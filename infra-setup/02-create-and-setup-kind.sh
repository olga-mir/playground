#!/bin/bash

set -eoux pipefail

KIND_TEST_CLUSTER_NAME=kind-test-cluster
REPO_ROOT=$(git rev-parse --show-toplevel)

if ! kind get clusters | grep -q $KIND_TEST_CLUSTER_NAME; then
  echo "Cluster $KIND_TEST_CLUSTER_NAME does not exist. Creating..."
  kind create cluster --name $KIND_TEST_CLUSTER_NAME --config $REPO_ROOT/infra-setup/kind-config.yaml
else
  echo "Cluster $KIND_TEST_CLUSTER_NAME already exists."
fi


### Setup Crossplane ###

# https://docs.crossplane.io/v2.0-preview/get-started/install/

# helm repo add crossplane-preview https://charts.crossplane.io/preview
# helm repo update
# helm install --dry-run --debug

CROSSPLANE_VERSION="v2.0.0-preview.1"

helm install crossplane \
--namespace crossplane-system \
--create-namespace crossplane-preview/crossplane \
--version $CROSSPLANE_VERSION


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
