# GKE Cluster Compositions

This directory contains Crossplane compositions for creating GKE clusters with different configurations based on cluster type.

## Directory Structure

```
crossplane-config/
├── compositions/           # XRDs and Compositions
│   ├── gke-cluster-xrd.yaml
│   └── gke-cluster-composition.yaml
├── functions/              # Crossplane Functions
│   └── functions.yaml
├── providers/              # Crossplane Providers  
│   └── providers.yaml
├── provider-configs/       # ProviderConfig templates
│   └── gcp-provider-config.yaml.tpl
├── namespaces/            # Kubernetes namespaces
│   └── gke-namespace.yaml
├── claims/                # Example cluster claims
│   ├── mgmt-cluster-claim.yaml
│   └── apps-cluster-claim.yaml
├── mgmt-cluster-tooling/  # Legacy tooling configs
└── README.md
```

## Architecture

The composition supports two cluster types:

### Management Cluster (`mgmt`)
- Full GKE cluster with node pool
- ArgoCD with ApplicationSet controller and full server
- Crossplane installation with GCP providers
- Kubernetes ProviderConfig for managing resources in the cluster

### Apps/Dev Cluster (`apps`)
- GKE cluster with node pool
- ArgoCD agent only (no server, controller, or ApplicationSet)
- No Crossplane installation
- Optimized for application workloads

## Files

- `compositions/gke-cluster-xrd.yaml` - CompositeResourceDefinition defining the API
- `compositions/gke-cluster-composition.yaml` - Composition using pipeline mode with conditional logic
- `functions/functions.yaml` - Crossplane functions (go-templating, auto-ready)
- `providers/providers.yaml` - Crossplane providers (helm, kubernetes)
- `provider-configs/gcp-provider-config.yaml.tpl` - GCP ProviderConfig template
- `namespaces/gke-namespace.yaml` - GKE namespace
- `claims/mgmt-cluster-claim.yaml` - Example management cluster claim
- `claims/apps-cluster-claim.yaml` - Example apps cluster claim

## Usage

### Prerequisites
1. Install Crossplane in your management cluster (Kind)
2. Required functions and providers are automatically installed by `05-apply-compositions.sh`

### Deploy the Composition

1. Run the composition setup script:
   ```bash
   ./infra-setup/05-apply-compositions.sh
   ```

   This script will:
   - Create required namespaces
   - Install Crossplane functions (go-templating, auto-ready)
   - Install Crossplane providers (helm, kubernetes)
   - Apply XRD and Composition
   - Create GCP credentials secret
   - Create GCP ProviderConfig
   - Create cluster claims

### Environment Variables

The script uses the following environment variables:
- `PROJECT_ID` - GCP Project ID
- `REGION` - GCP Region
- `ZONE` - GCP Zone
- `GKE_VPC` - VPC network name
- `MGMT_SUBNET_NAME` - Management cluster subnet
- `APPS_DEV_SUBNET_NAME` - Apps cluster subnet
- `GITHUB_DEMO_REPO_OWNER` - GitHub repository owner
- `GITHUB_DEMO_REPO_NAME` - GitHub repository name
- `GITHUB_DEMO_REPO_PAT` - GitHub personal access token
- `CROSSPLANE_GSA_KEY_FILE` - Path to GCP service account key file
- `KIND_CROSSPLANE_CONTEXT` - kubectl context for Kind cluster

## Composition Pipeline

The composition uses a 4-step pipeline:

1. **cluster-resources** - Creates GKE cluster, node pool, and ProviderConfigs
2. **argocd-resources** - Creates ArgoCD installations (conditional based on cluster type)
3. **crossplane-resources** - Creates Crossplane installations (mgmt clusters only)
4. **ready** - Sets composite resource readiness status using function-auto-ready

## Benefits Over Bash Scripts

1. **Declarative**: Resources are defined as desired state, not imperative steps
2. **Dependency Management**: Crossplane handles resource dependencies automatically
3. **Drift Detection**: Continuous reconciliation ensures actual state matches desired
4. **Reusable**: Same composition works across environments with different parameters
5. **GitOps Ready**: Compositions and claims can be stored in Git and managed by ArgoCD
6. **Type Safety**: XRD provides schema validation for cluster specifications
7. **Status Reporting**: Rich status information for debugging and monitoring
8. **Auto-Ready**: Proper readiness signaling using function-auto-ready

## Migration from Bash Scripts

This composition replaces:
- `03-deploy-gke-clusters.sh` - GKE cluster creation
- Parts of `04-setup-gke-clusters.sh` - ArgoCD and Crossplane installation

The composition handles the complexity of conditional resource creation based on cluster type, eliminating the need for complex bash logic and manual helm installations.

## Monitoring

Monitor composition progress with:

```bash
# Watch cluster claims
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" get gkeclusters -w

# Watch composite resources
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" get xgkeclusters -w

# Check individual resources
kubectl --context="${KIND_CROSSPLANE_CONTEXT}" get clusters,nodepools,releases -n gke
```