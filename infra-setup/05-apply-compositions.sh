#!/bin/bash

set -eoux pipefail

# Environment variables that need to be explicitly set
set +x
required_vars=(
    PROJECT_ID
    REGION
    ZONE
    GKE_MGMT_CLUSTER
    GKE_APPS_DEV_CLUSTER
    GKE_VPC
    KIND_CROSSPLANE_CONTEXT
    MGMT_SUBNET_NAME
    APPS_DEV_SUBNET_NAME
    GITHUB_DEMO_REPO_OWNER
    GITHUB_DEMO_REPO_NAME
    GITHUB_DEMO_REPO_PAT
    CROSSPLANE_GSA_KEY_FILE
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

export REPO_ROOT=$(git rev-parse --show-toplevel)

echo "Installing Crossplane compositions and functions..."

# Install required functions
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f - <<EOF
apiVersion: pkg.crossplane.io/v1beta1
kind: Function
metadata:
  name: function-go-templating
spec:
  package: xpkg.upbound.io/crossplane-contrib/function-go-templating:v0.10.0
---
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-helm
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-helm:v0.21.0
---
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v0.18.0
EOF

echo "Waiting for providers and functions to be ready..."
sleep 30

kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=healthy provider --all --timeout=300s
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=healthy function --all --timeout=300s

echo "Applying Crossplane XRD and Composition..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f "${REPO_ROOT}/infra-setup/crossplane-config/compositions/"

echo "Waiting for XRD to be established..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=established xrd --all --timeout=60s

echo "Creating GCP credentials secret..."
if [ -z "${CROSSPLANE_GSA_KEY_FILE:-}" ]; then
    echo "Error: CROSSPLANE_GSA_KEY_FILE environment variable is not set."
    exit 1
fi

kubectl --context="${KIND_CROSSPLANE_CONTEXT}" create secret generic gcp-creds \
    --namespace crossplane-system \
    --from-file=credentials="${CROSSPLANE_GSA_KEY_FILE}" \
    --dry-run=client -o yaml | kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f -

echo "Creating GCP ProviderConfig..."
envsubst < "${REPO_ROOT}/infra-setup/crossplane-config/provider-configs/gcp-provider-config.yaml.tpl" | \
    kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f -

echo "Creating GKE clusters using compositions..."

# Create management cluster
echo "Creating management cluster..."
envsubst < "${REPO_ROOT}/infra-setup/crossplane-config/examples/mgmt-cluster-claim.yaml" | \
  kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f -

# Create apps cluster  
echo "Creating apps cluster..."
envsubst < "${REPO_ROOT}/infra-setup/crossplane-config/examples/apps-cluster-claim.yaml" | \
  kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f -

echo "Clusters creation initiated via Crossplane compositions!"
echo "Monitor progress with: kubectl --context=${KIND_CROSSPLANE_CONTEXT} get gkeclusters -w"
