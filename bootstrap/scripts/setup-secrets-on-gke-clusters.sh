#!/bin/bash

set -eoux pipefail

# Usage: ./setup-cluster-secrets.sh <cluster-type>
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
        export IS_CONTROL_PLANE=true
        ;;
    "apps-dev")
        export CLUSTER_NAME="${GKE_APPS_DEV_CLUSTER}"
        export CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_APPS_DEV_CLUSTER}"
        export IS_CONTROL_PLANE=false
        ;;
    *)
        # Generic workload cluster
        export CLUSTER_NAME="$CLUSTER_TYPE"
        export CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${CLUSTER_TYPE}"
        export IS_CONTROL_PLANE=false
        ;;
esac

export CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME="github-provider-credentials-org"
export CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME="github-provider-credentials-repo"
export CROSSPLANE_GITHUB_SECRET_NAMESPACE="crossplane-system"

echo "🔐 Setting up secrets for ${CLUSTER_TYPE} cluster: ${CLUSTER_NAME}"

# Check if we can connect to the cluster
echo "🔍 Checking connection to ${CLUSTER_TYPE} cluster..."
kubectl --context="${CLUSTER_CONTEXT}" version

# Only create Crossplane-specific secrets for control-plane cluster
if [[ "$IS_CONTROL_PLANE" == "true" ]]; then
    echo "🏭 Setting up Crossplane secrets for control-plane cluster..."

    # Create secret for Crossplane GitHub provider (ORGANIZATION LEVEL access)
    set +x
    echo "Creating Crossplane GitHub provider secret for ORG LEVEL access: ${CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME}"
    if ! kubectl --context="${CLUSTER_CONTEXT}" get secret "${CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" >/dev/null 2>&1; then
        kubectl --context="${CLUSTER_CONTEXT}" create secret generic "${CROSSPLANE_GITHUB_ORG_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" \
            --from-literal=credentials="{\"token\":\"${GITHUB_DEST_ORG_ORG_LVL_PAT}\",\"owner\":\"${GITHUB_DEST_ORG_NAME}\"}" || { echo "Error creating GitHub org-level provider secret"; exit 1; }
        echo "✅ Created GitHub org-level provider secret"
    else
        echo "ℹ️  GitHub org-level provider secret already exists"
    fi
    set -x

    # Create secret for Crossplane GitHub provider (REPOSITORY LEVEL access)
    set +x
    echo "Creating Crossplane GitHub provider secret for REPO LEVEL access: ${CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME}"
    if ! kubectl --context="${CLUSTER_CONTEXT}" get secret "${CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" >/dev/null 2>&1; then
        kubectl --context="${CLUSTER_CONTEXT}" create secret generic "${CROSSPLANE_GITHUB_REPO_LEVEL_SECRET_NAME}" -n "${CROSSPLANE_GITHUB_SECRET_NAMESPACE}" \
            --from-literal=credentials="{\"token\":\"${GITHUB_DEST_ORG_REPO_LVL_PAT}\",\"owner\":\"${GITHUB_DEST_ORG_NAME}\"}" || { echo "Error creating GitHub repo-level provider secret"; exit 1; }
        echo "✅ Created GitHub repo-level provider secret"
    else
        echo "ℹ️  GitHub repo-level provider secret already exists"
    fi
    set -x
fi

# AI Platform secrets (workload clusters only - kagent/kgateway run on workload clusters)
if [[ "$IS_CONTROL_PLANE" == "false" ]]; then
    set +x
    echo "🤖 Creating AI platform API Key secrets for kagent on workload cluster..."

    if ! kubectl --context="${CLUSTER_CONTEXT}" get namespace kagent-system &>/dev/null; then
       kubectl --context="${CLUSTER_CONTEXT}" create namespace kagent-system
       echo "✅ Created kagent-system namespace"
    fi

    # Create Anthropic API key secret
    if ! kubectl --context="${CLUSTER_CONTEXT}" get secret kagent-anthropic -n kagent-system >/dev/null 2>&1; then
        kubectl --context="${CLUSTER_CONTEXT}" create secret generic kagent-anthropic \
          --from-literal=ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY} \
          -n kagent-system
        echo "✅ Created kagent-anthropic secret"
    else
        echo "ℹ️  kagent-anthropic secret already exists"
    fi

    # Create OpenAI API key secret
    if ! kubectl --context="${CLUSTER_CONTEXT}" get secret kagent-openai -n kagent-system >/dev/null 2>&1; then
        kubectl --context="${CLUSTER_CONTEXT}" create secret generic kagent-openai \
          --from-literal=OPENAI_API_KEY=${OPENAI_API_KEY} \
          -n kagent-system
        echo "✅ Created kagent-openai secret"
    else
        echo "ℹ️  kagent-openai secret already exists"
    fi
    set -x
fi

# Common secrets and resources for all clusters
echo "🌐 Setting up common resources..."

# Gateway API CRDs (needed for networking)
echo "📡 Installing Gateway API CRDs..."
kubectl --context="${CLUSTER_CONTEXT}" apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/experimental-install.yaml || echo "⚠️  Gateway API CRDs may already be installed"

# Application-specific secrets for workload clusters
if [[ "$IS_CONTROL_PLANE" == "false" ]]; then
    echo "📱 Setting up workload cluster specific secrets..."

    # Add any workload-cluster specific secret creation here
    # For example, application database credentials, service account keys, etc.
    # AI platform secrets are already created above

    echo "ℹ️  No additional workload cluster secrets configured"
fi

echo "✅ Secret setup for ${CLUSTER_TYPE} cluster completed successfully!"
echo ""
echo "🔍 Secrets summary for cluster: ${CLUSTER_NAME}"
if [[ "$IS_CONTROL_PLANE" == "true" ]]; then
    echo "   Crossplane secrets in crossplane-system namespace:"
    kubectl --context="${CLUSTER_CONTEXT}" get secrets -n crossplane-system | grep -E "(github-provider|gcp-creds)" || echo "   No Crossplane secrets found"
    echo "   ℹ️  AI platform secrets are deployed to workload clusters only"
else
    echo "   AI platform secrets in kagent-system namespace:"
    kubectl --context="${CLUSTER_CONTEXT}" get secrets -n kagent-system | grep -E "(kagent-)" || echo "   No AI platform secrets found"
    echo "   Other workload cluster secrets:"
    echo "   No additional cluster-specific secrets configured"
fi
