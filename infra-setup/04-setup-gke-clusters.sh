#!/bin/bash

set -eoux pipefail

# Parse command line arguments
SKIP_ARGO=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-argo)
            SKIP_ARGO=true
            shift
            ;;
        *)
            echo "Unknown parameter: $1"
            exit 1
            ;;
    esac
done

# Environment variables that need to be explicitly set
set +x
required_vars=(
    PROJECT_ID
    REGION
    GKE_MGMT_CLUSTER
    GKE_APPS_DEV_CLUSTER
    CROSSPLANE_GSA_KEY_FILE
    GITHUB_DEMO_REPO_OWNER
    GITHUB_DEMO_REPO_NAME
    GITHUB_DEST_ORG_NAME
    GITHUB_DEMO_REPO_PAT
    GITHUB_DEST_ORG_REPO_LVL_PAT # For repo-level operations in the destination org
    GITHUB_DEST_ORG_ORG_LVL_PAT  # For org-level operations in the destination org
)

echo "Checking required environment variables..."
all_set=true
for var in "${required_vars[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "Error: Environment variable $var is not set."
        all_set=false
    fi
done
set -x

if [ "$all_set" = false ]; then
    exit 1
fi

#export MGMT_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${REGION}_${GKE_MGMT_CLUSTER}"
#export APPS_DEV_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${REGION}_${GKE_APPS_DEV_CLUSTER}"
export MGMT_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_MGMT_CLUSTER}"
export APPS_DEV_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_APPS_DEV_CLUSTER}"
export CROSSPLANE_VERSION="v2.0.0-preview.1"
export ARGOCD_VERSION="v2.14.10"
export ARGOCD_CHART_VERSION="7.8.26"
export ARGOCD_NAMESPACE="argocd"
export CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME="github-provider-credentials-org"
export CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME="github-provider-credentials-repo"
export CROSSPLANE_GITHUB_SECRET_NAMESPACE="crossplane-system"

export REPO_ROOT=$(git rev-parse --show-toplevel)


# Function to configure Argo CD to connect to another cluster
install_and_configure_argocd_cluster() {
  local target_cluster_name="$1"
  local target_context="$2"

  # Get the kubeconfig for the target cluster
  kubectl --context="${target_context}" config view --raw --minify > "${target_cluster_name}.kubeconfig"

  # Extract the server address and certificate authority data from the kubeconfig
  SERVER=$(yq e '.clusters[0].cluster.server' "${target_cluster_name}.kubeconfig")
  CERTIFICATE_AUTHORITY_DATA=$(yq e '.clusters[0].cluster.certificate-authority-data' "${target_cluster_name}.kubeconfig")
  TOKEN=$(yq e '.users[0].user.token' "${target_cluster_name}.kubeconfig" || echo "")
  if [ "$TOKEN" = "null" ] || [ -z "$TOKEN" ]; then
      # Get token from current context
      TOKEN=$(kubectl --context="${target_context}" create token default)
  fi

  # https://github.com/argoproj/argo-helm/blob/main/charts/argo-cd/values.yaml
  # ApplicationSet controller = https://github.com/argoproj/argo-helm/blob/b02220a33f94e2d09af50c85a4f4a13284a29aa7/charts/argo-cd/values.yaml#L2828
  if ! helm status argocd --kube-context="${MGMT_CLUSTER_CONTEXT}" --namespace argocd &>/dev/null; then

    VALUES_TEMPLATE="${REPO_ROOT}/infra-setup/manifests/templates/argocd-values.yaml.tpl"
    VALUES_RENDERED="${REPO_ROOT}/infra-setup/manifests/rendered/argocd-values.yaml"

    envsubst < "${VALUES_TEMPLATE}" > "${VALUES_RENDERED}"

    helm install argocd argo/argo-cd \
      --kube-context="${MGMT_CLUSTER_CONTEXT}" \
      --namespace argocd \
      --create-namespace \
      --version "${ARGOCD_CHART_VERSION}" \
      -f "${VALUES_RENDERED}"

  else
    echo "ArgoCD is already installed in the management cluster. Skipping installation."
  fi

  # Create a secret for the cluster credentials
  kubectl --context="${MGMT_CLUSTER_CONTEXT}" -n "${ARGOCD_NAMESPACE}" create secret generic "${target_cluster_name}-cluster-secret" \
    --from-literal=server="${SERVER}" \
    --from-literal=token="${TOKEN}" \
    --from-literal=certificateAuthorityData="${CERTIFICATE_AUTHORITY_DATA}" \
    --dry-run=client -o yaml | kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f - || { echo "Error creating cluster secret for Argo in Mangement cluster"; exit 1; }

  rm "${target_cluster_name}.kubeconfig"

  # bloody argo CMP mess!
  # check infra-setup/README.md how it should look like
  kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f ${REPO_ROOT}/infra-setup/manifests/rendered/argo-env-plugin-configmap.yaml

  echo "Argo CD on management cluster configured to connect to ${target_cluster_name}"
}

