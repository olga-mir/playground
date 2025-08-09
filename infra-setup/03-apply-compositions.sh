#!/bin/bash

set -eoux pipefail

export KIND_CROSSPLANE_CONTEXT="kind-kind-test-cluster"

export REPO_ROOT=$(git rev-parse --show-toplevel)

echo "Creating GCP credentials secret..."
if [ -z "${CROSSPLANE_GSA_KEY_FILE:-}" ]; then
    echo "Error: CROSSPLANE_GSA_KEY_FILE environment variable is not set."
    exit 1
fi

kubectl --context="${KIND_CROSSPLANE_CONTEXT}" create secret generic gcp-creds \
    --namespace crossplane-system \
    --from-file=credentials="${CROSSPLANE_GSA_KEY_FILE}" \
    --dry-run=client -o yaml | kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f -

echo "Creating Crossplane variables ConfigMap for Flux substituteFrom..."
set +x
export BASE64_ENCODED_GCP_CREDS=$(base64 -w 0 < "${CROSSPLANE_GSA_KEY_FILE}")
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" create configmap crossplane-vars \
    --namespace flux-system \
    --from-literal=PROJECT_ID="${PROJECT_ID}" \
    --from-literal=REGION="${REGION}" \
    --from-literal=ZONE="${ZONE}" \
    --from-literal=GKE_CONTROL_PLANE_CLUSTER="${GKE_CONTROL_PLANE_CLUSTER}" \
    --from-literal=GKE_APPS_DEV_CLUSTER="${GKE_APPS_DEV_CLUSTER}" \
    --from-literal=GKE_VPC="${GKE_VPC}" \
    --from-literal=CONTROL_PLANE_SUBNET_NAME="${CONTROL_PLANE_SUBNET_NAME}" \
    --from-literal=APPS_DEV_SUBNET_NAME="${APPS_DEV_SUBNET_NAME}" \
    --from-literal=GITHUB_DEMO_REPO_OWNER="${GITHUB_DEMO_REPO_OWNER}" \
    --from-literal=GITHUB_DEMO_REPO_PAT="${GITHUB_DEMO_REPO_PAT}" \
    --from-literal=BASE64_ENCODED_GCP_CREDS="${BASE64_ENCODED_GCP_CREDS}" \
    --dry-run=client -o yaml | kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f -
unset BASE64_ENCODED_GCP_CREDS
set -x

echo "Applying Flux Crossplane source..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f "${REPO_ROOT}/infra-setup/flux/crossplane-source.yaml"

echo "Waiting for Flux to sync Crossplane resources..."
echo "This includes providers, compositions, and cluster Composite Resources"
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=Ready kustomization/crossplane-base -n flux-system --timeout=600s
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=healthy providers.pkg.crossplane.io --all --timeout=300s
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=healthy functions.pkg.crossplane.io --all --timeout=300s
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=established xrd --all --timeout=60s
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=Ready kustomization/crossplane-composite-resources -n flux-system --timeout=300s

echo "Clusters creation initiated via Crossplane compositions!"

echo "Waiting for clusters to be ready..."
echo "This may take 10-15 minutes for GKE clusters to provision..."

# Function to wait for a cluster to be ready using Composite Resources
wait_for_cluster_ready() {
    local composite_name="$1"
    local composite_namespace="$2"
    local max_retries=60  # x45 sec
    local retry_count=0

    while [ $retry_count -lt $max_retries ]; do
        if kubectl --context="${KIND_CROSSPLANE_CONTEXT}" get gkeclusters.platform.tornado-demo.io "${composite_name}" -n "${composite_namespace}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | grep -q "True"; then
            echo "✅ Cluster $composite_name is ready!"
            return 0
        fi

        echo "⏳ Waiting for cluster $composite_name to be ready... (${retry_count}/${max_retries})"
        retry_count=$((retry_count+1))

        # Handle interruption properly
        if ! sleep 45; then
            echo "❌ Interrupted waiting for cluster $composite_name"
            return 1
        fi
    done

    echo "❌ Timeout waiting for cluster $composite_name to be ready"
    return 1
}

# Wait for both clusters sequentially to handle Ctrl+C properly
wait_for_cluster_ready "control-plane-cluster" "gkecluster-control-plane"
wait_for_cluster_ready "apps-dev-cluster" "gkecluster-apps-dev"

echo "✅ All clusters are ready!"
echo "Monitor detailed progress with: kubectl --context=${KIND_CROSSPLANE_CONTEXT} get gkeclusters -w"

# Get cluster credentials for local kubectl access
echo "🔑 Setting up local cluster credentials..."
gcloud container clusters get-credentials "${GKE_APPS_DEV_CLUSTER}" --zone "${REGION}-a" --project "${PROJECT_ID}"
gcloud container clusters get-credentials "${GKE_CONTROL_PLANE_CLUSTER}" --zone "${REGION}-a" --project "${PROJECT_ID}"

echo ""
echo "🎉 Cluster provisioning complete!"
echo ""
echo "Next steps:"
echo "1. Flux notifications will automatically trigger GitHub Actions"
echo "2. GitHub Actions will bootstrap Flux on the new GKE clusters"
echo "3. Flux will deploy applications to the clusters"
echo ""
echo "Monitor GitHub Actions: https://github.com/${GITHUB_DEMO_REPO_OWNER}/${GITHUB_DEMO_REPO_NAME}/actions"
echo "Check cluster status: kubectl --context=${KIND_CROSSPLANE_CONTEXT} get gkeclusters -A"
