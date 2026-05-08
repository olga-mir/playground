#!/bin/bash

set -eoux pipefail

KIND_TEST_CLUSTER_NAME=kind-test-cluster
REPO_ROOT=$(git rev-parse --show-toplevel)
CROSSPLANE_VERSION="v2.2.0"
KIND_CLUSTER_CONTEXT="kind-${KIND_TEST_CLUSTER_NAME}"

# echo "Setting up GCP infrastructure (VPC and subnets)..."
# "${REPO_ROOT}/scripts/setup-gcp-once.sh"

# Create kind cluster if it doesn't exist
if ! kind get clusters | grep -q $KIND_TEST_CLUSTER_NAME; then
  echo "Cluster $KIND_TEST_CLUSTER_NAME does not exist. Creating..."
  kind create cluster --name $KIND_TEST_CLUSTER_NAME --config $REPO_ROOT/bootstrap/kind/kind-config.yaml
else
  echo "Cluster $KIND_TEST_CLUSTER_NAME already exists."
fi

# Verify flux CLI is available (used for reconciliation checks later)
if ! command -v flux &> /dev/null; then
    echo "FluxCD CLI not found. Please install flux CLI first."
    exit 1
fi

echo "Pre-creating required secrets and configmaps before Flux Operator install..."

# Create flux-system namespace if it doesn't exist (needed for secrets/configmaps)
kubectl --context "${KIND_CLUSTER_CONTEXT}" create namespace flux-system --dry-run=client -o yaml | kubectl --context "${KIND_CLUSTER_CONTEXT}" apply -f -

echo "Creating Crossplane variables ConfigMap for Flux substituteFrom..."
kubectl --context "${KIND_CLUSTER_CONTEXT}" create configmap platform-config \
    --namespace flux-system \
    --from-literal=PROJECT_ID="${PROJECT_ID}" \
    --from-literal=REGION="${REGION}" \
    --from-literal=ZONE="${ZONE}" \
    --from-literal=GKE_CONTROL_PLANE_CLUSTER="${GKE_CONTROL_PLANE_CLUSTER}" \
    --from-literal=GKE_APPS_DEV_CLUSTER="${GKE_APPS_DEV_CLUSTER}" \
    --from-literal=GKE_VPC="${GKE_VPC}" \
    --from-literal=CONTROL_PLANE_SUBNET_NAME="${CONTROL_PLANE_SUBNET_NAME}" \
    --from-literal=APPS_DEV_SUBNET_NAME="${APPS_DEV_SUBNET_NAME}" \
    --dry-run=client -o yaml | kubectl --context "${KIND_CLUSTER_CONTEXT}" apply -f -

echo "Creating platform secrets for Flux substituteFrom..."
export BASE64_ENCODED_GCP_CREDS=$(base64 -w 0 < "${CROSSPLANE_GSA_KEY_FILE}")
kubectl --context "${KIND_CLUSTER_CONTEXT}" create secret generic platform-secrets \
    --namespace flux-system \
    --from-literal=GITHUB_FLUX_PLAYGROUND_PAT="${GITHUB_FLUX_PLAYGROUND_PAT}" \
    --from-literal=BASE64_ENCODED_GCP_CREDS="${BASE64_ENCODED_GCP_CREDS}" \
    --dry-run=client -o yaml | kubectl --context "${KIND_CLUSTER_CONTEXT}" apply -f -

echo "Creating GitHub webhook token secret for notification provider..."
kubectl --context "${KIND_CLUSTER_CONTEXT}" create secret generic github-webhook-token \
    --namespace flux-system \
    --from-literal=token="${GITHUB_FLUX_PLAYGROUND_PAT}" \
    --dry-run=client -o yaml | kubectl --context "${KIND_CLUSTER_CONTEXT}" apply -f -
unset BASE64_ENCODED_GCP_CREDS

echo "Creating flux-system secret with GitHub App credentials..."
# The FluxInstance references this secret via spec.sync.pullSecret and spec.sync.provider: github.
# The Flux Operator never overwrites this secret, so GitHub App credentials persist across reconciliations.
kubectl --context "${KIND_CLUSTER_CONTEXT}" create secret generic flux-system \
    --namespace flux-system \
    --from-literal=githubAppID="${GITHUB_APP_ID}" \
    --from-literal=githubAppInstallationID="${GITHUB_APP_INSTALLATION_ID}" \
    --from-file=githubAppPrivateKey="${GITHUB_APP_PRIVATE_KEY_FILE}" \
    --dry-run=client -o yaml | kubectl --context "${KIND_CLUSTER_CONTEXT}" apply -f -

echo "Installing Flux Operator via Helm..."
helm upgrade --install flux-operator oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator --version 0.48.0 \
    --namespace flux-system \
    --kube-context "${KIND_CLUSTER_CONTEXT}" \
    --wait \
    --timeout=5m

echo "Applying FluxInstance manifest..."
kubectl --context "${KIND_CLUSTER_CONTEXT}" apply -f "${REPO_ROOT}/kubernetes/clusters/kind/flux-system/flux-instance.yaml"

echo "Waiting for FluxInstance to be ready (installs Flux components and begins sync)..."
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=Ready fluxinstance/flux -n flux-system --timeout=600s

echo "FluxCD bootstrap completed successfully!"

# Wait for FluxCD controllers to be ready
echo "Waiting for FluxCD controllers to be ready..."
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=ready pod -l app=source-controller -n flux-system --timeout=300s
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=ready pod -l app=kustomize-controller -n flux-system --timeout=300s
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=ready pod -l app=helm-controller -n flux-system --timeout=100s
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=ready pod -l app=notification-controller -n flux-system --timeout=100s

