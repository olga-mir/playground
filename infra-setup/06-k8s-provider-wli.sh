#!/bin/bash

set -eoux pipefail

# Use PROJECT_ID from environment
if [ -z "$PROJECT_ID" ]; then
  echo "ERROR: PROJECT_ID environment variable is not set"
  exit 1
fi


export MGMT_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_MGMT_CLUSTER}"
export APPS_DEV_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_APPS_DEV_CLUSTER}"

# Use the existing provider Kubernetes service account
PROVIDER_KSA="provider-kubernetes-fd7ab5be249e"
PROVIDER_KSA_NAMESPACE="crossplane-system"
GSA_NAME="crossplane-gke-provider"
PROVIDER_CONFIG_NAME="kubernetes-gke-provider"

echo "=== Setting up Workload Identity Federation for Crossplane ==="
echo "Project ID: $PROJECT_ID"
echo "Management Cluster Context: $MGMT_CLUSTER_CONTEXT"
echo "Apps Dev Cluster Context: $APPS_DEV_CLUSTER_CONTEXT"
echo "Provider KSA: $PROVIDER_KSA in namespace $PROVIDER_KSA_NAMESPACE"

# Verify the provider service account exists
if ! kubectl --context="${MGMT_CLUSTER_CONTEXT}" get serviceaccount ${PROVIDER_KSA} -n ${PROVIDER_KSA_NAMESPACE} &>/dev/null; then
  echo "ERROR: Service account ${PROVIDER_KSA} not found in namespace ${PROVIDER_KSA_NAMESPACE}"
  echo "Please verify the Kubernetes provider is installed correctly"
  exit 1
fi

echo "=== Creating Google Service Account ==="
# Check if GSA already exists
if gcloud iam service-accounts describe ${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com &>/dev/null; then
  echo "Google service account ${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com already exists"
else
  gcloud iam service-accounts create ${GSA_NAME} \
    --display-name="Crossplane GKE Provider"
  echo "Created Google service account ${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
fi

echo "=== Granting GKE Admin Permissions ==="
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/container.admin"

echo "=== Binding GSA to KSA with Workload Identity ==="
gcloud iam service-accounts add-iam-policy-binding ${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[${PROVIDER_KSA_NAMESPACE}/${PROVIDER_KSA}]"

echo "=== Annotating Kubernetes Service Account ==="
kubectl --context="${MGMT_CLUSTER_CONTEXT}" annotate serviceaccount ${PROVIDER_KSA} -n ${PROVIDER_KSA_NAMESPACE} \
  iam.gke.io/gcp-service-account=${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com --overwrite

# k get crd providerconfigs.kubernetes.crossplane.io -o yaml | less
# https://github.com/crossplane-contrib/provider-kubernetes/blob/d8049de66f67ef1dff522e75cd4a42c642ace50b/package/crds/kubernetes.crossplane.io_providerconfigs.yaml#L173
# https://github.com/crossplane-contrib/provider-kubernetes/blob/d8049de66f67ef1dff522e75cd4a42c642ace50b/examples/provider/provider-config-with-secret-google-identity.yaml#L6
