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
* run "validate:kustomize-build-clusters" task to validate any changes made to clusters and setup
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
* **kagent**: platform for building custom agents
* **kgateway**: AI-specific networking gateway
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
