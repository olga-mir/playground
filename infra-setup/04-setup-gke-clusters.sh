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

# ArgoCD functions disabled - migrated to FluxCD
# wait_for_argocd_ready() { ... }
# add_repo_to_argocd() { ... }

echo "ArgoCD setup skipped - migrated to FluxCD"

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
