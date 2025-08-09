# DEPRECATED: ArgoCD Helm Applications

This directory contained ArgoCD Helm application definitions that have been migrated to Flux HelmRelease resources.

## Migration Status:

### ✅ Migrated to Flux HelmRelease

**AI Platform Helm Charts** → Deployed to `apps-dev` cluster
- `kagent-crds.yaml` → `platform-products/ai/kagent/helm/kagent-crds-release.yaml`
- `kagent.yaml` → `platform-products/ai/kagent/helm/kagent-release.yaml`

**Networking Platform Helm Charts** → Deployed to `apps-dev` cluster  
- `kgateway-crds.yaml` → `platform-products/networking/kgateway/helm/kgateway-crds-release.yaml`
- `kgateway-mcp-app.yaml` → `platform-products/networking/kgateway/helm/kgateway-release.yaml`

## Migration Details:

### ArgoCD → Flux Conversion:
- **ArgoCD Application** → **Flux HelmRelease**
- **syncWave** → **dependsOn** relationships
- **Helm values** → Preserved in `spec.values`
- **Chart repositories** → **Flux HelmRepository** resources

### Deployment Strategy:
- **CRDs first**: kgateway-crds and kagent-crds deployed before main applications
- **Dependency management**: Main releases depend on CRD releases
- **Namespace creation**: `createNamespace: true` for automatic namespace creation
- **Remediation**: 3 retries for install/upgrade failures

## Architecture:

- **Apps-dev cluster**: Deploys all AI and networking platform Helm charts
- **Flux management**: HelmRelease resources managed via `platform-products-source.yaml`

## Next Steps:

1. Test Helm deployments via Flux on apps-dev cluster
2. Remove this directory once migration is verified
3. Update any remaining references to ArgoCD Helm applications