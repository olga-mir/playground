#!/usr/bin/env bash
# snapshot-kagent-pre-teardown.sh
#
# Capture kagent runtime state before tearing down the cluster.
# Saves full Agent CR specs (system messages, tool wiring), ToolServer endpoints,
# effective HelmRelease values, and RBAC — everything needed to author standalone
# Agent CRs in the next session without re-reading the Helm chart.
#
# Usage:
#   scripts/snapshot-kagent-pre-teardown.sh
#
# Output: release-artifacts/kagent-snapshot-<timestamp>/
#
# What is captured (and why):
#   agents-*.yaml       — full Agent CR specs incl. system messages and tool lists
#                         (these come from bundled Helm sub-charts, not our manifests)
#   toolservers.yaml    — ToolServer / RemoteMCPServer CRs and their in-cluster URLs
#   modelconfigs.yaml   — ModelConfig CRs across all kagent namespaces
#   helmrelease-values.yaml — effective values applied to the kagent HelmRelease
#   rbac.yaml           — ClusterRole/Binding entries for kagent ServiceAccounts
#   prometheus-endpoint.txt — Prometheus service URL reachable from agent pods
#   secret-names.txt    — Secret names referenced by kagent (names only, no values)

set -eou pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TS="$(date +%Y%m%dT%H%M%S)"
OUT_DIR="${REPO_ROOT}/release-artifacts/kagent-snapshot-${TS}"
mkdir -p "${OUT_DIR}"

# Resolve apps-dev context
APPS_CTX="$(kubectl config get-contexts -o name 2>/dev/null | grep "_apps-dev$" | head -1 || true)"
if [[ -z "${APPS_CTX}" ]]; then
  echo "ERROR: apps-dev kubeconfig context not found — is the cluster up?" >&2
  exit 1
fi

echo "Snapshotting kagent from context: ${APPS_CTX}"
echo "Output: ${OUT_DIR}"
echo

kube() { kubectl --context "${APPS_CTX}" "$@"; }

# ──────────────────────────────────────────────────────────────────────────────
# 1. Agent CRs — full spec including systemMessage and tools
# ──────────────────────────────────────────────────────────────────────────────
echo "==> Agent CRs"
for ns in kagent-system team-charlie team-alpha team-bravo; do
  FILE="${OUT_DIR}/agents-${ns}.yaml"
  AGENT_LIST=$(kube get agents -n "${ns}" --no-headers 2>/dev/null || true)
  if [[ -n "${AGENT_LIST}" ]]; then
    kube get agents -n "${ns}" -o yaml > "${FILE}"
    COUNT=$(echo "${AGENT_LIST}" | wc -l | tr -d ' ')
    echo "  ${ns}: ${COUNT} agents -> $(basename "${FILE}")"
  else
    echo "  ${ns}: no agents"
  fi
done

# ──────────────────────────────────────────────────────────────────────────────
# 2. ToolServer / RemoteMCPServer CRs
# ──────────────────────────────────────────────────────────────────────────────
echo "==> ToolServers and RemoteMCPServers"
{
  echo "# ToolServers"
  kube get toolservers -A -o yaml 2>/dev/null || echo "# none found"
  echo "---"
  echo "# RemoteMCPServers"
  kube get remotemcpservers -A -o yaml 2>/dev/null || echo "# none found"
} > "${OUT_DIR}/toolservers.yaml"

# ──────────────────────────────────────────────────────────────────────────────
# 3. ModelConfig CRs
# ──────────────────────────────────────────────────────────────────────────────
echo "==> ModelConfigs"
kube get modelconfigs -A -o yaml 2>/dev/null > "${OUT_DIR}/modelconfigs.yaml" || echo "# none found" > "${OUT_DIR}/modelconfigs.yaml"

