#!/usr/bin/env bash
# scan-versions.sh — Discovers versioned components in the repo and emits JSON.
#
# Output: JSON array of objects with fields:
#   type          helm | crossplane | readme
#   file          relative path from repo root
#   component     chart name, package name, or README component name
#   current_version
#   github_repo   org/repo on GitHub

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG="${REPO_ROOT}/bootstrap/scripts/version-sources.yaml"

warn() { echo "WARN: $*" >&2; }

# Emit a JSON object for one version entry
make_item() {
  local type=$1 file=$2 component=$3 version=$4 github_repo=$5
  jq -cn \
    --arg type "$type" --arg file "$file" --arg component "$component" \
    --arg version "$version" --arg github_repo "$github_repo" \
    '{type:$type, file:$file, component:$component, current_version:$version, github_repo:$github_repo}'
}

items=()

# ── 1. HelmRelease files ────────────────────────────────────────────────────
while IFS= read -r file; do
  # Use ea + select to handle multi-doc YAML (e.g. HelmRepository + HelmRelease in one file)
  chart=$(yq ea 'select(.kind == "HelmRelease") | .spec.chart.spec.chart' "$file" 2>/dev/null || true)
  version=$(yq ea 'select(.kind == "HelmRelease") | .spec.chart.spec.version' "$file" 2>/dev/null || true)
  [[ -z "$chart" || "$chart" == "null" || -z "$version" || "$version" == "null" ]] && continue

  github_repo=$(yq ".helm.\"${chart}\"" "$CONFIG" 2>/dev/null || true)
  if [[ -z "$github_repo" || "$github_repo" == "null" ]]; then
    warn "No GitHub repo mapping for Helm chart '${chart}' (${file#"$REPO_ROOT"/}) — add it to version-sources.yaml"
    continue
  fi

  items+=("$(make_item "helm" "${file#"$REPO_ROOT"/}" "$chart" "$version" "$github_repo")")
done < <(grep -rl 'kind: HelmRelease' "$REPO_ROOT/kubernetes" 2>/dev/null | grep -v 'gotk-components.yaml' || true)

# ── 2. Crossplane Provider / Function files ──────────────────────────────────
while IFS= read -r file; do
  # yq ea selects all matching docs in a multi-doc YAML, outputs one JSON per doc
  while IFS= read -r pkg_json; do
    [[ -z "$pkg_json" || "$pkg_json" == "null" ]] && continue

    pkg_name=$(echo "$pkg_json" | jq -r '.name')
    package=$(echo "$pkg_json" | jq -r '.package // empty')
    [[ -z "$package" ]] && continue

    # package format: xpkg.REGISTRY/ORG/PKGNAME:VERSION
    version="${package##*:}"
    # org_path: ORG/PKGNAME (strip registry host and version)
    org_path=$(echo "$package" | sed 's|[^/]*/\(.*\):.*|\1|')
    pkg_basename="${org_path##*/}"

    override=$(yq ".xpkg.\"${pkg_basename}\"" "$CONFIG" 2>/dev/null || true)
    if [[ -n "$override" && "$override" != "null" ]]; then
      github_repo="$override"
    else
      github_repo="$org_path"
    fi

    items+=("$(make_item "crossplane" "${file#"$REPO_ROOT"/}" "$pkg_basename" "$version" "$github_repo")")
  done < <(
    yq ea -o=json 'select(.kind == "Provider" or .kind == "Function") | {"name": .metadata.name, "package": .spec.package}' "$file" 2>/dev/null \
      | jq -c '.' 2>/dev/null || true
  )
done < <(grep -rl 'xpkg\.' "$REPO_ROOT/kubernetes" 2>/dev/null | grep -v 'gotk-components.yaml' || true)

# ── 3. README-only components (e.g. FluxCD) ──────────────────────────────────
while IFS= read -r component; do
  [[ -z "$component" || "$component" == "null" ]] && continue

  github_repo=$(yq ".readme_only.\"${component}\"" "$CONFIG" 2>/dev/null || true)
  [[ -z "$github_repo" || "$github_repo" == "null" ]] && continue

  # Extract version from the README tech-stack table line matching this component
  version=$(grep -E "\|\s*${component}\s*\|" "$REPO_ROOT/README.md" 2>/dev/null \
    | grep -oE '\[v?[0-9][^]]*\]' | head -1 | tr -d '[]' || true)
  [[ -z "$version" ]] && { warn "Could not find version for '${component}' in README.md"; continue; }

  items+=("$(make_item "readme" "README.md" "$component" "$version" "$github_repo")")
done < <(yq '.readme_only | keys | .[]' "$CONFIG" 2>/dev/null || true)

# ── Output JSON array ─────────────────────────────────────────────────────────
printf '[\n'
for i in "${!items[@]}"; do
  if (( i < ${#items[@]} - 1 )); then
    printf '  %s,\n' "${items[$i]}"
  else
    printf '  %s\n' "${items[$i]}"
  fi
done
printf ']\n'