# Function to wait for ArgoCD repo server pods to be ready
wait_for_argocd_ready() {
  echo "Waiting for ArgoCD repo server to be ready..."

  # Maximum number of retries
  local max_retries=30
  local retry_count=0
  local ready=false

  while [ $retry_count -lt $max_retries ] && [ "$ready" = false ]; do
    # Check if pod with label app.kubernetes.io/name=argocd-repo-server is ready
    if kubectl --context="${MGMT_CLUSTER_CONTEXT}" -n "${ARGOCD_NAMESPACE}" wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-repo-server --timeout=10s >/dev/null 2>&1; then
      echo "ArgoCD repo server is ready!"
      ready=true
    else
      echo "Waiting for ArgoCD repo server to be ready... (${retry_count}/${max_retries})"
      retry_count=$((retry_count+1))
      sleep 10
    fi
  done

  if [ "$ready" = false ]; then
    echo "Timed out waiting for ArgoCD repo server to be ready"
    return 1
  fi

  return 0
}

# Function to add a repository to Argo CD
add_repo_to_argocd() {
  echo "Adding repository to Argo CD..."

  # Create a secret for the Git repository
  # This directly configures the repository in ArgoCD without needing separate ConfigMaps or kustomization
  echo Setting up secret for repo "https://github.com/${GITHUB_DEMO_REPO_OWNER}/${GITHUB_DEMO_REPO_NAME}.git"
  kubectl --context="${MGMT_CLUSTER_CONTEXT}" -n "${ARGOCD_NAMESPACE}" create secret generic "${GITHUB_DEMO_REPO_NAME}-repo" \
    --from-literal=type=git \
    --from-literal=url="https://github.com/${GITHUB_DEMO_REPO_OWNER}/${GITHUB_DEMO_REPO_NAME}.git" \
    --from-literal=username="${GITHUB_DEMO_REPO_OWNER}" \
    --from-literal=password="${GITHUB_DEMO_REPO_PAT}" \
    --dry-run=client -o yaml | kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f - || { echo "Error creating repo secret"; exit 1; }

  # Add a label to the secret so ArgoCD recognizes it as a repository configuration
  kubectl --context="${MGMT_CLUSTER_CONTEXT}" -n "${ARGOCD_NAMESPACE}" label secret "${GITHUB_DEMO_REPO_NAME}-repo" \
    argocd.argoproj.io/secret-type=repository --overwrite || { echo "Error labeling repo secret"; exit 1; }

  echo "Repository ${GITHUB_DEMO_REPO_OWNER}/${GITHUB_DEMO_REPO_NAME} added to Argo CD successfully."
}

# Install Argo "spoke" on apps-dev
install_argo_agent_on_target_cluster() {
  echo "Starting ArgoCD installation..."

  if ! helm status argocd-agent --kube-context "${APPS_DEV_CLUSTER_CONTEXT}" --namespace argocd &>/dev/null; then
      helm install argocd-agent argo/argo-cd \
          --kube-context="${APPS_DEV_CLUSTER_CONTEXT}" \
          --namespace argocd \
          --create-namespace \
          --version "${ARGOCD_CHART_VERSION}" \
          --set global.image.tag=$ARGOCD_VERSION \
          --set controller.enable=false \
          --set dex.enabled=false \
          --set server.enable=false \
          --set applicationSet.enabled=false \
          --set notifications.enabled=false \
          --set repoServer.replicas=1 \
          --set redis.enabled=false \
          --set configs.params."controller\\.k8s\\.clusterAdminAccess"=true || { echo "Error installing ArgoCD agent"; exit 1; }
  else
      echo "ArgoCD agent is already installed in the ${GKE_APPS_DEV_CLUSTER} cluster. Skipping installation."
  fi
}

echo "Starting setup..."

# Install ArgoCD only if not skipped
if [ "$SKIP_ARGO" = false ]; then
    install_and_configure_argocd_cluster "apps-dev-cluster" "${APPS_DEV_CLUSTER_CONTEXT}"
    add_repo_to_argocd
    wait_for_argocd_ready
    kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f ${REPO_ROOT}/platform/argocd-foundations/argo-projects.yaml
    sleep 3
    kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f ${REPO_ROOT}/platform/argocd-foundations
    install_argo_agent_on_target_cluster
else
    echo "Skipping ArgoCD installation and configuration..."
fi

echo "Installing Crossplane on management cluster..."

if ! helm status crossplane --kube-context "${MGMT_CLUSTER_CONTEXT}" --namespace crossplane-system &>/dev/null; then
    helm install crossplane crossplane-preview/crossplane \
        --kube-context="${MGMT_CLUSTER_CONTEXT}" \
        --namespace crossplane-system \
        --create-namespace \
        --version "${CROSSPLANE_VERSION}" || { echo "Error installing crossplane"; exit 1; }
    sleep 10
