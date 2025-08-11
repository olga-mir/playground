#!/bin/bash

set -eoux pipefail

export REPO_ROOT=$(git rev-parse --show-toplevel)
export CONTROL_PLANE_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_CONTROL_PLANE_CLUSTER}"

set +x
export GITHUB_TOKEN="${GITHUB_FLUX_PLAYGROUND_PAT}"
set -x

echo "🚀 Bootstrapping Flux on control-plane cluster: ${GKE_CONTROL_PLANE_CLUSTER}"

echo "📦 Installing Flux on control-plane cluster..."
GITHUB_TOKEN=${GITHUB_FLUX_PLAYGROUND_PAT} flux bootstrap github \
  --owner=${GITHUB_DEMO_REPO_OWNER} \
  --repository=${GITHUB_DEMO_REPO_NAME} \
  --branch=base-refactor \
  --path=clusters/control-plane \
  --context="${CONTROL_PLANE_CONTEXT}"
  --personal

echo "⏳ Waiting for Flux components to be ready..."
kubectl --context="${CONTROL_PLANE_CONTEXT}" wait --for=condition=ready pod -l app=source-controller -n flux-system --timeout=300s
kubectl --context="${CONTROL_PLANE_CONTEXT}" wait --for=condition=ready pod -l app=kustomize-controller -n flux-system --timeout=300s
kubectl --context="${CONTROL_PLANE_CONTEXT}" wait --for=condition=ready pod -l app=helm-controller -n flux-system --timeout=300s
kubectl --context="${CONTROL_PLANE_CONTEXT}" wait --for=condition=ready pod -l app=notification-controller -n flux-system --timeout=300s

# Create cluster-vars ConfigMap for control-plane specific substitutions
echo "🔧 Creating cluster-vars ConfigMap..."
kubectl --context="${CONTROL_PLANE_CONTEXT}" create configmap cluster-vars \
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
    --dry-run=client -o yaml | kubectl --context="${CONTROL_PLANE_CONTEXT}" apply -f -

# Create GCP credentials secret for Crossplane
echo "🔑 Creating GCP credentials secret..."
kubectl --context="${CONTROL_PLANE_CONTEXT}" create namespace crossplane-system --dry-run=client -o yaml | kubectl --context="${CONTROL_PLANE_CONTEXT}" apply -f -
kubectl --context="${CONTROL_PLANE_CONTEXT}" create secret generic gcp-creds \
    --namespace crossplane-system \
    --from-file=credentials="${CROSSPLANE_GSA_KEY_FILE}" \
    --dry-run=client -o yaml | kubectl --context="${CONTROL_PLANE_CONTEXT}" apply -f -

echo "⏳ Waiting for GitRepository flux-system to be ready..."
kubectl --context="${CONTROL_PLANE_CONTEXT}" wait --for=condition=ready gitrepository/flux-system -n flux-system --timeout=300s

echo "⏳ Waiting for initial Kustomization flux-system to be ready..."
kubectl --context="${CONTROL_PLANE_CONTEXT}" wait --for=condition=ready kustomization/flux-system -n flux-system --timeout=600s

echo "🔄 Checking Crossplane installation..."
# Wait for Crossplane to be installed by Flux
kubectl --context="${CONTROL_PLANE_CONTEXT}" wait --for=condition=ready kustomization/crossplane-providers -n flux-system --timeout=900s

echo "🏥 Waiting for Crossplane providers to be healthy..."
kubectl --context="${CONTROL_PLANE_CONTEXT}" wait --for=condition=healthy providers.pkg.crossplane.io --all --timeout=600s

echo "📋 Waiting for Crossplane compositions to be ready..."
kubectl --context="${CONTROL_PLANE_CONTEXT}" wait --for=condition=ready kustomization/crossplane-compositions -n flux-system --timeout=300s

echo "🎯 Waiting for workload cluster definitions to be applied..."
kubectl --context="${CONTROL_PLANE_CONTEXT}" wait --for=condition=ready kustomization/crossplane-workload-clusters -n flux-system --timeout=300s

echo "✅ Flux bootstrap on control-plane cluster completed successfully!"
echo ""
echo "📊 Current status:"
kubectl --context="${CONTROL_PLANE_CONTEXT}" get kustomizations -n flux-system
echo ""
echo "🔍 Check detailed status with:"
echo "kubectl --context=${CONTROL_PLANE_CONTEXT} get gitrepositories,kustomizations,helmreleases -n flux-system"
