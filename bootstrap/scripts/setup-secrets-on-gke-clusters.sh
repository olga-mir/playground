#!/bin/bash

set -eoux pipefail

# Environment variables that need to be explicitly set
set +x
# required_vars=(
#     PROJECT_ID
#     REGION
#     GITHUB_DEMO_REPO_OWNER
#     GITHUB_DEMO_REPO_NAME
#     GITHUB_DEST_ORG_NAME
#     GITHUB_DEMO_REPO_PAT
#     GITHUB_DEST_ORG_REPO_LVL_PAT # For repo-level operations in the destination org
#     GITHUB_DEST_ORG_ORG_LVL_PAT  # For org-level operations in the destination org
# )

#echo "Checking required environment variables..."
#all_set=true
#for var in "${required_vars[@]}"; do
#    if [ -z "${!var:-}" ]; then
#        echo "Error: Environment variable $var is not set."
#        all_set=false
#    fi
#done
#set -x

export REPO_ROOT=$(git rev-parse --show-toplevel)
export CONTROL_PLANE_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_CONTROL_PLANE_CLUSTER}"
export CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME="github-provider-credentials-org"
export CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME="github-provider-credentials-repo"
export CROSSPLANE_GITHUB_SECRET_NAMESPACE="crossplane-system"


# Create secret for Crossplane GitHub provider (ORGANIZATION LEVEL access)
# This secret will be referenced by a ProviderConfig for org-level operations (e.g., creating repositories)
set +x
echo "Creating Crossplane GitHub provider secret for ORG LEVEL access: ${CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME}"
if ! kubectl --context="${CONTROL_PLANE_CONTEXT}" get secret "${CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" >/dev/null 2>&1; then
    # Create the secret with proper JSON format for Crossplane GitHub provider
    kubectl --context="${CONTROL_PLANE_CONTEXT}" create secret generic "${CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" \
        --from-literal=credentials="{\"token\":\"${GITHUB_DEST_ORG_ORG_LVL_PAT}\",\"owner\":\"${GITHUB_DEST_ORG_NAME}\"}" || { echo "Error creating GitHub org-level provider secret"; exit 1; }
fi
set -x

# Create secret for Crossplane GitHub provider (REPOSITORY LEVEL access)
# This secret will be referenced by a ProviderConfig for repo-level operations (e.g., managing files, deploy keys within existing repos)
set +x
echo "Creating Crossplane GitHub provider secret for REPO LEVEL access: ${CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME}"
if ! kubectl --context="${CONTROL_PLANE_CONTEXT}" get secret "${CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" >/dev/null 2>&1; then
    # Create the secret with proper JSON format for Crossplane GitHub provider
    kubectl --context="${CONTROL_PLANE_CONTEXT}" create secret generic "${CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" \
        --from-literal=credentials="{\"token\":\"${GITHUB_DEST_ORG_REPO_LVL_PAT}\",\"owner\":\"${GITHUB_DEST_ORG_NAME}\"}" || { echo "Error creating GitHub repo-level provider secret"; exit 1; }
fi
set -x

set +x
echo Creating AI platform API Key secret for kagent

if ! kubectl --context="${CONTROL_PLANE_CONTEXT}" get namespace kagent-system &>/dev/null; then
  kubectl --context="${CONTROL_PLANE_CONTEXT}" create namespace kagent-system
  echo "Created kagent-system namespace"
fi

kubectl --context="${CONTROL_PLANE_CONTEXT}" create secret generic kagent-anthropic \
  --from-literal=ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY} \
  -n kagent-system

kubectl --context="${CONTROL_PLANE_CONTEXT}" create secret generic kagent-openai \
  --from-literal=OPENAI_API_KEY=${OPENAI_API_KEY} \
  -n kagent-system

# Not sure why some CRDs are not installed, despite Gateway API enabled
kubectl --context="${CONTROL_PLANE_CONTEXT}" apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/experimental-install.yaml
