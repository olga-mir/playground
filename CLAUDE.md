# Project purpose
* This is project that covers wide range of technology for learning and exploration for experienced Kubernetes and Platform Engineers
* This is not production ready project, but we aim for comprehensive prod-like solutions as much as possible
* The infrastructure in this project is disposable - it is provisioned in the beginning of a learning session and then fully destroyed. All out-of-band commands must be captured in yaml manifests, bash scripts or taskfiles.
* The infrastructure is provisioned in a personal GCP account - we need to be aware of costs and security.

# important-instruction-reminders
* NEVER proactively create documentation files (.md) or README files. Only create documentation files if explicitly requested by the User.
* NEVER commit project ID or other semi-sensitve information
* be aware if files are versioned, use "git mv" over "mv" commands when working with files.
* ALWAYS place newline at the end of the file
* when updating Taskfiles, validate resulting files, by running through yq
* one command deploy task: `bootstrap/scripts/setup-kind-cluster.sh` (combines cluster creation and credential setup)
* run "validate:kustomize-build" task to validate any changes made to clusters and setup
* Use `kubectl wait --for=condition=Established providers.pkg.crossplane.io` for proper resource types in setup scripts

# architecture-context
This is a multi-cluster Kubernetes setup using Crossplane v2 for infrastructure provisioning and FluxCD for GitOps:

## Cluster Architecture
- **kind cluster (local)**: Temporary bootstrap cluster running Crossplane v2 and FluxCD. Provisions GKE control plane cluster.
- **GKE control-plane cluster (GCP)**: Control plane cluster with Crossplane, Flux, and platform services. Provisions workload clusters.
- **GKE apps-dev cluster (GCP)**: Workload cluster for tenant applications.

## Crossplane v2 Changes (No More Claims)
In Crossplane v2, the concept of "claims" is removed. Key changes:
- **Direct namespace-scoped Composite Resources**: Users create namespaced XRs directly using XRDs
- **Eliminated claim-XR indirection**: No separate claim CRD proxying XRs
- **Simplified authoring**: Fewer lines of code, more intuitive for Kubernetes developers
- **Alignment with K8s conventions**: Namespace-scoped by default for multi-tenancy

**Migration Impact**: All "claim" references removed from codebase, using direct GKECluster composite resources.

## GitOps Flow - "Batteries Included" Cluster Provisioning
1. **Crossplane Composite Resources** → provision GKE clusters (infrastructure only)
2. **Flux notifications** → detect cluster readiness → trigger GitHub webhook
3. **GitHub Actions** → bootstrap Flux on new GKE clusters → point to `/clusters/{cluster-type}/`
4. **Flux on target GKE cluster** → deploy Crossplane, platform services, and applications ("batteries")

### Key Architectural Principles
- **Compositions create infrastructure only** (GKE cluster, NodePool, connection secrets)
- **GitOps handles cluster bootstrapping** (Crossplane installation, platform services)
- **Separation of concerns** avoids circular dependencies and readiness issues
- **Namespace-scoped resources** for proper multi-tenancy (v2 default)

## File Structure
```
kubernetes
├── clusters     # flux and kustomizations pointing to "namespaces/overlays" to compose the cluster applications
│   ├── apps-dev
│   ├── control-plane
│   └── kind
├── namespaces
│   ├── base # we need to fix this now. content of two folders inside needs to go into each individual namespace
│   ├── crossplane-system # all folders from here below need to be moved inside "base"
│   ├── flux-system
│   ├── gkecluster-apps-dev
│   ├── gkecluster-control-plane
│   ├── kagent
│   ├── kagent-system
│   ├── kgateway-system
│   └── overlays # This is where the content for each cluster is assembled. It needs to contain folder for each cluster, and inside there is a kustomization that collects required resources
└── tenants
    ├── base
    └── overlays
```

### Key Features

#### AI Platform Stack

Core components and versions:

