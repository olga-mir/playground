#!/bin/bash

set -eoux pipefail

# Usage: ./bootstrap-cluster.sh <cluster-type>
# cluster-type: control-plane or apps-dev (or any workload cluster name)

CLUSTER_TYPE=${1:-}

if [[ -z "$CLUSTER_TYPE" ]]; then
    echo "❌ Usage: $0 <cluster-type>"
    echo "   cluster-type: control-plane, apps-dev, or any workload cluster name"
    echo ""
    echo "Examples:"
    echo "  $0 control-plane    # Bootstrap control-plane cluster with Flux + Crossplane"
    echo "  $0 apps-dev         # Bootstrap apps-dev workload cluster with Flux only"
    exit 1
fi

export REPO_ROOT=$(git rev-parse --show-toplevel)

echo "🚀 Starting complete bootstrap for ${CLUSTER_TYPE} cluster..."
echo ""

# Step 1: Bootstrap Flux
echo "📦 Step 1: Bootstrapping Flux..."
"${REPO_ROOT}/bootstrap/scripts/flux-bootstrap-cluster.sh" "$CLUSTER_TYPE"

echo ""
echo "🔐 Step 2: Setting up secrets..."
"${REPO_ROOT}/bootstrap/scripts/setup-cluster-secrets.sh" "$CLUSTER_TYPE"

echo ""
echo "✅ Complete bootstrap for ${CLUSTER_TYPE} cluster finished successfully!"
echo ""

# Set cluster-specific variables for final status
case "$CLUSTER_TYPE" in
    "control-plane")
        export CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_CONTROL_PLANE_CLUSTER}"
        ;;
    "apps-dev")
        export CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_APPS_DEV_CLUSTER}"
        ;;
    *)
        export CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${CLUSTER_TYPE}"
        ;;
esac

echo "📊 Final status check:"
kubectl --context="${CLUSTER_CONTEXT}" get nodes
echo ""
kubectl --context="${CLUSTER_CONTEXT}" get kustomizations -n flux-system
echo ""

if [[ "$CLUSTER_TYPE" == "control-plane" ]]; then
    echo "🔍 Crossplane status:"
    kubectl --context="${CLUSTER_CONTEXT}" get providers.pkg.crossplane.io || echo "No Crossplane providers found"
fi

echo ""
echo "🔗 Useful commands:"
echo "kubectl --context=${CLUSTER_CONTEXT} get all -n flux-system"
echo "kubectl --context=${CLUSTER_CONTEXT} logs -n flux-system -l app=kustomize-controller"