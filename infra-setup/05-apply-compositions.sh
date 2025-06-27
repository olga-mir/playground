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

echo "Creating namespaces..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f "${REPO_ROOT}/infra-setup/crossplane-config/namespaces/"

echo "Applying Crossplane RBAC..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f "${REPO_ROOT}/infra-setup/crossplane-config/rbac/"

echo "Installing Crossplane functions..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f "${REPO_ROOT}/infra-setup/crossplane-config/functions/"

echo "Installing Crossplane providers..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f "${REPO_ROOT}/infra-setup/crossplane-config/providers/"

echo "Waiting for providers and functions to be ready..."
sleep 45

kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=healthy providers --all --timeout=300s
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=healthy function --all --timeout=300s

echo "Applying Crossplane XRD and Composition..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f "${REPO_ROOT}/infra-setup/crossplane-config/compositions/"
sleep 15

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

echo "Creating management cluster..."
envsubst < "${REPO_ROOT}/infra-setup/crossplane-config/claims/mgmt-cluster-claim.yaml" | \
  kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f -

echo "Creating apps cluster..."
envsubst < "${REPO_ROOT}/infra-setup/crossplane-config/claims/apps-cluster-claim.yaml" | \
  kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f -

echo "Clusters creation initiated via Crossplane compositions!"

echo "Waiting for clusters to be ready..."
echo "This may take 10-15 minutes for GKE clusters to provision..."

# Function to wait for a cluster to be ready using the actual cluster resource
wait_for_cluster_ready() {
    local cluster_name="$1"
    local max_retries=60  # x45 sec
    local retry_count=0

    while [ $retry_count -lt $max_retries ]; do
        if kubectl --context="${KIND_CROSSPLANE_CONTEXT}" get cluster "${cluster_name}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | grep -q "True"; then
            echo "✅ Cluster $cluster_name is ready!"
            return 0
        fi

        echo "⏳ Waiting for cluster $cluster_name to be ready... (${retry_count}/${max_retries})"
        retry_count=$((retry_count+1))

        # Handle interruption properly
        if ! sleep 45; then
            echo "❌ Interrupted waiting for cluster $cluster_name"
            return 1
        fi
    done

    echo "❌ Timeout waiting for cluster $cluster_name to be ready"
    return 1
}

# Wait for both clusters sequentially to handle Ctrl+C properly
wait_for_cluster_ready "${GKE_MGMT_CLUSTER}"
wait_for_cluster_ready "${GKE_APPS_DEV_CLUSTER}"

echo "✅ All clusters are ready!"
echo "Monitor detailed progress with: kubectl --context=${KIND_CROSSPLANE_CONTEXT} get gkeclusters -w"