# ──────────────────────────────────────────────────────────────────────────────
# 4. Effective HelmRelease values
# ──────────────────────────────────────────────────────────────────────────────
echo "==> HelmRelease applied values"
{
  echo "# Effective values from kagent HelmRelease"
  echo "# Retrieved from: kubectl get helmrelease kagent -n kagent-system -o jsonpath='{.spec.values}'"
  kube get helmrelease kagent -n kagent-system \
    -o jsonpath='{.spec.values}' 2>/dev/null \
    | python3 -c "import json,sys,yaml; print(yaml.dump(json.load(sys.stdin), default_flow_style=False))" \
    2>/dev/null || kube get helmrelease kagent -n kagent-system -o yaml
} > "${OUT_DIR}/helmrelease-values.yaml"

# ──────────────────────────────────────────────────────────────────────────────
# 5. RBAC — ClusterRoles and ClusterRoleBindings for kagent SAs
# ──────────────────────────────────────────────────────────────────────────────
echo "==> RBAC"
{
  echo "# ClusterRoles with 'kagent' in name"
  CR_NAMES=$(kube get clusterrole -o name 2>/dev/null | grep kagent || true)
  if [[ -n "${CR_NAMES}" ]]; then
    kube get ${CR_NAMES} -o yaml 2>/dev/null || true
  fi
  echo "---"
  echo "# ClusterRoleBindings with 'kagent' in name"
  CRB_NAMES=$(kube get clusterrolebinding -o name 2>/dev/null | grep kagent || true)
  if [[ -n "${CRB_NAMES}" ]]; then
    kube get ${CRB_NAMES} -o yaml 2>/dev/null || true
  fi
  echo "---"
  echo "# Roles in team-charlie with 'kagent' in name"
  kube get role -n team-charlie -o yaml 2>/dev/null || true
} > "${OUT_DIR}/rbac.yaml"

# ──────────────────────────────────────────────────────────────────────────────
# 6. Prometheus service endpoint
# ──────────────────────────────────────────────────────────────────────────────
echo "==> Prometheus endpoint"
{
  echo "# Prometheus services in monitoring namespace"
  kube get svc -n monitoring -o wide 2>/dev/null | grep -i prom || echo "no prometheus services found in monitoring namespace"
  echo
  echo "# Derived in-cluster URL (for agent tool config):"
  PROM_SVC=$(kube get svc -n monitoring --no-headers 2>/dev/null | grep -i "prometheus\b" | grep -v "alertmanager\|operator\|node" | awk '{print $1}' | head -1 || true)
  if [[ -n "${PROM_SVC}" ]]; then
    PROM_PORT=$(kube get svc -n monitoring "${PROM_SVC}" -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || echo "9090")
    echo "http://${PROM_SVC}.monitoring.svc.cluster.local:${PROM_PORT}"
  else
    echo "http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090  # (default — verify)"
  fi
} > "${OUT_DIR}/prometheus-endpoint.txt"

# ──────────────────────────────────────────────────────────────────────────────
# 7. Secret names referenced by kagent (names only)
# ──────────────────────────────────────────────────────────────────────────────
echo "==> Secret names"
{
  echo "# Secrets in kagent-system (names only — no values)"
  kube get secrets -n kagent-system --no-headers 2>/dev/null | awk '{print $1, $2}' || true
  echo
  echo "# Secrets in team-charlie (names only)"
  kube get secrets -n team-charlie --no-headers 2>/dev/null | awk '{print $1, $2}' || true
} > "${OUT_DIR}/secret-names.txt"

# ──────────────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────────────
echo
echo "Snapshot complete: ${OUT_DIR}"
echo
echo "Files saved:"
ls -lh "${OUT_DIR}"
echo
echo "Key reads for next session:"
echo "  - agents-kagent-system.yaml  : bundled agent system messages and tool configs"
echo "  - toolservers.yaml           : in-cluster tool server URLs"
echo "  - helmrelease-values.yaml    : currently applied HelmRelease values (diff from repo)"
echo "  - prometheus-endpoint.txt    : Prometheus URL for promql/observability agents"
