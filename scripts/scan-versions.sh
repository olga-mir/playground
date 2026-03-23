#!/usr/bin/env bash
# scan-versions.sh — Discovers versioned components in the repo, emits JSON.
#
# No config file needed. GitHub repos are derived from:
#   - HelmRepository URL (github.io, ghcr.io, or upgrade.playground/github-repo annotation)
#   - Crossplane xpkg package URL (org/name encoded in the URL)
#   - README tech-stack table GitHub links (for README-only components like FluxCD)
#
# Output: JSON array of objects:
#   type          "helm" | "crossplane" | "readme"
#   file          repo-relative path
#   component     chart or package name
#   current_version
#   source        {"type": "helm_index", "url": ..., "chart": ...}
#              OR {"type": "github", "repo": "ORG/REPO"}

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

warn()     { echo "WARN: $*" >&2; }
make_helm(){ # file component current_version helm_repo_url chart_name
  jq -cn --arg file "$1" --arg component "$2" --arg ver "$3" \
         --arg url "$4" --arg chart "$5" \
    '{type:"helm", file:$file, component:$component, current_version:$ver,
      source:{type:"helm_index", url:$url, chart:$chart}}'
}
make_gh()  { # file component current_version github_repo type
  local t="${5:-crossplane}"
  jq -cn --arg file "$1" --arg component "$2" --arg ver "$3" \
         --arg repo "$4" --arg t "$t" \
    '{type:$t, file:$file, component:$component, current_version:$ver,
      source:{type:"github", repo:$repo}}'
}

# Resolve HelmRepository URL (and optional annotation) from a sourceRef name.
helm_repo_url_for() {
  local name="$1"
  local url="" annot=""
  while IFS= read -r f; do
    url=$(yq ea "select(.kind == \"HelmRepository\" and .metadata.name == \"${name}\") | .spec.url" \
            "$f" 2>/dev/null | grep -v '^null' | head -1 || true)
    if [[ -n "$url" ]]; then
      annot=$(yq ea "select(.kind == \"HelmRepository\" and .metadata.name == \"${name}\") | .metadata.annotations.\"upgrade.playground/github-repo\"" \
               "$f" 2>/dev/null | grep -v '^null' | head -1 || true)
      printf '%s|%s\n' "$url" "$annot"
      return
    fi
  done < <(grep -rl 'kind: HelmRepository' "$REPO_ROOT/kubernetes" 2>/dev/null \
           | grep -v 'gotk-components.yaml')
}

items=()
seen_github_repos=()  # repos found in YAML scan — used to skip README duplicates

# ── 1. HelmRelease files ──────────────────────────────────────────────────────
while IFS= read -r file; do
  chart=$(yq ea 'select(.kind == "HelmRelease") | .spec.chart.spec.chart'        "$file" 2>/dev/null | grep -v '^null' | head -1 || true)
  ver=$(  yq ea 'select(.kind == "HelmRelease") | .spec.chart.spec.version'      "$file" 2>/dev/null | grep -v '^null' | head -1 || true)
  ref=$(  yq ea 'select(.kind == "HelmRelease") | .spec.chart.spec.sourceRef.name' "$file" 2>/dev/null | grep -v '^null' | head -1 || true)
  [[ -z "$chart" || -z "$ver" || -z "$ref" ]] && continue

  rel="${file#"$REPO_ROOT"/}"
  lookup=$(helm_repo_url_for "$ref")
  repo_url="${lookup%%|*}"
  annotation="${lookup##*|}"

  if [[ -z "$repo_url" ]]; then
    warn "HelmRepository '${ref}' not found (${rel})"
    continue
  fi

  case "$repo_url" in
    oci://ghcr.io/*)
      # Derive GitHub repo from: oci://ghcr.io/ORG/REPO/... → ORG/REPO
      github_repo=$(echo "$repo_url" | sed 's|oci://ghcr.io/\([^/]*/[^/]*\).*|\1|')
      items+=("$(make_gh "$rel" "$chart" "$ver" "$github_repo" "helm")")
      seen_github_repos+=("$github_repo")
      ;;
    oci://*)
      # Custom OCI registry — require annotation on the HelmRepository
      if [[ -z "$annotation" ]]; then
        warn "Cannot derive GitHub repo for OCI registry '${repo_url}' (${rel}). Add annotation 'upgrade.playground/github-repo: ORG/REPO' to the HelmRepository YAML."
        continue
      fi
      items+=("$(make_gh "$rel" "$chart" "$ver" "$annotation" "helm")")
      seen_github_repos+=("$annotation")
      ;;
    https://*)
      # HTTP Helm index — fetch index.yaml to get latest chart version (no GitHub API needed)
      items+=("$(make_helm "$rel" "$chart" "$ver" "$repo_url" "$chart")")
      ;;
    *)
      warn "Unsupported HelmRepository URL '${repo_url}' (${rel})"
      ;;
  esac