else
    echo "Crossplane is already installed in the management cluster. Skipping installation."
fi

# Create secret for GCP provider
if ! kubectl --context="${MGMT_CLUSTER_CONTEXT}" get secret gcp-creds -n crossplane-system >/dev/null 2>&1; then
    kubectl --context="${MGMT_CLUSTER_CONTEXT}" create secret generic gcp-creds \
        --namespace crossplane-system \
        --from-file=credentials.json="${CROSSPLANE_GSA_KEY_FILE}" || { echo "Error creating gcp-creds secret"; exit 1; }
fi

# Create secret for apps-dev cluster kubeconfig
echo "Creating secret for apps-dev cluster kubeconfig..."

# Get cluster info from the apps-dev cluster context
APPS_SERVER=$(kubectl config view --minify --flatten -o jsonpath="{.clusters[?(@.name == \"${APPS_DEV_CLUSTER_CONTEXT}\")].cluster.server}" --context="${APPS_DEV_CLUSTER_CONTEXT}")
APPS_CA_DATA=$(kubectl config view --minify --flatten -o jsonpath="{.clusters[?(@.name == \"${APPS_DEV_CLUSTER_CONTEXT}\")].cluster.certificate-authority-data}" --context="${APPS_DEV_CLUSTER_CONTEXT}")

KUBECONFIG_CONTENT=$(cat <<EOF
apiVersion: v1
kind: Config
clusters:
- name: apps-dev-cluster
  cluster:
    server: ${APPS_SERVER}
    certificate-authority-data: ${APPS_CA_DATA}
contexts:
- name: apps-dev-cluster
  context:
    cluster: apps-dev-cluster
    user: kubernetes-provider
current-context: apps-dev-cluster
users:
- name: kubernetes-provider
  user: {}
EOF
)

# Create the secret
kubectl --context="${MGMT_CLUSTER_CONTEXT}" create secret generic apps-dev-cluster-config \
    --namespace crossplane-system \
    --from-literal=kubeconfig="${KUBECONFIG_CONTENT}" \
    --dry-run=client -o yaml | kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f -

# Create secret for Crossplane GitHub provider (ORGANIZATION LEVEL access)
# This secret will be referenced by a ProviderConfig for org-level operations (e.g., creating repositories)
set +x
echo "Creating Crossplane GitHub provider secret for ORG LEVEL access: ${CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME}"
if ! kubectl --context="${MGMT_CLUSTER_CONTEXT}" get secret "${CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" >/dev/null 2>&1; then
    # Create the secret with proper JSON format for Crossplane GitHub provider
    kubectl --context="${MGMT_CLUSTER_CONTEXT}" create secret generic "${CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" \
        --from-literal=credentials="{\"token\":\"${GITHUB_DEST_ORG_ORG_LVL_PAT}\",\"owner\":\"${GITHUB_DEST_ORG_NAME}\"}" || { echo "Error creating GitHub org-level provider secret"; exit 1; }
fi
set -x

# Create secret for Crossplane GitHub provider (REPOSITORY LEVEL access)
# This secret will be referenced by a ProviderConfig for repo-level operations (e.g., managing files, deploy keys within existing repos)
set +x
echo "Creating Crossplane GitHub provider secret for REPO LEVEL access: ${CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME}"
if ! kubectl --context="${MGMT_CLUSTER_CONTEXT}" get secret "${CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" >/dev/null 2>&1; then
    # Create the secret with proper JSON format for Crossplane GitHub provider
    kubectl --context="${MGMT_CLUSTER_CONTEXT}" create secret generic "${CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" \
        --from-literal=credentials="{\"token\":\"${GITHUB_DEST_ORG_REPO_LVL_PAT}\",\"owner\":\"${GITHUB_DEST_ORG_NAME}\"}" || { echo "Error creating GitHub repo-level provider secret"; exit 1; }
fi
set -x

set +x
echo Creating AI platform API Key secret for kagent

if ! kubectl --context="${MGMT_CLUSTER_CONTEXT}" get namespace kagent-system &>/dev/null; then
  kubectl --context="${MGMT_CLUSTER_CONTEXT}" create namespace kagent-system
  echo "Created kagent-system namespace"
fi

kubectl --context="${MGMT_CLUSTER_CONTEXT}" create secret generic kagent-anthropic \
  --from-literal=ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY} \
  -n kagent-system

kubectl --context="${MGMT_CLUSTER_CONTEXT}" create secret generic kagent-openai \
  --from-literal=OPENAI_API_KEY=${OPENAI_API_KEY} \
  -n kagent-system

# Not sure why some CRDs are not installed, despite Gateway API enabled
kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/experimental-install.yaml