echo "FluxCD is ready!"
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=Ready kustomization/flux-system -n flux-system --timeout=300s

# Create crossplane-system namespace (needed for GCP credentials)
kubectl --context "${KIND_CLUSTER_CONTEXT}" create namespace crossplane-system --dry-run=client -o yaml | kubectl --context "${KIND_CLUSTER_CONTEXT}" apply -f -

echo "Creating GCP credentials secret..."
kubectl --context "${KIND_CLUSTER_CONTEXT}" create secret generic gcp-creds \
    --namespace crossplane-system \
    --from-file=credentials="${CROSSPLANE_GSA_KEY_FILE}" \
    --dry-run=client -o yaml | kubectl --context "${KIND_CLUSTER_CONTEXT}" apply -f -
# NOTE: the secret also needs to be in each XR namespace (control-plane, apps-dev).
# Those namespaces are created by Flux (clusters kustomization), so we copy after Flux syncs.
# See copy_gcp_creds_to_xr_namespaces() called after crossplane-compositions is ready.

echo "Waiting for Flux to sync all resources..."
flux get all -A

echo "Waiting for Crossplane kustomizations to be applied by Flux..."
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=Ready kustomization/crossplane-install -n flux-system --timeout=5m
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=Ready kustomization/crossplane-providers -n flux-system --timeout=5m

# Seems to be timing issue with this kustomization and it waits for next cycle after hitting
# "dependency not ready" on the first attempt. Not sure what is going on here, but this kustomization needs a kick in a right time. (TODO)
sleep 5
set +e
flux reconcile ks crossplane-configs -n flux-system --timeout=2m
flux reconcile ks crossplane-configs -n flux-system --timeout=2m
flux reconcile ks crossplane-configs -n flux-system --timeout=2m
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=Ready kustomization/crossplane-configs -n flux-system --timeout=5m
set -e

echo "Waiting for Crossplane to be ready..."
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=healthy providers.pkg.crossplane.io --all --timeout=600s
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=healthy functions.pkg.crossplane.io --all --timeout=600s

echo "Waiting for Flux to deploy Crossplane compositions..."
# Wait for compositions kustomization to be ready before checking XRDs
if kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=ready kustomization/crossplane-compositions -n flux-system --timeout=300s; then
    echo "Compositions deployed, waiting for XRDs to be established..."
    kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=established xrd --all --timeout=180s
else
    echo "⚠️  Compositions kustomization not ready yet - XRDs will be available once Flux completes the dependency chain"
    echo "   You can check progress with: flux get kustomizations -A"
fi

# Pre-create XR namespaces and copy gcp-creds BEFORE clusters kustomization applies GKECluster XRs
# This ensures ProviderConfigs can authenticate before managed resources try to provision
echo "Pre-creating XR namespaces and copying GCP credentials..."
for ns in control-plane apps-dev; do
    kubectl --context "${KIND_CLUSTER_CONTEXT}" create namespace "${ns}" --dry-run=client -o yaml | kubectl --context "${KIND_CLUSTER_CONTEXT}" apply -f -
done

# Copy gcp-creds secret to each namespace before clusters kustomization applies
secret_json=$(kubectl --context "${KIND_CLUSTER_CONTEXT}" get secret gcp-creds -n crossplane-system -o json \
    | jq 'del(.metadata.namespace,.metadata.resourceVersion,.metadata.uid,.metadata.creationTimestamp,.metadata.annotations,.metadata.ownerReferences)')
for ns in control-plane apps-dev; do
    echo "Copying gcp-creds to namespace ${ns}..."
    echo "${secret_json}" | kubectl --context "${KIND_CLUSTER_CONTEXT}" apply -n "${ns}" -f -
done

# Wait for clusters kustomization
echo "Waiting for clusters kustomization to apply GKECluster XRs..."
kubectl --context "${KIND_CLUSTER_CONTEXT}" wait --for=condition=ready kustomization/clusters -n flux-system --timeout=300s || true

# Function to wait for a cluster to be ready using Composite Resources
wait_for_cluster_ready() {
    local composite_name="$1"
    local composite_namespace="$2"
    local max_retries=50  # x45 sec
    local retry_count=0

    while [ $retry_count -lt $max_retries ]; do
        if kubectl --context "${KIND_CLUSTER_CONTEXT}" get gkeclusters.platform.tornado-demo.io "${composite_name}" -n "${composite_namespace}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | grep -q "True"; then
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
wait_for_cluster_ready "control-plane-cluster" "control-plane"

echo "✅ Control-plane cluster is ready!"
echo "Monitor detailed progress with: kubectl --context ${KIND_CLUSTER_CONTEXT} get gkeclusters -w"

# Get cluster credentials for local kubectl access
echo "🔑 Setting up local cluster credentials..."
gcloud container clusters get-credentials "${GKE_CONTROL_PLANE_CLUSTER}" --zone "${REGION}-a" --project "${PROJECT_ID}"

set +x
echo ""
echo "🎉 Cluster provisioning complete!"
echo ""
echo "Next steps:"
echo "1. Flux notifications will automatically trigger GitHub Actions"
echo "2. GitHub Actions will bootstrap Flux on the new GKE clusters"
echo "3. Flux will deploy applications to the clusters"
echo ""
echo "Monitor GitHub Actions: https://github.com/${GITHUB_DEMO_REPO_OWNER}/${GITHUB_DEMO_REPO_NAME}/actions"
echo "Check cluster status: kubectl --context ${KIND_CLUSTER_CONTEXT} get gkeclusters -A"
