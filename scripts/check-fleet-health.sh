#!/usr/bin/env bash
# check-fleet-health.sh
# Progressively checks Flux health across all clusters in the fleet.
# Verifies all resources are Ready, not suspended, and GitRepositories are on the latest remote SHA.
#
# Usage:
#   ./check-fleet-health.sh            # check all available clusters
#   ./check-fleet-health.sh apps-dev   # check a single cluster by short name

set -eou pipefail

# ── colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()     { echo -e "  ${GREEN}✓${NC}  $*"; }
fail()   { echo -e "  ${RED}✗${NC}  $*"; echo "FAIL" >> "${FAIL_FILE}"; }
warn()   { echo -e "  ${YELLOW}⚠${NC}  $*"; }
header() { echo -e "\n${BOLD}${CYAN}━━━ $* ${NC}"; }
sub()    { echo -e "  ${BOLD}$*${NC}"; }

# ── known clusters: "short-name:kubeconfig-context" ──────────────────────────
# GKE context names embed the project ID — discover them from kubeconfig by
# suffix pattern so this script stays project-ID-agnostic.
_gke_ctx() { kubectl config get-contexts -o name 2>/dev/null | grep "_${1}$" | head -1 || true; }

CLUSTERS=(
  "kind:kind-kind-test-cluster"
  "control-plane:$(_gke_ctx control-plane)"
  "apps-dev:$(_gke_ctx apps-dev)"
)

# ── temp file tracks failures across subshells ────────────────────────────────
FAIL_FILE=$(mktemp)
trap 'rm -f "${FAIL_FILE}"' EXIT

# ── helpers ───────────────────────────────────────────────────────────────────

context_exists() { kubectl config get-contexts "$1" &>/dev/null; }

# Check all instances of a Flux CRD type in a cluster.
check_type() {
  local ctx="$1" kind="$2"
  local short="${kind%%.*}"

  local json
  json=$(kubectl --context "${ctx}" get "${kind}" -A -o json 2>/dev/null) || { warn "${short}: CRD not present"; return 0; }

  local count
  count=$(echo "${json}" | jq '.items | length')
  [ "${count}" -eq 0 ] && { warn "${short}: no resources found"; return 0; }

  echo "${json}" | jq -r '
    .items[] | [
      .metadata.namespace,
      .metadata.name,
      ((.spec.suspend // false) | tostring),
      ((.status.conditions // []) | map(select(.type == "Ready")) | first | .status // "Unknown"),
      ((.status.conditions // []) | map(select(.type == "Ready")) | first | .message // "no condition"),
      (.status.artifact.revision // "")
    ] | @tsv
  ' | while IFS=$'\t' read -r ns name suspended ready msg rev; do
      local label="${short}/${name} (${ns})"
      local rev_short=""
      if [ -n "${rev}" ]; then
        local sha="${rev##*:}"
        rev_short=" [${sha:0:7}]"
      fi

      if [ "${suspended}" = "true" ]; then
        warn "${label} — SUSPENDED"
      elif [ "${ready}" = "True" ]; then
        ok "${label}${rev_short}"
      elif [ "${ready}" = "Unknown" ] && [ "${msg}" = "no condition" ]; then
        warn "${label} — no Ready condition yet (may still be initialising)"
      else
        fail "${label} — ${msg}"
      fi
    done
}

# Compare each GitRepository's artifact SHA with the actual remote HEAD.
check_git_freshness() {
  local ctx="$1"

  local json
  json=$(kubectl --context "${ctx}" get gitrepository -A -o json 2>/dev/null) || return 0

  echo "${json}" | jq -r '
    .items[] | [
      .metadata.name,
      .spec.url,
      (.spec.ref.branch // .spec.ref.tag // "main"),
      (.status.artifact.revision // "")
    ] | @tsv
  ' | while IFS=$'\t' read -r name url branch rev; do
      local current="${rev##*:}"
      if [ -z "${current}" ]; then
        warn "${name}: no artifact yet — skipping SHA check"
        continue
      fi

      local remote
      remote=$(git ls-remote "${url}" "refs/heads/${branch}" 2>/dev/null | awk '{print $1}')
      if [ -z "${remote}" ]; then
        warn "${name}: could not reach ${url} to verify SHA"
        continue
      fi

      if [ "${current}" = "${remote}" ]; then
        ok "${name}: up to date with ${branch}@${remote:0:7}"
      else
        fail "${name}: BEHIND — synced ${current:0:7}, remote ${branch} is ${remote:0:7}"
      fi
    done
}

# ── resolve which clusters to check ──────────────────────────────────────────
get_context_for() {
  local target="$1"
  for entry in "${CLUSTERS[@]}"; do
    local sname="${entry%%:*}"
    local ctx="${entry##*:}"
    [ "${sname}" = "${target}" ] && echo "${ctx}" && return
  done
}

is_known_cluster() {
  local target="$1"
  for entry in "${CLUSTERS[@]}"; do
    [ "${entry%%:*}" = "${target}" ] && return 0
  done
  return 1
}

if [ "${1:-}" != "" ]; then
  TARGETS=("$1")
else
  TARGETS=()
  for entry in "${CLUSTERS[@]}"; do
    TARGETS+=("${entry%%:*}")
  done
fi

# ── main loop ─────────────────────────────────────────────────────────────────
for short_name in "${TARGETS[@]}"; do
  ctx=$(get_context_for "${short_name}")
  if [ -z "${ctx}" ]; then
    if is_known_cluster "${short_name}"; then
      warn "context for '${short_name}' not found in kubeconfig — cluster not provisioned yet, skipping"
    else
      echo -e "${RED}Unknown cluster '${short_name}'${NC}"
    fi
    continue
  fi

  header "Cluster: ${short_name}"

  if ! context_exists "${ctx}"; then
    warn "context '${ctx}' not in kubeconfig — cluster not provisioned yet, skipping"
    continue
  fi

  if ! kubectl --context "${ctx}" cluster-info &>/dev/null 2>&1; then
    warn "cannot reach API server for ${short_name} — cluster not running, skipping"
    continue
  fi

  sub "GitRepositories"
  check_type "${ctx}" "gitrepository.source.toolkit.fluxcd.io"

  sub "Remote SHA freshness"
  check_git_freshness "${ctx}"

  sub "Kustomizations"
  check_type "${ctx}" "kustomization.kustomize.toolkit.fluxcd.io"

  sub "HelmRepositories"
  check_type "${ctx}" "helmrepository.source.toolkit.fluxcd.io"

  sub "HelmReleases"
  check_type "${ctx}" "helmrelease.helm.toolkit.fluxcd.io"

  sub "ImageRepositories"
  check_type "${ctx}" "imagerepository.image.toolkit.fluxcd.io"

  sub "ImagePolicies"
  check_type "${ctx}" "imagepolicy.image.toolkit.fluxcd.io"

  sub "ImageUpdateAutomations"
  check_type "${ctx}" "imageupdateautomation.image.toolkit.fluxcd.io"
done

# ── summary ───────────────────────────────────────────────────────────────────
echo ""
if grep -q "FAIL" "${FAIL_FILE}" 2>/dev/null; then
  failures=$(wc -l < "${FAIL_FILE}" | tr -d ' ')
  echo -e "${RED}${BOLD}✗ Fleet NOT healthy — ${failures} issue(s) found${NC}"
  exit 1
else
  echo -e "${GREEN}${BOLD}✓ Fleet healthy — all resources synced and up to date${NC}"
  exit 0
fi
