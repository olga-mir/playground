#!/usr/bin/env bash
# validate-version-formats.sh — Verifies version updates preserve each component's
# existing v-prefix format.
#
# The rule: if the current version in the file starts with 'v', the new version
# must also start with 'v'. If it doesn't, the new version must not. This is
# inferred per-component from .version-report.json without any hardcoding.
#
# Exits 0 if all checks pass; exits 1 with structured errors otherwise.
# Designed to be called by Claude mid-execution so errors can be fixed inline.
#
# Usage: bash scripts/validate-version-formats.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="${REPO_ROOT}/.version-report.json"

if [[ ! -f "$REPORT" ]]; then
  echo "ERROR: .version-report.json not found. Run scan-versions.sh | fetch-latest-versions.sh first." >&2
  exit 1
fi

errors=()

while IFS= read -r item; do
  component=$(echo "$item" | jq -r '.component')
  file=$(echo "$item"      | jq -r '.file')
  current=$(echo "$item"   | jq -r '.current_version')
  latest=$(echo "$item"    | jq -r '.latest_version')

  [[ "$latest" == "unknown" ]] && continue
  [[ "$component" == "crossplane" ]] && continue
  [[ "$component" == "provider-gcp-gke" ]] && continue

  # Derive expected version: preserve v-prefix from the current version in the file.
  # current_version reflects what is actually in the file (canonical source of truth
  # for format), while latest_version is the raw tag from GitHub (may differ in prefix).
  if [[ "$current" == v* ]]; then
    expected="v${latest#v}"
  else
    expected="${latest#v}"
  fi

  abs_file="${REPO_ROOT}/${file}"
  if [[ ! -f "$abs_file" ]]; then
    errors+=("MISSING_FILE component=${component} file=${file}")
    continue
  fi

  if grep -qF "$expected" "$abs_file"; then
    continue
  fi

  # Expected version not found — determine what went wrong
  wrong_with_v="v${latest#v}"
  wrong_no_v="${latest#v}"

  if [[ "$expected" != v* ]] && grep -qF "$wrong_with_v" "$abs_file"; then
    errors+=("FORMAT_ERROR component=${component} file=${file} expected=${expected} found=${wrong_with_v} fix=remove_v_prefix")
  elif [[ "$expected" == v* ]] && grep -qF "$wrong_no_v" "$abs_file"; then
    errors+=("FORMAT_ERROR component=${component} file=${file} expected=${expected} found=${wrong_no_v} fix=add_v_prefix")
  elif grep -qF "$current" "$abs_file"; then
    errors+=("NOT_UPDATED component=${component} file=${file} expected=${expected} still_has=${current}")
  else
    errors+=("UNKNOWN_STATE component=${component} file=${file} expected=${expected} current=${current}")
  fi

done < <(jq -c '.[] | select(.needs_update == true)' "$REPORT")

if [[ ${#errors[@]} -eq 0 ]]; then
  echo "OK: all version updates validated"
  exit 0
fi

echo "VALIDATION ERRORS (${#errors[@]} issue(s) found):"
for e in "${errors[@]}"; do
  echo "  $e"
done
echo ""
echo "For each FORMAT_ERROR: use sed to replace the wrong version string with the expected one in the named file, then re-run this script."
exit 1
