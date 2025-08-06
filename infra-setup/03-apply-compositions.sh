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
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" create configmap crossplane-vars \
    --namespace flux-system \
    --from-literal=PROJECT_ID="${PROJECT_ID}" \
    --from-literal=REGION="${REGION}" \
    --from-literal=ZONE="${ZONE}" \
    --from-literal=GKE_MGMT_CLUSTER="${GKE_MGMT_CLUSTER}" \
    --from-literal=GKE_APPS_DEV_CLUSTER="${GKE_APPS_DEV_CLUSTER}" \
    --from-literal=GKE_VPC="${GKE_VPC}" \
    --from-literal=MGMT_SUBNET_NAME="${MGMT_SUBNET_NAME}" \
    --from-literal=APPS_DEV_SUBNET_NAME="${APPS_DEV_SUBNET_NAME}" \
    --dry-run=client -o yaml | kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f -

echo "Applying Flux Crossplane source..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" apply -f "${REPO_ROOT}/infra-setup/manifests/flux-root/crossplane-source.yaml"

echo "Waiting for Flux to sync Crossplane resources..."
echo "This includes providers, compositions, and cluster claims"
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=Ready kustomization/crossplane-base -n flux-system --timeout=600s

echo "Waiting for providers and functions to be ready..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=healthy providers --all --timeout=300s
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=healthy function --all --timeout=300s

echo "Waiting for XRD to be established..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=established xrd --all --timeout=60s

echo "Applying cluster claims via Flux..."
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" wait --for=condition=Ready kustomization/crossplane-claims -n flux-system --timeout=300s

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

gcloud container clusters get-credentials "${GKE_APPS_DEV_CLUSTER}" --zone "${REGION}-a" --project "${PROJECT_ID}"
gcloud container clusters get-credentials "${GKE_MGMT_CLUSTER}" --zone "${REGION}-a" --project "${PROJECT_ID}"
