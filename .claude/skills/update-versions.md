# Update Component Versions

This skill updates component versions in the project by checking GitHub releases and updating both documentation and manifests.

## Components to Update

Based on the README.md tech stack table, update versions for all components listed in the README Tech Stack table

**IMPORTANT**: Do NOT update Crossplane - it requires special attention and is handled separately.

## Steps to Execute

### 1. Extract GitHub URLs from README

**CRITICAL**: Do NOT guess or hardcode GitHub repository URLs. Always extract them from the README.md file.

Read `README.md` from repo root and extract the GitHub repository URLs from the "Project Version" column in the tech stack table.

Each row contains links like `[v2.1.2](https://github.com/kgateway-dev/kgateway/releases/tag/v2.1.2)`.

Extract the repository URL (e.g., `https://github.com/kgateway-dev/kgateway`) and convert to the releases page URL by appending `/releases/latest`.

Example transformation:
- From README: `https://github.com/kgateway-dev/kgateway/releases/tag/v2.1.2`
- Extract repo: `https://github.com/kgateway-dev/kgateway`
- Releases URL: `https://github.com/kgateway-dev/kgateway/releases/latest`

### 2. Check Latest Versions

For each component, fetch the latest release version from their GitHub releases page using WebFetch:

```
WebFetch url: <extracted-repo-url>/releases/latest
Prompt: "What is the latest stable version number?"
```

### 3. Update README.md

Edit the tech stack table in `README.md`:

- Update the "Project Version" column for each component
- Update the version links in the "Project Version" column to point to the new version tag

Example row format after update:
```markdown
| <img src="..." width="30"> | FluxCD | Description | [v2.7.5](https://github.com/fluxcd/flux2/releases/tag/v2.7.5) |
```

### 4. Update Kubernetes Manifests

Update version fields in the following HelmRelease manifests:

#### kagent
- `kubernetes/namespaces/base/kagent/kagent/helm/kagent-release.yaml`
  - Update `spec.chart.spec.version` field
- `kubernetes/namespaces/base/kagent/kagent/helm/kagent-crds-release.yaml`
  - Update `spec.chart.spec.version` field

#### kgateway
- `kubernetes/namespaces/base/kgateway-system/helm/kgateway-release.yaml`
  - Update `spec.chart.spec.version` field
- `kubernetes/namespaces/base/kgateway-system/helm/kgateway-crds-release.yaml`
  - Update `spec.chart.spec.version` field

#### LitmusChaos
- `kubernetes/namespaces/base/litmus/helm/litmus-release.yaml`
  - Update `spec.chart.spec.version` field
  - Note: This uses the `litmus-core` chart

**Note**: FluxCD is auto-managed by Flux bootstrap - do not update any manifests for it.

### 5. Summary

After all updates, provide a summary table showing:
- Component name
- Old version → New version
- Files updated

## Important Notes

- **Never update Crossplane** - it requires special handling
- **FluxCD**: Only update README, not manifests (Flux manages itself)
- **Version format**: Keep existing format (e.g., "v2.1.1" vs "2.1.1") - match what's in the file
- **No testing required**: Task ends when files are updated
- **No installation**: This is purely a documentation and manifest update task

## Validation

After updates, you can validate Helm chart versions are correct by running:
```bash
task validate:kustomize-build
```

This ensures the manifests are still valid YAML and Kustomize can build them.
