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

## GitOps Flow - "Batteries Included" Cluster Provisioning
1. **Crossplane Composite Resources** → provision GKE clusters (infrastructure only)
2. **Flux notifications** → detect cluster readiness → trigger GitHub webhook
3. **GitHub Actions** → bootstrap Flux on new GKE clusters → point to `/clusters/{cluster-type}/`
4. **Flux on target GKE cluster** → deploy Crossplane, platform services, and applications ("batteries")

### Key Architectural Principles
- **Compositions create infrastructure only** (GKE cluster, NodePool, connection secrets)
- **GitOps handles cluster bootstrapping** (Crossplane installation, platform services)
- **Separation of concerns** avoids circular dependencies and readiness issues

## File Structure
```
├── .github/workflows/     # GitHub Actions for Flux bootstrap
├── bootstrap/             # Bootstrap scripts and kind cluster configuration
│   ├── scripts/           # Bootstrap scripts (setup, cleanup)
│   └── kind/              # Kind cluster configs (Crossplane for provisioning infrastructure)
│       ├── crossplane/    # Crossplane installation and compositions for kind cluster
│       └── flux/          # Flux configuration for kind cluster
├── clusters/              # Target cluster configurations (deployed via GitHub Actions)
│   ├── control-plane/     # Control plane cluster: Crossplane + platform services
│   └── apps-dev/          # Workload cluster: applications and tenants
├── control-plane-crossplane/  # Crossplane configs deployed to control-plane cluster
│   ├── providers/         # Providers for control-plane (GCP, Helm, K8s)
│   ├── compositions/      # WorkloadCluster compositions
│   └── workload-clusters/ # Workload cluster definitions (apps-dev, etc.)
├── platform-products/    # Platform services (AI stack, networking)
├── platform-tenants/     # Tenant application deployments
├── tasks/                 # Taskfile supporting tasks
└── local/                 # Local development experiments
```

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
* These variables are always sourced in a "working" terminal:

```
export GKE_VPC
export GKE_CONTROL_PLANE_CLUSTER
export GKE_APPS_DEV_CLUSTER
export REGION
export ZONE
export PROJECT_ID
export PROJECT_NUMBER
export CONTROL_PLANE_SUBNET_NAME
export APPS_DEV_SUBNET_NAME
export CROSSPLANE_GSA_KEY_FILE
export DOMAIN
export CERT_NAME
export DNS_PROJECT
export DNS_ZONE
# ArgoCD variables removed - migrated to FluxCD
export GITHUB_DEMO_REPO_OWNER
export GITHUB_DEMO_REPO_NAME
export GITHUB_DEMO_REPO_PAT
export GITHUB_DEST_ORG_NAME
export GITHUB_DEST_ORG_REPO_LVL_PAT
export GITHUB_DEST_ORG_ORG_LVL_PAT
export ANTHROPIC_API_KEY
export OPENAI_API_KEY
export CLAUDE_MCP_CONFIG_FILE
export PINECONE_API_KEY
```

## Working with Crossplane Composite Resources (GitOps)

When debugging or fixing Crossplane composite resources in this GitOps setup:

1. **Suspend Flux kustomization** to prevent interference:
   ```bash
   kubectl --context kind-kind-test-cluster patch kustomization crossplane-composite-resources -n flux-system -p '{"spec":{"suspend":true}}' --type=merge
   ```

2. **Fix issues** by editing the composition or composite resource files locally

3. **Resume kustomization** after fixes:
   ```bash
   kubectl --context kind-kind-test-cluster patch kustomization crossplane-composite-resources -n flux-system -p '{"spec":{"suspend":false}}' --type=merge
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
   - **Example**: For `crossplane-composite-resources` Kustomization in `flux-system` namespace → `Kustomization/crossplane-composite-resources.flux-system`
   - **Solution**: GitHub workflow must match exact format:
   ```yaml
   on:
     repository_dispatch:
       types: [Kustomization/crossplane-composite-resources.flux-system]
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

### Working Notification Setup Example
```yaml
# Provider
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Provider
metadata:
  name: github-webhook
  namespace: flux-system
spec:
  type: githubdispatch
  address: https://github.com/owner/repo
  secretRef:
    name: github-webhook-token

# Alert  
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: cluster-ready-alert
  namespace: flux-system
spec:
  providerRef:
    name: github-webhook
  eventSeverity: info
  eventSources:
  - kind: Kustomization
    name: crossplane-composite-resources
    namespace: flux-system
  eventMetadata:
    cluster_name: "{{ if contains .Object.metadata.name \"control-plane\" }}control-plane{{ else }}apps-dev{{ end }}"
    project_id: "${PROJECT_ID}"
    region: "${REGION}"
```
