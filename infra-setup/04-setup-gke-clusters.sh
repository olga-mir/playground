#!/bin/bash

set -eoux pipefail

export KIND_CROSSPLANE_CONTEXT="kind-kind-test-cluster"

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

export MGMT_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_MGMT_CLUSTER}"
export APPS_DEV_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_APPS_DEV_CLUSTER}"
export ARGOCD_NAMESPACE="argocd"
export CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME="github-provider-credentials-org"
export CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME="github-provider-credentials-repo"
export CROSSPLANE_GITHUB_SECRET_NAMESPACE="crossplane-system"

export REPO_ROOT=$(git rev-parse --show-toplevel)

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

echo "Waiting for ArgoCD to be ready (installed by Composition)..."
wait_for_argocd_ready

echo "ArgoCD multi-cluster setup now handled by Crossplane Helm compositions..."

echo "Adding repository to ArgoCD..."
add_repo_to_argocd

kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f ${REPO_ROOT}/infra-setup/manifests/argo-env-plugin-configmap.yaml
kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f ${REPO_ROOT}/platform/argocd-foundations/argo-projects.yaml
sleep 3
kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f ${REPO_ROOT}/platform/argocd-foundations

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
  -n kagent-system \
  --dry-run=client -o yaml | kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f -

kubectl --context="${MGMT_CLUSTER_CONTEXT}" create secret generic kagent-openai \
  --from-literal=OPENAI_API_KEY=${OPENAI_API_KEY} \
  -n kagent-system \
  --dry-run=client -o yaml | kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f -

# Not sure why some CRDs are not installed, despite Gateway API enabled
kubectl --context="${MGMT_CLUSTER_CONTEXT}" apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/experimental-install.yaml

echo "Setup completed! Clusters are now managed by Crossplane compositions."
echo "ArgoCD and Crossplane installations are handled declaratively."
