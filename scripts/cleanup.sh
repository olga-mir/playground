#!/bin/bash

set -euo pipefail

echo "🧹 Starting hierarchical cluster cleanup..."
echo "⚠️  This will permanently delete all clusters!"
echo ""

export GKE_CONTROL_PLANE_CLUSTER="${GKE_CONTROL_PLANE_CLUSTER:-control-plane}"
export GKE_APPS_DEV_CLUSTER="${GKE_APPS_DEV_CLUSTER:-apps-dev}"
export KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-kind-test-cluster}"

# Step 1: Delete kind cluster (stops managing control-plane)
echo "🔄 Step 1: Deleting bootstrap cluster (kind)..."
if kind get clusters | grep -q "$KIND_CLUSTER_NAME"; then
    echo "   Deleting kind cluster: $KIND_CLUSTER_NAME..."
    kind delete cluster --name "$KIND_CLUSTER_NAME"
    echo "   ✅ Kind cluster deleted"
else
    echo "   ⚠️  Kind cluster doesn't exist, skipping"
fi

# Step 2: Delete control-plane cluster (stops managing workload clusters)
echo ""
echo "🎛️  Step 2: Deleting control-plane cluster..."
if gcloud container clusters describe "$GKE_CONTROL_PLANE_CLUSTER" --zone="$ZONE" --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "   Deleting control-plane cluster: $GKE_CONTROL_PLANE_CLUSTER..."
    gcloud container clusters delete "$GKE_CONTROL_PLANE_CLUSTER" --zone="$ZONE" --project="$PROJECT_ID" --quiet
    echo "   ✅ Control-plane cluster deleted"
else
    echo "   ⚠️  Control-plane cluster doesn't exist, skipping"
fi

# Step 3: Delete workload clusters in parallel
echo ""
echo "🚀 Step 3: Deleting workload clusters in parallel..."

# Start workload cluster deletions in background
WORKLOAD_PIDS=()

if gcloud container clusters describe "$GKE_APPS_DEV_CLUSTER" --zone="$ZONE" --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "   Starting deletion of apps-dev cluster..."
    gcloud container clusters delete "$GKE_APPS_DEV_CLUSTER" --zone="$ZONE" --project="$PROJECT_ID" --quiet &
    WORKLOAD_PIDS+=($!)
else
    echo "   ⚠️  Apps-dev cluster doesn't exist, skipping"
fi

# Add more workload clusters here in the future
# if gcloud container clusters describe "$GKE_STAGING_CLUSTER" --zone="$ZONE" --project="$PROJECT_ID" >/dev/null 2>&1; then
#     echo "   Starting deletion of staging cluster..."
#     gcloud container clusters delete "$GKE_STAGING_CLUSTER" --zone="$ZONE" --project="$PROJECT_ID" --quiet &
#     WORKLOAD_PIDS+=($!)
# fi

# Wait for workload clusters to be deleted
if [ ${#WORKLOAD_PIDS[@]} -gt 0 ]; then
    echo "   Waiting for workload clusters to be deleted..."
    for pid in "${WORKLOAD_PIDS[@]}"; do
        if wait "$pid"; then
            echo "   ✅ Workload cluster deletion completed"
        else
            echo "   ⚠️  Workload cluster deletion may have failed"
        fi
    done
fi

echo ""
echo "✅ Cleanup completed!"
echo ""
echo "Deletion order:"
echo "  1. 🔄 Bootstrap cluster (kind) - stops managing control-plane"
echo "  2. 🎛️  Control-plane cluster - stops managing workload clusters"
echo "  3. 🚀 Workload clusters (parallel) - no longer managed"
echo ""
echo "💡 This sequence prevents Flux/Crossplane from trying to restore deleted clusters."