done < <(grep -rl 'kind: HelmRelease' "$REPO_ROOT/kubernetes" 2>/dev/null \
         | grep -v 'gotk-components.yaml' || true)

# ── 2. Crossplane Provider / Function files ───────────────────────────────────
while IFS= read -r file; do
  while IFS= read -r pkg_json; do
    [[ -z "$pkg_json" || "$pkg_json" == "null" ]] && continue
    pkg_name=$(echo "$pkg_json" | jq -r '.name')
    package=$( echo "$pkg_json" | jq -r '.package // empty')
    [[ -z "$package" ]] && continue

    version="${package##*:}"
    # Strip registry host, keep ORG/PKGNAME (before the colon)
    org_path=$(echo "$package" | sed 's|[^/]*/\(.*\):.*|\1|')
    github_repo="$org_path"
    pkg_basename="${org_path##*/}"

    items+=("$(make_gh "${file#"$REPO_ROOT"/}" "$pkg_basename" "$version" "$github_repo" "crossplane")")
    seen_github_repos+=("$github_repo")
  done < <(
    yq ea -o=json \
      'select(.kind == "Provider" or .kind == "Function") | {"name": .metadata.name, "package": .spec.package}' \
      "$file" 2>/dev/null | jq -c '.' 2>/dev/null || true
  )
done < <(grep -rl 'xpkg\.' "$REPO_ROOT/kubernetes" 2>/dev/null \
         | grep -v 'gotk-components.yaml' || true)

# ── 3. README tech-stack table — components NOT already tracked via YAML ──────
while IFS= read -r line; do
  # Extract GitHub org/repo from URL in version link column
  github_repo=$(echo "$line" | grep -oE 'github\.com/[^/]+/[^/]+' | head -1 \
                | sed 's|github.com/||' || true)
  [[ -z "$github_repo" ]] && continue

  # Skip repos already covered by YAML scanning
  already=false
  for seen in "${seen_github_repos[@]+"${seen_github_repos[@]}"}"; do
    [[ "$seen" == "$github_repo" ]] && { already=true; break; }
  done
  "$already" && continue

  version=$(echo "$line" | grep -oE '\[v?[0-9][^]]*\]' | head -1 | tr -d '[]' || true)
  [[ -z "$version" ]] && continue

  # Component name: 3rd pipe-delimited field, strip img tags and whitespace
  component=$(echo "$line" | awk -F'|' '{print $3}' | sed 's/<[^>]*>//g' | xargs)
  [[ -z "$component" ]] && continue

  items+=("$(make_gh "README.md" "$component" "$version" "$github_repo" "readme")")
done < <(grep -E '^\|.*\[v?[0-9].*github\.com' "$REPO_ROOT/README.md" 2>/dev/null || true)

# ── Output JSON array ─────────────────────────────────────────────────────────
printf '[\n'
for i in "${!items[@]}"; do
  (( i < ${#items[@]} - 1 )) && printf '  %s,\n' "${items[$i]}" || printf '  %s\n' "${items[$i]}"
done
printf ']\n'
