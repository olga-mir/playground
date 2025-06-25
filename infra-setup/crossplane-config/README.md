# GKE Cluster Compositions

This directory contains Crossplane compositions for creating GKE clusters with different configurations based on cluster type.

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

- `gke-cluster-xrd.yaml` - CompositeResourceDefinition defining the API
- `gke-cluster-composition.yaml` - Composition using pipeline mode with conditional logic
- `examples/mgmt-cluster-claim.yaml` - Example management cluster claim
- `examples/apps-cluster-claim.yaml` - Example apps cluster claim

## Usage

### Prerequisites
1. Install Crossplane in your management cluster (Kind)
2. Install the required providers:
   ```yaml
   apiVersion: pkg.crossplane.io/v1
   kind: Provider
   metadata:
     name: provider-gcp-beta-container
   spec:
     package: xpkg.upbound.io/upbound/provider-gcp-beta-container:v0.5.1
   ---
   apiVersion: pkg.crossplane.io/v1
   kind: Provider
   metadata:
     name: provider-helm
   spec:
     package: xpkg.upbound.io/crossplane-contrib/provider-helm:v0.19.0
   ---
   apiVersion: pkg.crossplane.io/v1
   kind: Provider
   metadata:
     name: provider-kubernetes
   spec:
     package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v0.14.0
   ```

3. Install the function-go-templating function:
   ```yaml
   apiVersion: pkg.crossplane.io/v1beta1
   kind: Function
   metadata:
     name: function-go-templating
   spec:
     package: xpkg.upbound.io/crossplane-contrib/function-go-templating:v0.6.0
   ```

### Deploy the Composition

1. Apply the XRD and Composition:
   ```bash
   kubectl apply -f gke-cluster-xrd.yaml
   kubectl apply -f gke-cluster-composition.yaml
   ```

2. Create cluster claims:
   ```bash
   # Create management cluster
   envsubst < examples/mgmt-cluster-claim.yaml | kubectl apply -f -
   
   # Create apps cluster
   envsubst < examples/apps-cluster-claim.yaml | kubectl apply -f -
   ```

### Environment Variables

The examples use the following environment variables:
- `PROJECT_ID` - GCP Project ID
- `REGION` - GCP Region
- `ZONE` - GCP Zone
- `GKE_VPC` - VPC network name
- `MGMT_SUBNET_NAME` - Management cluster subnet
- `APPS_DEV_SUBNET_NAME` - Apps cluster subnet
- `GITHUB_DEMO_REPO_OWNER` - GitHub repository owner
- `GITHUB_DEMO_REPO_NAME` - GitHub repository name
- `GITHUB_DEMO_REPO_PAT` - GitHub personal access token

## Benefits Over Bash Scripts

1. **Declarative**: Resources are defined as desired state, not imperative steps
2. **Dependency Management**: Crossplane handles resource dependencies automatically
3. **Drift Detection**: Continuous reconciliation ensures actual state matches desired
4. **Reusable**: Same composition works across environments with different parameters
5. **GitOps Ready**: Compositions and claims can be stored in Git and managed by ArgoCD
6. **Type Safety**: XRD provides schema validation for cluster specifications
7. **Status Reporting**: Rich status information for debugging and monitoring

## Migration from Bash Scripts

This composition replaces:
- `03-deploy-gke-clusters.sh` - GKE cluster creation
- Parts of `04-setup-gke-clusters.sh` - ArgoCD and Crossplane installation

The composition handles the complexity of conditional resource creation based on cluster type, eliminating the need for complex bash logic and manual helm installations.