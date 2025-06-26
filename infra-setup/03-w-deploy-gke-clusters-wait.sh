#!/bin/bash

set -eoux pipefail

# Environment variables that need to be explicitly set
required_vars=(
    GKE_MGMT_CLUSTER
    GKE_APPS_DEV_CLUSTER
)

echo "Checking required environment variables..."
all_set=true
for var in "${required_vars[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "Error: Environment variable $var is not set."
        all_set=false
    fi
done

if [ "$all_set" = false ]; then
    exit 1
fi
echo "All required variables are set."
echo

# This can take a while!
# managed/container.gcp-beta.upbound.io/v1beta1, kind=cluster  failed to observe the resource: [{0 Error when reading or editing Container Cluster "mgmt":
# Get "https://container.googleapis.com/v1beta1/projects/<PROJ>/locations/<REGION>/clusters/mgmt?alt=json&prettyPrint=false":
# dial tcp [2404:6800:4006:80b::200a]:443: connect: network is unreachable  []}]
# ^ this is transient
timeout=900
interval=60

start_time=$(date +%s)
while true; do
    all_ready=true

    for cluster in "${GKE_MGMT_CLUSTER}" "${GKE_APPS_DEV_CLUSTER}"; do
        if ! kubectl wait --for=condition=ready --timeout="${interval}s" cluster.container.gcp-beta.upbound.io/"${cluster}" -n gke; then
            all_ready=false
        fi
    done

    if [ "$all_ready" = true ]; then
        echo "All clusters are ready."
        break
    fi

    current_time=$(date +%s)
    elapsed_time=$((current_time - start_time))
    if [ "$elapsed_time" -ge "$timeout" ]; then
        echo "Timeout reached while waiting for clusters to be ready."
    fi

    echo "Retrying in $interval seconds..."
    sleep $interval
done

# most of the times clusters are usable at this point even if there is no explicit ready status
# continue opportunistically, worst case it'll fail in the next steps
gcloud container clusters get-credentials "${GKE_APPS_DEV_CLUSTER}" --zone "${REGION}-a" --project "${PROJECT_ID}"
gcloud container clusters get-credentials "${GKE_MGMT_CLUSTER}" --zone "${REGION}-a" --project "${PROJECT_ID}"

# Wait for node pools to be ready (nodepools don't have to be ready commpletely to proceed with next steps)
# TODO hardcoded context
#kubectl wait --context=kind-kind-test-cluster --for=condition=ready --timeout=30s nodepool.container.gcp-beta.upbound.io/"${GKE_MGMT_CLUSTER}-pool" -n gke || true
#kubectl wait --context=kind-kind-test-cluster --for=condition=ready --timeout=30s nodepool.container.gcp-beta.upbound.io/"${GKE_APPS_DEV_CLUSTER}-pool" -n gke || true
