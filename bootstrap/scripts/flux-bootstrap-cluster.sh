#!/bin/bash

set -eoux pipefail

# Usage: ./flux-bootstrap-cluster.sh <cluster-type>
# cluster-type: control-plane or apps-dev (or any workload cluster name)

CLUSTER_TYPE=${1:-}

if [[ -z "$CLUSTER_TYPE" ]]; then
    echo "❌ Usage: $0 <cluster-type>"
    echo "   cluster-type: control-plane, apps-dev, or any workload cluster name"
    exit 1
fi

export REPO_ROOT=$(git rev-parse --show-toplevel)

# Set cluster-specific variables based on type
case "$CLUSTER_TYPE" in
    "control-plane")
        export CLUSTER_NAME="${GKE_CONTROL_PLANE_CLUSTER}"
        export CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_CONTROL_PLANE_CLUSTER}"
        export FLUX_PATH="clusters/control-plane"
        export IS_CONTROL_PLANE=true
        ;;
    "apps-dev")
        export CLUSTER_NAME="${GKE_APPS_DEV_CLUSTER}"
        export CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_APPS_DEV_CLUSTER}"
        export FLUX_PATH="clusters/apps-dev"
        export IS_CONTROL_PLANE=false
        ;;
    *)
        # Generic workload cluster
        export CLUSTER_NAME="$CLUSTER_TYPE"
        export CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${CLUSTER_TYPE}"
        export FLUX_PATH="clusters/${CLUSTER_TYPE}"
        export IS_CONTROL_PLANE=false
        ;;
esac

set +x
export GITHUB_TOKEN="${GITHUB_FLUX_PLAYGROUND_PAT}"

echo "🚀 Bootstrapping Flux on ${CLUSTER_TYPE} cluster: ${CLUSTER_NAME}"

# Check if we can connect to the cluster
echo "🔍 Checking connection to ${CLUSTER_TYPE} cluster..."
kubectl --context="${CLUSTER_CONTEXT}" version

echo "📦 Installing Flux on ${CLUSTER_TYPE} cluster..."
GITHUB_TOKEN=${GITHUB_FLUX_PLAYGROUND_PAT} flux bootstrap github \
  --owner=${GITHUB_DEMO_REPO_OWNER} \
  --repository=${GITHUB_DEMO_REPO_NAME} \
  --branch=base-refactor \
  --path=${FLUX_PATH} \
  --context="${CLUSTER_CONTEXT}" \
  --personal
set -x

echo "⏳ Waiting for Flux components to be ready..."
kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready pod -l app=source-controller -n flux-system --timeout=300s
kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready pod -l app=kustomize-controller -n flux-system --timeout=300s
kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready pod -l app=helm-controller -n flux-system --timeout=300s
kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready pod -l app=notification-controller -n flux-system --timeout=300s

# Create cluster-vars ConfigMap for cluster-specific substitutions
echo "🔧 Creating cluster-vars ConfigMap..."
kubectl --context="${CLUSTER_CONTEXT}" create configmap cluster-vars \
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
    --from-literal=CLUSTER_NAME="${CLUSTER_NAME}" \
    --from-literal=CLUSTER_TYPE="${CLUSTER_TYPE}" \
    --dry-run=client -o yaml | kubectl --context="${CLUSTER_CONTEXT}" apply -f -

# Only create Crossplane-specific resources for control-plane cluster
if [[ "$IS_CONTROL_PLANE" == "true" ]]; then
    echo "🔑 Creating GCP credentials secret for Crossplane..."
    kubectl --context="${CLUSTER_CONTEXT}" create namespace crossplane-system --dry-run=client -o yaml | kubectl --context="${CLUSTER_CONTEXT}" apply -f -
    kubectl --context="${CLUSTER_CONTEXT}" create secret generic gcp-creds \
        --namespace crossplane-system \
        --from-file=credentials="${CROSSPLANE_GSA_KEY_FILE}" \
        --dry-run=client -o yaml | kubectl --context="${CLUSTER_CONTEXT}" apply -f -

    echo "⏳ Waiting for GitRepository flux-system to be ready..."
    kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready gitrepository/flux-system -n flux-system --timeout=300s

    echo "⏳ Waiting for initial Kustomization flux-system to be ready..."
    kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready kustomization/flux-system -n flux-system --timeout=600s

    echo "🔄 Checking Crossplane installation..."
    # Wait for Crossplane to be installed by Flux
    kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready kustomization/crossplane-providers -n flux-system --timeout=900s || echo "⚠️  Crossplane providers not found - may not be configured for this cluster type"

    echo "🏥 Waiting for Crossplane providers to be healthy..."
    kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=healthy providers.pkg.crossplane.io --all --timeout=600s || echo "⚠️  Some providers may still be starting"

    echo "📋 Waiting for Crossplane compositions to be ready..."
    kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready kustomization/crossplane-compositions -n flux-system --timeout=300s || echo "⚠️  Crossplane compositions not found - may not be configured"

    echo "🎯 Waiting for workload cluster definitions to be applied..."
    kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready kustomization/crossplane-workload-clusters -n flux-system --timeout=300s || echo "⚠️  Workload cluster definitions not found - may not be configured"
else
    echo "⏳ Waiting for GitRepository flux-system to be ready..."
    kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready gitrepository/flux-system -n flux-system --timeout=300s

    echo "⏳ Waiting for initial Kustomization flux-system to be ready..."
    kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready kustomization/flux-system -n flux-system --timeout=600s

    echo "📦 Checking platform applications deployment..."
    # Wait for platform applications to be deployed
    kubectl --context="${CLUSTER_CONTEXT}" wait --for=condition=ready kustomizations --all -n flux-system --timeout=300s || echo "⚠️  Some kustomizations may still be syncing"
fi

echo "✅ Flux bootstrap on ${CLUSTER_TYPE} cluster completed successfully!"
echo ""
echo "📊 Current status:"
kubectl --context="${CLUSTER_CONTEXT}" get kustomizations -n flux-system
echo ""
echo "🔍 Check detailed status with:"
echo "kubectl --context=${CLUSTER_CONTEXT} get gitrepositories,kustomizations,helmreleases -n flux-system"