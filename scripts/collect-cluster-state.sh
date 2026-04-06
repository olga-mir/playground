#!/usr/bin/env bash
# collect-cluster-state.sh
# Collect cluster state for a provisioning phase and save a timestamped snapshot.
#
# Usage:
#   scripts/collect-cluster-state.sh bootstrap
#   scripts/collect-cluster-state.sh control
#   scripts/collect-cluster-state.sh workload
#
# Output: prints state to stdout AND writes orchestrator/runs/snapshot-<phase>-<ts>.txt
# The snapshot is for reference and release evidence; agent invocations use kubectl directly.

set -eou pipefail

PHASE="${1:-}"
if [[ -z "$PHASE" ]]; then
  echo "Usage: $0 <bootstrap|control|workload>" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS_DIR="${REPO_ROOT}/orchestrator/runs"
mkdir -p "${RUNS_DIR}"

KIND_CTX="kind-kind-test-cluster"
_gke_ctx() { kubectl config get-contexts -o name 2>/dev/null | grep "_${1}$" | head -1 || true; }
CONTROL_CTX="$(_gke_ctx control-plane)"
APPS_CTX="$(_gke_ctx apps-dev)"

run_cmd() {
  echo "$ $*"
  "$@" 2>&1 || true
  echo ""
}

collect() {
  case "$PHASE" in
    bootstrap)
      run_cmd kubectl get pods -n crossplane-system --context "${KIND_CTX}" -o wide
      run_cmd kubectl get providers.pkg.crossplane.io --context "${KIND_CTX}" -o wide
      run_cmd kubectl get providerrevisions.pkg.crossplane.io --context "${KIND_CTX}" -o wide
      run_cmd kubectl get functions.pkg.crossplane.io --context "${KIND_CTX}" -o wide
      run_cmd kubectl get kustomizations -A --context "${KIND_CTX}"
      run_cmd kubectl describe kustomizations -A --context "${KIND_CTX}"
      run_cmd kubectl get gitrepositories -A --context "${KIND_CTX}"
      run_cmd kubectl get helmreleases -A --context "${KIND_CTX}"
      run_cmd kubectl describe providers.pkg.crossplane.io --context "${KIND_CTX}"
      ;;

    control)
      run_cmd kubectl get gkecluster -A --context "${KIND_CTX}" -o wide
      run_cmd kubectl describe gkecluster -A --context "${KIND_CTX}"
      run_cmd kubectl get managed --context "${KIND_CTX}" -o wide
      run_cmd kubectl get providers.pkg.crossplane.io --context "${KIND_CTX}" -o wide
      run_cmd kubectl get compositions --context "${KIND_CTX}" -o wide
      run_cmd kubectl get crds --context "${KIND_CTX}" --no-headers \
        | grep -E 'gke\.gcp|container\.gcp' | awk '{print $1}' | sort
      run_cmd kubectl get events -A --context "${KIND_CTX}" \
        --sort-by=.lastTimestamp --field-selector type=Warning
      run_cmd kubectl get kustomizations -A --context "${KIND_CTX}"
      run_cmd kubectl logs -n crossplane-system --context "${KIND_CTX}" \
        -l pkg.crossplane.io/revision --tail=40 --prefix
      if [[ -n "${CONTROL_CTX}" ]]; then
        run_cmd kubectl cluster-info --context "${CONTROL_CTX}"
        run_cmd kubectl get kustomizations -A --context "${CONTROL_CTX}"
        run_cmd kubectl get gitrepositories -A --context "${CONTROL_CTX}"
        run_cmd kubectl get pods -n flux-system --context "${CONTROL_CTX}"
      else
        echo "# control-plane GKE context not yet in kubeconfig — cluster still provisioning"
        echo ""
      fi
      ;;

    workload)
      if [[ -z "${CONTROL_CTX}" ]]; then
        echo "# control-plane context not available — cannot assess workload phase yet"
        exit 0
      fi
      run_cmd kubectl get gkecluster -A --context "${CONTROL_CTX}" -o wide
      run_cmd kubectl describe gkecluster -A --context "${CONTROL_CTX}"
      run_cmd kubectl get managed --context "${CONTROL_CTX}" -o wide
      run_cmd kubectl get events -A --context "${CONTROL_CTX}" \
        --sort-by=.lastTimestamp --field-selector type=Warning
      run_cmd kubectl get kustomizations -A --context "${CONTROL_CTX}"
      run_cmd kubectl logs -n crossplane-system --context "${CONTROL_CTX}" \
        -l pkg.crossplane.io/revision --tail=40 --prefix
      if [[ -n "${APPS_CTX}" ]]; then
        run_cmd kubectl cluster-info --context "${APPS_CTX}"
        run_cmd kubectl get kustomizations -A --context "${APPS_CTX}"
        run_cmd kubectl get gitrepositories -A --context "${APPS_CTX}"
        run_cmd kubectl get pods -n flux-system --context "${APPS_CTX}"
      else
        echo "# apps-dev GKE context not yet in kubeconfig — cluster still provisioning"
        echo ""
      fi
      ;;

    *)
      echo "Unknown phase: ${PHASE}" >&2
      exit 1
      ;;
  esac
}

TS="$(date '+%Y-%m-%d_%H%M%S')"
SNAPSHOT="${RUNS_DIR}/snapshot-${PHASE}-${TS}.txt"

{
  echo "# Fleet State Snapshot — ${PHASE}"
  echo "# $(date)"
  echo ""
  collect
} | tee "${SNAPSHOT}"

echo "# Snapshot saved: ${SNAPSHOT}" >&2
