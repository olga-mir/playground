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

## File Structure (Simplified)
```
├── .github/workflows/     # GitHub Actions for Flux bootstrap
├── bootstrap/             # Bootstrap scripts and kind cluster configuration
│   ├── scripts/           # Bootstrap scripts (setup, cleanup)
│   └── kind/              # Kind cluster configs
│       ├── crossplane/    # Simplified flat structure (no base/ nesting)
│       │   ├── install/   # Crossplane installation
│       │   ├── providers/ # Providers (GCP, Helm)
│       │   ├── functions/ # Composition functions
│       │   ├── compositions/ # GKE cluster XRD + composition (unified)
│       │   ├── providerconfigs/ # Provider configurations
│       │   └── clusters/  # Control-plane cluster + namespace
│       └── flux/          # Flux configuration + alerts
├── clusters/              # Target cluster configurations
│   └── control-plane/     # Control plane cluster: Crossplane + platform services
├── control-plane-crossplane/  # Crossplane configs for control-plane cluster
│   ├── providers/         # Providers for workload cluster provisioning
│   ├── compositions/      # (Empty - uses unified composition from bootstrap)
│   └── workload-clusters/ # Per-cluster folders with dedicated namespaces
│       └── apps-dev/      # Apps-dev cluster in its own namespace + folder
├── platform-products/    # Platform services (AI stack, networking)
├── platform-tenants/     # Tenant application deployments
├── tasks/                 # Taskfile supporting tasks
└── local/                 # Local development experiments
```

## Key Improvements Made
### Unified GKE Cluster Composition
- **Before**: Separate `control-plane-composition` and `workload-composition` (nearly identical)
- **After**: Single `gke-cluster-composition` with `clusterType` parameter (`control-plane` or `workload`)
- **XRD**: Combined features from both XRDs (connectionSecrets, writeConnectionSecretsToNamespace, crossplane config)

### Simplified Bootstrap Structure
- **Before**: Convoluted `base/` + peer folders, single-file directories
- **After**: Clean flat structure in `bootstrap/kind/crossplane/` with logical grouping
- **Removed**: Unnecessary nesting, duplicate kustomizations, unused directories

### Namespace-Per-Workload-Cluster
- **Before**: Shared `workload-clusters` namespace for all workload clusters
- **After**: Each workload cluster gets dedicated namespace (e.g., `apps-dev-cluster`)
- **Structure**: `control-plane-crossplane/workload-clusters/apps-dev/` folder per cluster

### FluxCD Integration for Alerts
- **Per-cluster FluxCD Kustomizations**: Each cluster has dedicated Flux Kustomization with healthChecks
- **Control-plane**: `control-plane-cluster` Kustomization (KIND cluster)
- **Apps-dev**: `apps-dev-cluster` Kustomization (control-plane cluster)
- **Alerts**: GitHub webhook notifications tied to specific Flux objects for granular monitoring

### Key Features

#### AI Platform Stack
* **kagent**: Custom agent for Crossplane composition management
* **kgateway**: AI-specific networking gateway
* MCP server integration for agent workflows
* Platform services deployed via Flux to mgmt cluster

#### GitOps with Flux
* Multi-cluster Flux setup with hub-and-spoke pattern
* Automated cluster bootstrap via GitHub Actions and Workload Identity Federation
* Cluster-specific configurations in dedicated namespaces (gkecluster-*)
* Platform-products vs platform-tenants separation

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
   note that regex can be used, but in its own format using `*` not `.*`.
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

Note that PostBuild is not available on any Flux resource. Always check CRD in the clsuter to make sure your suggestions align with reality.

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

### Flux Notification Configuration Best Practices

**Avoid Over-Filtering in Alerts**:
- Complex inclusion/exclusion regex filters in Alert specs can be unreliable and hard to debug
- **Better approach**: Remove filters from alerts and implement logic in GitHub Actions workflows
- This makes the system more transparent and easier to troubleshoot

**Use Modern API Fields**:
- **Deprecated**: `spec.summary` field in Alert resources
- **Current**: `spec.eventMetadata.summary` field
- Mixing both causes conflicts and can prevent alerts from firing properly

**Alert Configuration Issues**:
1. **Configuration Conflicts**: Having both deprecated `summary` and new `eventMetadata` fields
2. **Filter Complexity**: Inclusion filters like `.*GKECluster.*created.*` may not match as expected
3. **Event Processing**: Alerts process events differently than expected - test with actual payloads

**Debugging Event Payloads**:
- Capture webhook payloads from GitHub Actions logs to understand actual event structure
- Event messages may not match expected patterns due to formatting differences
- Use simple test alerts without filters to verify basic webhook functionality

**Workflow Design**:
- GitHub workflows only read from the default branch (usually `main`)
- Both workflows listening to same `repository_dispatch` type will both trigger
- Implement cluster readiness checks in workflows rather than relying on alert filters
- Add conditional execution to skip irrelevant events (non-cluster events)

**Provider vs Alert Separation**:
- Multiple alerts can share the same provider (webhook endpoint)
- Each alert processes events independently based on its configuration
- Provider issues affect all alerts using that provider
