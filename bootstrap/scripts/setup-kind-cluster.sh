#!/bin/bash

set -eoux pipefail

KIND_TEST_CLUSTER_NAME=kind-test-cluster
REPO_ROOT=$(git rev-parse --show-toplevel)
CROSSPLANE_VERSION="v2.0.0-rc.1"
FLUX_VERSION="v2.7.5"
KIND_CLUSTER_CONTEXT="kind-${KIND_TEST_CLUSTER_NAME}"

# Create kind cluster if it doesn't exist
if ! kind get clusters | grep -q $KIND_TEST_CLUSTER_NAME; then
  echo "Cluster $KIND_TEST_CLUSTER_NAME does not exist. Creating..."
  kind create cluster --name $KIND_TEST_CLUSTER_NAME --config $REPO_ROOT/bootstrap/kind/kind-config.yaml
else
  echo "Cluster $KIND_TEST_CLUSTER_NAME already exists."
fi

kubectl config use-context "${KIND_CLUSTER_CONTEXT}"

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
echo "Pre-creating required secrets and configmaps before Flux bootstrap..."

# Create flux-system namespace if it doesn't exist (needed for secrets/configmaps)
kubectl create namespace flux-system --dry-run=client -o yaml | kubectl apply -f -

echo "Creating Crossplane variables ConfigMap for Flux substituteFrom..."
kubectl create configmap platform-config \
    --namespace flux-system \
    --from-literal=PROJECT_ID="${PROJECT_ID}" \
    --from-literal=REGION="${REGION}" \
    --from-literal=ZONE="${ZONE}" \
    --from-literal=GKE_CONTROL_PLANE_CLUSTER="${GKE_CONTROL_PLANE_CLUSTER}" \
    --from-literal=GKE_APPS_DEV_CLUSTER="${GKE_APPS_DEV_CLUSTER}" \
    --from-literal=GKE_VPC="${GKE_VPC}" \
    --from-literal=CONTROL_PLANE_SUBNET_NAME="${CONTROL_PLANE_SUBNET_NAME}" \
    --from-literal=APPS_DEV_SUBNET_NAME="${APPS_DEV_SUBNET_NAME}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "Creating platform secrets for Flux substituteFrom..."
export BASE64_ENCODED_GCP_CREDS=$(base64 -w 0 < "${CROSSPLANE_GSA_KEY_FILE}")
kubectl create secret generic platform-secrets \
    --namespace flux-system \
    --from-literal=GITHUB_FLUX_PLAYGROUND_PAT="${GITHUB_FLUX_PLAYGROUND_PAT}" \
    --from-literal=BASE64_ENCODED_GCP_CREDS="${BASE64_ENCODED_GCP_CREDS}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "Creating GitHub webhook token secret for notification provider..."
kubectl create secret generic github-webhook-token \
    --namespace flux-system \
    --from-literal=token="${GITHUB_FLUX_PLAYGROUND_PAT}" \
    --dry-run=client -o yaml | kubectl apply -f -
unset BASE64_ENCODED_GCP_CREDS

echo "Bootstrapping FluxCD..."
GITHUB_TOKEN=${GITHUB_FLUX_PLAYGROUND_PAT} flux bootstrap github \
    --owner=${GITHUB_DEMO_REPO_OWNER} \
    --repository=${GITHUB_DEMO_REPO_NAME} \
    --branch=develop \
    --path=./kubernetes/clusters/kind \
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
kubectl wait --for=condition=Ready kustomization/flux-system -n flux-system --timeout=300s

# Create crossplane-system namespace (needed for GCP credentials)
kubectl create namespace crossplane-system --dry-run=client -o yaml | kubectl apply -f -

echo "Creating GCP credentials secret..."
kubectl create secret generic gcp-creds \
    --namespace crossplane-system \
    --from-file=credentials="${CROSSPLANE_GSA_KEY_FILE}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "Waiting for Flux to sync all resources..."
flux get all -A

echo "Waiting for Crossplane kustomizations to be applied by Flux..."
kubectl wait --for=condition=Ready kustomization/crossplane-install -n flux-system --timeout=5m
kubectl wait --for=condition=Ready kustomization/crossplane-providers -n flux-system --timeout=5m

# Seems to be timing issue with this kustomization and it waits for next cycle after hitting
# "dependency not ready" on the first attempt. Not sure what is going on here, but this kustomization needs a kick in a right time. (TODO)
sleep 5
set +e
flux reconcile ks crossplane-configs -n flux-system --timeout=2m
flux reconcile ks crossplane-configs -n flux-system --timeout=2m
flux reconcile ks crossplane-configs -n flux-system --timeout=2m
kubectl wait --for=condition=Ready kustomization/crossplane-configs -n flux-system --timeout=5m
set -e

echo "Waiting for Crossplane to be ready..."
kubectl wait --for=condition=healthy providers.pkg.crossplane.io --all --timeout=600s
kubectl wait --for=condition=healthy functions.pkg.crossplane.io --all --timeout=600s

echo "Waiting for Flux to deploy Crossplane compositions..."
# Wait for compositions kustomization to be ready before checking XRDs
if kubectl wait --for=condition=ready kustomization/crossplane-compositions -n flux-system --timeout=300s; then
    echo "Compositions deployed, waiting for XRDs to be established..."
    kubectl wait --for=condition=established xrd --all --timeout=180s
else
    echo "⚠️  Compositions kustomization not ready yet - XRDs will be available once Flux completes the dependency chain"
    echo "   You can check progress with: flux get kustomizations -A"
fi

# Function to wait for a cluster to be ready using Composite Resources
wait_for_cluster_ready() {
    local composite_name="$1"
    local composite_namespace="$2"
    local max_retries=50  # x45 sec
    local retry_count=0

    while [ $retry_count -lt $max_retries ]; do
        if kubectl get gkeclusters.platform.tornado-demo.io "${composite_name}" -n "${composite_namespace}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | grep -q "True"; then
            echo "✅ Cluster $composite_name is ready!"
            return 0
        fi

        echo "⏳ Waiting for cluster $composite_name to be ready... (${retry_count}/${max_retries})"
        retry_count=$((retry_count+1))

        if ! sleep 45; then
            echo "❌ Interrupted waiting for cluster $composite_name"
            return 1
        fi
    done

    echo "❌ Timeout waiting for cluster $composite_name to be ready"
    return 1
}

# Wait for control-plane cluster
wait_for_cluster_ready "control-plane-cluster" "gkecluster-control-plane"

echo "✅ Control-plane cluster is ready!"
echo "Monitor detailed progress with: kubectl get gkeclusters -w"

# Get cluster credentials for local kubectl access
echo "🔑 Setting up local cluster credentials..."
gcloud container clusters get-credentials "${GKE_CONTROL_PLANE_CLUSTER}" --zone "${REGION}-a" --project "${PROJECT_ID}"

echo ""
echo "🎉 Cluster provisioning complete!"
echo ""
echo "Next steps:"
echo "1. Flux notifications will automatically trigger GitHub Actions"
echo "2. GitHub Actions will bootstrap Flux on the new GKE clusters"
echo "3. Flux will deploy applications to the clusters"
echo ""
echo "Monitor GitHub Actions: https://github.com/${GITHUB_DEMO_REPO_OWNER}/${GITHUB_DEMO_REPO_NAME}/actions"
echo "Check cluster status: kubectl get gkeclusters -A"
