#!/bin/bash

set -eoux pipefail

KIND_TEST_CLUSTER_NAME=kind-test-cluster
REPO_ROOT=$(git rev-parse --show-toplevel)
CROSSPLANE_VERSION="v2.0.0-rc.1"
FLUX_VERSION="v2.6.4"


if ! kind get clusters | grep -q $KIND_TEST_CLUSTER_NAME; then
  echo "Cluster $KIND_TEST_CLUSTER_NAME does not exist. Creating..."
  kind create cluster --name $KIND_TEST_CLUSTER_NAME --config $REPO_ROOT/infra-setup/kind-config.yaml
else
  echo "Cluster $KIND_TEST_CLUSTER_NAME already exists."
fi


# https://docs.crossplane.io/v2.0-preview/get-started/install/

#helm install crossplane \
#--namespace crossplane-system \
#--create-namespace crossplane-preview/crossplane \
#--version $CROSSPLANE_VERSION

# install release instructions: https://github.com/crossplane/crossplane/releases/tag/v2.0.0-rc.1
helm repo add crossplane-stable https://charts.crossplane.io/stable --force-update
helm install crossplane --namespace crossplane-system --create-namespace crossplane-stable/crossplane --devel


# Wait for Crossplane CRDs to be established
sleep 10
until kubectl get crd providers.pkg.crossplane.io &>/dev/null; do
  echo "Waiting for CRD providers.pkg.crossplane.io to be created..."
  sleep 5
done

# gke-provider is not templated, but rendered folder is .gitignor'ed
# so it is an exception that can be applied directly
kubectl apply -f ${REPO_ROOT}/infra-setup/manifests/templates/gke-provider.yaml

# Wait for CRDs to be established
sleep 10

for crd in clusters.container.gcp-beta.upbound.io \
          nodepools.container.gcp-beta.upbound.io; do
  until kubectl get crd $crd &>/dev/null; do
    echo "Waiting for CRD $crd to be created..."
    sleep 5
  done
done



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
flux version --client
echo "Bootstrapping FluxCD..."
GITHUB_TOKEN=${GITHUB_FLUX_PLAYGROUND_PAT} flux bootstrap github \
  --owner=${GITHUB_DEMO_REPO_OWNER} \
  --repository=${GITHUB_DEMO_REPO_NAME} \
  --branch=base-refactor \
  --path=./infra-setup/manifests/flux-root \
  --personal
set -x

echo "FluxCD bootstrap completed successfully!"

# Wait for FluxCD to be ready
echo "Waiting for FluxCD to be ready..."
kubectl wait --for=condition=ready pod -l app=source-controller -n flux-system --timeout=300s
kubectl wait --for=condition=ready pod -l app=kustomize-controller -n flux-system --timeout=300s
kubectl wait --for=condition=ready pod -l app=helm-controller -n flux-system --timeout=300s
kubectl wait --for=condition=ready pod -l app=notification-controller -n flux-system --timeout=300s

echo "FluxCD is ready!"
flux get all
