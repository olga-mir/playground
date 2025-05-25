#!/bin/bash

set -eoux pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)

TEMPLATE_DIR="${REPO_ROOT}/infra-setup/manifests/templates"
RENDERED_DIR="${REPO_ROOT}/infra-setup/manifests/rendered"

PROVIDER_CONFIG_FILE_TPL="${TEMPLATE_DIR}/providers-config.yaml.tpl"
PROVIDER_CONFIG_FILE_RENDERED="${RENDERED_DIR}/providers-config.yaml"

# Function to wait for GCP provider to be ready
wait_for_provider() {
    echo "Waiting for GCP provider to be ready..."
    while ! kubectl get providers.pkg.crossplane.io provider-gcp-beta-container -o jsonpath="{.status.conditions[?(@.type=='Healthy')].status}" | grep -q "True"; do
        echo "GCP provider not ready yet, waiting..."
        sleep 10
    done
    echo "GCP provider is ready"
}

# --- Reduced Required Variables ---
# Variables that need to be explicitly set
required_vars=(
    PROJECT_ID
    REGION
    GKE_VPC
    GKE_MGMT_CLUSTER
    MGMT_NODE_MACHINE_TYPE
    MGMT_NODE_COUNT
    GKE_APPS_DEV_CLUSTER
    APPS_DEV_NODE_MACHINE_TYPE
    APPS_DEV_NODE_COUNT
    CROSSPLANE_GSA_KEY_FILE
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

if ! kubectl get namespace gke >/dev/null 2>&1; then
  kubectl create namespace gke
fi

if ! kubectl get secret gcp-creds -n crossplane-system >/dev/null 2>&1; then
  kubectl create secret generic gcp-creds \
    --namespace crossplane-system \
    --from-file=credentials="${CROSSPLANE_GSA_KEY_FILE}"
fi

envsubst < "${PROVIDER_CONFIG_FILE_TPL}" > "${PROVIDER_CONFIG_FILE_RENDERED}"
kubectl apply -f "${PROVIDER_CONFIG_FILE_RENDERED}"

wait_for_provider

export MGMT_CLUSTER_TEMPLATE="${TEMPLATE_DIR}/mgmt-cluster.yaml.tpl"
export APPS_DEV_CLUSTER_TEMPLATE="${TEMPLATE_DIR}/apps-dev-cluster.yaml.tpl"

envsubst < "${MGMT_CLUSTER_TEMPLATE}" > "${RENDERED_DIR}/mgmt-cluster.yaml"
envsubst < "${APPS_DEV_CLUSTER_TEMPLATE}" > "${RENDERED_DIR}/apps-dev-cluster.yaml"
echo "Templates rendered to ${RENDERED_DIR}"
echo

kubectl apply -f "${RENDERED_DIR}/mgmt-cluster.yaml"
kubectl apply -f "${RENDERED_DIR}/apps-dev-cluster.yaml"
echo
