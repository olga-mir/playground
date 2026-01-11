# Update Component Versions

This skill updates component versions in the project by checking GitHub releases and updating both documentation and manifests.

## Components to Update

Based on the README.md tech stack table, update versions for:

1. **FluxCD** - https://github.com/fluxcd/flux2/releases/latest
2. **kagent** - https://github.com/kagent-dev/kagent/releases/latest
3. **kgateway** - https://github.com/Kong/kgateway/releases/latest
4. **LitmusChaos** - https://github.com/litmuschaos/litmus-helm/releases/latest

**IMPORTANT**: Do NOT update Crossplane - it requires special attention and is handled separately.

## Steps to Execute

### 1. Check Latest Versions

For each component, fetch the latest release version from their GitHub releases page using WebFetch:

```
WebFetch url: https://github.com/<org>/<repo>/releases/latest
Prompt: "What is the latest version number?"
```

### 2. Update README.md

Edit the tech stack table in `/Users/olga/repos/playground/README.md`:

- Update the "Project Version" column for each component
- **Remove the entire "Latest Version" column** from the table (user no longer wants to maintain it)
- Update the version links in the "Project Version" column to point to the new version tag

Example row format after update:
```markdown
| <img src="..." width="30"> | FluxCD | Description | [v2.7.5](https://github.com/fluxcd/flux2/releases/tag/v2.7.5) |
```

### 3. Update Kubernetes Manifests

Update version fields in the following HelmRelease manifests:

#### kagent
- `/Users/olga/repos/playground/kubernetes/namespaces/base/kagent/kagent/helm/kagent-release.yaml`
  - Update `spec.chart.spec.version` field
- `/Users/olga/repos/playground/kubernetes/namespaces/base/kagent/kagent/helm/kagent-crds-release.yaml`
  - Update `spec.chart.spec.version` field

#### kgateway
- `/Users/olga/repos/playground/kubernetes/namespaces/base/kgateway-system/helm/kgateway-release.yaml`
  - Update `spec.chart.spec.version` field
- `/Users/olga/repos/playground/kubernetes/namespaces/base/kgateway-system/helm/kgateway-crds-release.yaml`
  - Update `spec.chart.spec.version` field

#### LitmusChaos
- `/Users/olga/repos/playground/kubernetes/namespaces/base/litmus/helm/litmus-release.yaml`
  - Update `spec.chart.spec.version` field
  - Note: This uses the `litmus-core` chart

**Note**: FluxCD is auto-managed by Flux bootstrap - do not update any manifests for it.

### 4. Summary

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
