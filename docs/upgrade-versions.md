# Version Upgrade Process

## Overview

Versions are upgraded automatically every Wednesday via the `upgrade-versions` workflow
(`.github/workflows/upgrade-versions.yml`). It uses a hybrid approach:

1. **Bash** discovers all versioned components and fetches latest releases (cheap, deterministic)
2. **Claude** (via the `upgrade-versions` skill) reads the pre-computed report and applies edits + opens the PR

## How it works

```
scan-versions.sh → fetch-latest-versions.sh → .version-report.md → Claude (/upgrade-versions skill) applies edits
```

The Claude step uses `defaultMode: "acceptEdits"` (set in the workflow `settings`) so file edits
are auto-approved without interactive prompts. The skill is at `.claude/skills/upgrade-versions/SKILL.md`.

Required secrets for the GitHub workflow: `ANTHROPIC_API_KEY` (for the action), `GCS_LOG_BUCKET`, `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`.

Note: Do not confuse the workflow's `ANTHROPIC_API_KEY` with the in-cluster `KAGENT_ANTHROPIC_API_KEY` used by kagent workloads.

### scan-versions.sh

Discovers versioned components by inspecting the repo structure — no hardcoded file list.

| Component type | How GitHub repo is derived |
|---|---|
| HelmRelease with `ghcr.io` OCI repo | Parsed from `oci://ghcr.io/ORG/REPO/...` URL |
| HelmRelease with HTTP Helm repo | Fetches `{URL}/index.yaml` directly — no GitHub repo needed |
| HelmRelease with custom OCI registry | Reads `upgrade.playground/github-repo` annotation from the HelmRepository YAML |
| Crossplane Provider / Function | `crossplane-contrib/PKGNAME` parsed from xpkg URL |
| README-only component (e.g. FluxCD) | `github.com/ORG/REPO` parsed from the link URL already in the README table |

### fetch-latest-versions.sh

- For **Helm index** sources: fetches `{repo_url}/index.yaml`, extracts the latest version
  for the specific chart with `sort -V` (handles semver including pre-releases)
- For **GitHub** sources: calls `gh api repos/{org}/{repo}/releases/latest`, falls back to tags

Output: `.version-report.md` (markdown table) + `.version-report.json`

## Adding a new component

### New HelmRelease

No action needed unless the chart uses a custom OCI registry (not `ghcr.io`).
The scan script discovers HelmRelease files automatically.

If the HelmRepository URL is a custom OCI registry (not `ghcr.io` or HTTP), add one annotation:

```yaml
# In the HelmRepository YAML for the new component:
metadata:
  annotations:
    upgrade.playground/github-repo: ORG/REPO   # e.g. kgateway-dev/kgateway
```

### New Crossplane Provider or Function

No action needed. The GitHub repo is derived from the xpkg package URL:
- `xpkg.crossplane.io/crossplane-contrib/provider-foo` → `crossplane-contrib/provider-foo`

If the package is from a non-standard org (e.g. upbound) and the GitHub repo name differs
from the package name, the scan will still attempt the derived repo. Verify by checking if
the latest version resolves correctly in the workflow run log.

### New README-only component

Add the component to the README tech-stack table with a proper GitHub release link:
```markdown
| <img ...> | MyTool | Description | [v1.2.3](https://github.com/org/repo/releases/tag/v1.2.3) |
```

The scan picks up all `github.com/ORG/REPO` links from this table automatically, skipping
any repos already tracked via YAML files.

## Known quirks

### LitmusChaos — Helm index vs GitHub tags

LitmusChaos publishes to a HTTP Helm repo (`https://litmuschaos.github.io/litmus-helm/`).
The scan uses the Helm index directly, looking up the `litmus-core` chart version specifically.
This avoids confusion with GitHub tags like `litmus-agent-3.26.0` (a different chart family).

### `provider-gcp-gke` — upbound package

This package (`xpkg.upbound.io/upbound/provider-gcp-gke`) is tracked as
`upbound/provider-gcp-gke` on GitHub. If the GitHub releases API returns 404
(repo not found or no releases), the fetch script marks it as `unknown` and skips it.
Check the workflow run log for a WARN message; update the package manually if needed.

### Edit tool in GitHub Actions

File edits work via `defaultMode: "acceptEdits"` in the workflow's `settings` block.
This auto-approves all Edit calls without interactive prompts, which is correct for
an automated workflow. The deprecated `allowed_tools` parameter is not used; tools are
configured via `claude_args: '--allowedTools ...'` per the current claude-code-action v1 API.

### Crossplane chart version is an RC

The crossplane Helm chart is currently `2.0.0-rc.1`. When a stable version is released,
the Helm index will return it as the latest. The `sort -V` ordering treats `2.0.0-rc.1`
as less than `2.0.0`, so the upgrade will be correctly detected.
