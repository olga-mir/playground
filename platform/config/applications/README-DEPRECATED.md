# DEPRECATED: ArgoCD Applications

This directory contained ArgoCD application definitions that have been migrated to Flux.

## Migration Status:

### ✅ Migrated to Flux

**AI Platform Services** → `clusters/apps-dev/platform-products-source.yaml`
- `kagent-config.yaml` → `platform-products/ai/kagent/config/`
- `mcp-gateway-config.yaml` → `platform-products/networking/kgateway-mcp/`  
- `mcp-tools.yaml` → `platform-products/ai/mcp-tools/`

**AI Platform Helm Charts** → `clusters/apps-dev/platform-products-source.yaml`
- `../helm-applications/kagent.yaml` → `platform-products/ai/kagent/helm/`
- `../helm-applications/kagent-crds.yaml` → `platform-products/ai/kagent/helm/`
- `../helm-applications/kgateway-mcp-app.yaml` → `platform-products/networking/kgateway/helm/`
- `../helm-applications/kgateway-crds.yaml` → `platform-products/networking/kgateway/helm/`

**Crossplane Platform Services** → `clusters/control-plane/crossplane-platform-source.yaml`
- `crossplane-infra-providers.yaml` → `platform/crossplane/providers/`
- `crossplane-infra-functions.yaml` → `platform/crossplane/functions/`
- `crossplane-platform-compositions.yaml` → `platform/crossplane/compositions/`
- `crossplane-platform-xrd.yaml` → `platform/crossplane/definitions/`
- `crossplane-infra-provider-configs-cmp.yaml` → `platform/crossplane/provider-configs/`
- `crossplane-infra-environment-configs-cmp.yaml` → `platform/crossplane/environment-configs/`

## Architecture:

- **Control-plane cluster**: Runs Crossplane + platform services
- **Apps-dev cluster**: Runs AI platform services + tenant applications

## Next Steps:

1. Test Flux deployment on both clusters
2. Remove this directory once migration is verified
3. Update any remaining references to ArgoCD applications