| Component | Description | Project Version | Latest Version |
|-----------|-------------|-----------------|----------------|
| **Crossplane** | Infrastructure control plane | [v2.0.0-rc.1](https://github.com/crossplane/crossplane/releases/tag/v2.0.0-rc.1) | [v2.0.1](https://github.com/crossplane/crossplane/releases/latest) |
| **FluxCD** | GitOps toolkit | [v2.7.5](https://github.com/fluxcd/flux2/releases/tag/v2.7.5) | [v2.7.5](https://github.com/fluxcd/flux2/releases/latest) |
| **kagent** | AI agent framework | [v0.7.5](https://github.com/kagent-dev/kagent/releases/tag/v0.7.5) | [v0.7.5](https://github.com/kagent-dev/kagent/releases/latest) |
| **kgateway** | AI networking gateway | [v2.1.1](https://github.com/Kong/kgateway/releases/tag/v2.1.1) | [v2.1.1](https://github.com/Kong/kgateway/releases/latest) |

* MCP server integration for agent workflows
* Platform services deployed via Flux

#### GitOps with Flux
* Multi-cluster Flux setup with hub-and-spoke pattern
* Automated cluster bootstrap via GitHub Actions and Workload Identity Federation
* Cluster-specific configurations in dedicated namespaces (gkecluster-*)

## Recent Architecture Updates (2025)

### Namespace Structure Reorganization
- **Platform services moved**: Relocated from `flux-system` to `kubernetes/namespaces/base/platform-services/`
- **Proper base/overlay separation**: All namespace-scoped components now in `namespaces/base/`
- **Cluster-specific overlays**: Each cluster type has dedicated overlay in `namespaces/overlays/`

### Script Consolidation
- **Combined setup script**: `bootstrap/scripts/setup-kind-cluster.sh` replaces separate scripts
- **Fixed timing issues**: ConfigMaps created before Flux bootstrap to prevent dependency failures
- **Proper resource types**: Updated `kubectl wait` commands to use full resource names (e.g., `providers.pkg.crossplane.io`)

### Flux Kustomization Separation
- **GKE cluster resources**: Separated into dedicated Flux Kustomizations for clean alerts
- **Control-plane clusters**: Now managed via `kubernetes/clusters/kind/clusters.yaml`
- **Workload clusters**: Managed via `kubernetes/clusters/control-plane/clusters.yaml`

### GitRepository Consistency
- **Single GitRepository per cluster**: All clusters use consistent `flux-system` GitRepository
- **No duplicate repositories**: Eliminated `crossplane-config` GitRepository, unified on `flux-system`

### GitHub Actions Improvements
- **Updated workflow triggers**: Support for new cluster kustomization event patterns
- **GitRepository creation**: Automatic creation of flux-system GitRepository if missing after bootstrap
- **Simplified event handling**: Removed unnecessary GitRepository duplication logic

### Simplified Cluster Provisioning
- **Direct base references**: Flux Kustomizations now point directly to base directories for cluster provisioning
- **Removed overlay indirection**: Eliminated unnecessary `kind-clusters` and `control-plane-clusters` overlay layers
- **Cleaner architecture**: Reduced complexity while maintaining same functionality

## Detailed Architecture and File Structure

### Top-Level Directory Structure

```
kubernetes/
├── clusters/           # Flux Kustomization entry points for each cluster
├── namespaces/         # Kubernetes namespace-scoped resources
├── components/         # Reusable Kustomize components (e.g., Crossplane compositions)
└── tenants/           # Tenant application configurations

bootstrap/
└── scripts/           # Setup and deployment scripts

tasks/                 # Taskfile.yml tasks for validation and operations
```

### kubernetes/clusters/ - Flux Entry Points

Each subdirectory contains Flux Kustomization resources that define what gets deployed to each cluster type:

```
clusters/
├── kind/              # Bootstrap cluster (local kind)
│   ├── flux-system/   # Auto-generated Flux bootstrap files
│   ├── platform.yaml  # Points to namespaces/overlays/kind (Crossplane + platform services)
│   └── clusters.yaml  # Points to namespaces/base/gkecluster-control-plane/clusters (GKE control-plane provisioning)
├── control-plane/     # GKE control-plane cluster
│   ├── flux-system/   # Auto-generated Flux bootstrap files
│   ├── platform.yaml  # Points to namespaces/overlays/control-plane (Crossplane + platform services)
│   └── clusters.yaml  # Points to namespaces/base/gkecluster-apps-dev (GKE workload cluster provisioning)
└── apps-dev/          # GKE workload cluster
    ├── flux-system/   # Auto-generated Flux bootstrap files
    └── platform.yaml  # Points to namespaces/overlays/apps-dev (applications only, no Crossplane)
```

**Key Pattern**: Each cluster's Flux Kustomizations point to either:
- `namespaces/overlays/{cluster-type}` for platform services and infrastructure
- `namespaces/base/{specific-namespace}` for targeted deployments (like cluster provisioning)

### kubernetes/namespaces/ - Namespace-Scoped Resources

Organized using Kustomize base/overlay pattern:

```
namespaces/
├── base/                          # Base namespace configurations
│   ├── crossplane-system/        # Crossplane core installation and configuration
│   │   ├── install/               # Crossplane Helm chart and CRDs
│   │   ├── providers/             # Crossplane providers (GCP, GitHub)
│   │   ├── provider-configs/      # Provider authentication configurations
│   │   ├── functions/             # Crossplane composition functions
│   │   └── environment-configs/   # Environment-specific configurations
│   ├── flux-system/               # Flux notification providers and alerts
│   ├── platform-services/        # GitHub org/repo/team configurations and compositions
│   ├── gkecluster-control-plane/  # Control-plane cluster composite resources
│   │   └── clusters/              # Specific cluster definitions
│   ├── gkecluster-apps-dev/       # Apps-dev cluster composite resources
│   ├── kagent/                    # AI agent platform components
│   ├── kagent-system/             # AI agent system configurations
│   └── kgateway-system/           # AI gateway networking components
└── overlays/                      # Cluster-specific compositions
    ├── kind/                      # Bootstrap cluster overlay
    ├── control-plane/             # Control-plane cluster overlay
    └── apps-dev/                  # Workload cluster overlay
```

**Base Pattern**: Each base directory contains:
- `kustomization.yaml` - Lists all resources to include
- Resource YAML files for that namespace
- Subdirectories for logical grouping (e.g., `install/`, `providers/`)

**Overlay Pattern**: Each overlay composes multiple base directories for a cluster type:
```yaml
# Example: namespaces/overlays/control-plane/kustomization.yaml
resources:
  - ../../base/crossplane-system
  - ../../base/flux-system
  - ../../base/platform-services
  - ../../base/kagent
  - ../../base/kagent-system
  - ../../base/kgateway-system
  - ../../../components/crossplane-compositions/overlays/control-plane
```

### kubernetes/components/ - Reusable Components

Components are Kustomize resources that can be included in multiple places:

```
components/
└── crossplane-compositions/       # Crossplane XRDs and Compositions
    ├── base/
    │   ├── gke-cluster/           # GKE cluster composition and XRD
    │   └── cloudrun/              # CloudRun composition and XRD
    └── overlays/
        ├── kind/                  # Only includes GKE cluster composition
        └── control-plane/         # Includes both GKE cluster and CloudRun compositions
```

**Composition Separation Strategy**:
- **Kind cluster**: Only needs GKE cluster composition (for control-plane provisioning)
- **Control-plane cluster**: Needs GKE cluster + CloudRun compositions (for workload cluster + services)
- **GitHub compositions**: Located in `platform-services` base (org/repo/team management)

### What Goes in flux-system/

The `flux-system` namespace in each cluster contains:

1. **Auto-generated by Flux bootstrap**:
   - `gotk-sync.yaml` - GitRepository and root Kustomization pointing to `clusters/{cluster-type}/`
   - `gotk-components.yaml` - Flux controller deployments
   - Flux secrets for GitHub authentication

2. **Manually managed** (in `namespaces/base/flux-system/`):
   - `notification-provider.yaml` - GitHub webhook provider for cluster-ready notifications
   - Alert configurations for monitoring Flux health

**Important**: Flux bootstrap creates the GitRepository and root Kustomization automatically. Our manual `flux-system` base only adds notification providers and alerts.

### Base vs Overlays Pattern

**Base Directories** (`namespaces/base/`):
- Contain the actual Kubernetes resource YAML files
- Include a `kustomization.yaml` that lists all resources in that namespace
- Are environment-agnostic (use Flux PostBuild substitution for environment-specific values)
- Can be referenced directly by Flux Kustomizations for targeted deployments

**Overlay Directories** (`namespaces/overlays/`):
- Compose multiple base directories to create a complete cluster configuration
- Use `resources:` list to include bases and components
- Can add patches, transformations, or additional resources
- Represent the complete "bill of materials" for a cluster type

**Direct Base References**:
For targeted deployments (like cluster provisioning), Flux Kustomizations can point directly to base directories:
```yaml
# clusters/kind/clusters.yaml points directly to:
path: ./kubernetes/namespaces/base/gkecluster-control-plane/clusters
```

This pattern eliminates unnecessary overlay indirection when you only need resources from a single namespace.

### Cluster Provisioning Flow

1. **Kind cluster** (`clusters/kind/`):
   - `platform.yaml` → `namespaces/overlays/kind` → Crossplane + compositions
   - `clusters.yaml` → `namespaces/base/gkecluster-control-plane/clusters` → Creates control-plane GKE cluster

2. **Control-plane cluster** (`clusters/control-plane/`):
   - `platform.yaml` → `namespaces/overlays/control-plane` → Crossplane + platform services
   - `clusters.yaml` → `namespaces/base/gkecluster-apps-dev` → Creates apps-dev GKE cluster

3. **Apps-dev cluster** (`clusters/apps-dev/`):
   - `platform.yaml` → `namespaces/overlays/apps-dev` → Applications only (no Crossplane)

This architecture provides clear separation of concerns while maintaining flexibility and avoiding circular dependencies.

## VARIABLES
* Some of the variables won't be available to you terminal where you are running.
* Env variables listed in task `deploy` in `env` section are always sourced in working terminal, but are not accessible to agents.

## Working with Crossplane Composite Resources (GitOps)

When debugging or fixing Crossplane composite resources in this GitOps setup:

1. **Suspend Flux kustomization** to prevent interference:
   ```bash
   kubectl --context kind-kind-test-cluster patch kustomization <kustomization_name> -n flux-system -p '{"spec":{"suspend":true}}' --type=merge
   ```

2. **Fix issues** by editing the composition or composite resource files locally

3. **Resume kustomization** after fixes:
   ```bash
   kubectl --context kind-kind-test-cluster patch kustomization <kustomization_name>  -n flux-system -p '{"spec":{"suspend":false}}' --type=merge
   ```

4. **Commit and push** let the user review, commit and push

5. **Force reconciliation** if needed:
   ```bash
   kubectl --context kind-kind-test-cluster annotate kustomization crossplane-base -n flux-system reconcile.fluxcd.io/requestedAt=$(date '+%Y-%m-%dT%H:%M:%S%z') --overwrite
   ```

**Note**: Always work through GitOps - direct kubectl changes will be overridden by Flux.

## Flux Notifications & GitHub Workflows Debugging

### Common Issues and Solutions for Flux → GitHub Actions Integration

#### Issue: GitHub workflows not triggering from Flux notifications
**Root Causes and Fixes:**

1. **Event Type Mismatch** (Most Common)
   - **Problem**: Flux `githubdispatch` provider sends `event_type` in format: `{Kind}/{Name}.{Namespace}`
   - **Example**: For `control-plane-cluster` Kustomization in `flux-system` namespace → `Kustomization/control-plane-cluster.flux-system`
   - **Solution**: GitHub workflow must match exact format:
   ```yaml
   on:
     repository_dispatch:
       types: [Kustomization/control-plane-cluster.flux-system]
   ```
   note that glob patterns can be used, which use '*' as a wildcard instead of '.*'.
   This type will match too:
   ```yaml
       types: [Kustomization/*-cluster.flux-system]
   ```

2. **Workflow Location**
   - **Problem**: GitHub only looks for workflows in the **default branch** (usually `main`)
   - **Solution**: Ensure `.github/workflows/` files are committed to main branch

3. **Secret Configuration**
   - **Problem**: `githubdispatch` provider expects `token` key in secret
   - **Solution**: Create separate secret for GitHub webhook:
   ```bash
   kubectl create secret generic github-webhook-token --namespace flux-system --from-literal=token="${GITHUB_TOKEN}"
   ```

4. **Provider vs PostBuild Secrets**
   - **Problem**: Mixing notification provider secrets with Flux PostBuild substitution secrets
   - **Solution**: Keep separate:
     - `platform-secrets`: For Flux PostBuild `substituteFrom`
     - `github-webhook-token`: For notification Provider `secretRef`

Note that 'postBuild' is available on certain Flux resources like 'Kustomization', but not all. Always check the CRD in the cluster to verify feature support.

### Debugging Flux Notifications

1. **Check notification controller logs**:
   ```bash
   kubectl logs -n flux-system -l app=notification-controller --tail=20
   ```
   - Look for `"dispatching event"` (success) vs `"failed to send notification"` (error)

2. **Force trigger for testing**:
   ```bash
   kubectl annotate kustomization crossplane-composite-resources -n flux-system reconcile.fluxcd.io/requestedAt=$(date '+%Y-%m-%dT%H:%M:%S%z') --overwrite
   ```

3. **Check Provider/Alert status**:
   ```bash
   kubectl describe provider github-webhook -n flux-system
   kubectl describe alert cluster-ready-alert -n flux-system
   ```
