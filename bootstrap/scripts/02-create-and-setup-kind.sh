#!/bin/bash

set -eoux pipefail

KIND_TEST_CLUSTER_NAME=kind-test-cluster
REPO_ROOT=$(git rev-parse --show-toplevel)
CROSSPLANE_VERSION="v2.0.0-rc.1"
FLUX_VERSION="v2.6.4"


if ! kind get clusters | grep -q $KIND_TEST_CLUSTER_NAME; then
  echo "Cluster $KIND_TEST_CLUSTER_NAME does not exist. Creating..."
  kind create cluster --name $KIND_TEST_CLUSTER_NAME --config $REPO_ROOT/bootstrap/kind/kind-config.yaml
else
  echo "Cluster $KIND_TEST_CLUSTER_NAME already exists."
fi

# Crossplane installation and configuration is now handled by Flux
# The HelmRelease and providers will be deployed automatically via GitOps



echo "Setting up FluxCD ${FLUX_VERSION} on ${KIND_TEST_CLUSTER_NAME}"
kubectl config use-context kind-${KIND_TEST_CLUSTER_NAME} #TODO - explicit param to all commands

# Upgrade FluxCD CLI using brew if installed via brew
if command -v flux &> /dev/null; then
    echo "FluxCD CLI found, checking version..."
    if ! flux version --client 2>/dev/null | grep -q "${FLUX_VERSION}"; then
        echo "Upgrading FluxCD CLI to ${FLUX_VERSION}..."
        brew upgrade fluxcd/tap/flux
    else
        echo "FluxCD CLI ${FLUX_VERSION} already installed"
    fi
else
    echo "FluxCD CLI not found. Please install flux CLI first."
    exit 1
fi

# Verify FluxCD CLI installation
set +x
flux version --client
echo "Bootstrapping FluxCD..."
GITHUB_TOKEN=${GITHUB_FLUX_PLAYGROUND_PAT} flux bootstrap github \
  --owner=${GITHUB_DEMO_REPO_OWNER} \
  --repository=${GITHUB_DEMO_REPO_NAME} \
  --branch=base-refactor \
  --path=./bootstrap/kind/flux \
  --personal
set -x

echo "FluxCD bootstrap completed successfully!"

# Wait for FluxCD to be ready
echo "Waiting for FluxCD to be ready..."
kubectl wait --for=condition=ready pod -l app=source-controller -n flux-system --timeout=300s
kubectl wait --for=condition=ready pod -l app=kustomize-controller -n flux-system --timeout=300s
kubectl wait --for=condition=ready pod -l app=helm-controller -n flux-system --timeout=100s
kubectl wait --for=condition=ready pod -l app=notification-controller -n flux-system --timeout=100s

echo "FluxCD is ready!"

echo "Creating GCP credentials secret..."
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

sleep 30
flux get all -A
