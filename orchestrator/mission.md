# Current Mission

## Goal
Migrate from named, persistent workload clusters ("apps-dev" pet model) to numbered, disposable workload clusters ("cluster-01", "cluster-02", etc. cattle model). This reflects the core project philosophy: clusters as ephemeral KRM objects, not hand-managed environments.

Reference: Cluster cattle approach enables full lifecycle automation and demonstrates cloud-native platform engineering best practices.

## What will intentionally change
- **Cluster naming**: `apps-dev` → `cluster-01` (first workload cluster, with room for cluster-02, cluster-03, etc.)
- **Terminology**: Remove all hardcoded references to "apps-dev"; use generic "workload cluster" language where appropriate
- **Provisioning flow**: The orchestrator's workload phase will provision cluster-01 using the same KRM+Flux model as control-plane
- **Storage and state**: Manifests, kustomizations, and provisioning scripts will reference cluster-01 instead of apps-dev
- **Kubeconfig contexts**: `gke_${PROJECT_ID}_${REGION}-a_apps-dev` → `gke_${PROJECT_ID}_${REGION}-a_cluster-01`

## What "done" means
- All XRDs, Compositions, and kustomizations reference "cluster-01" (not "apps-dev")
- The orchestrator successfully provisions cluster-01 end-to-end (bootstrap → control → workload phases)
- Flux GitOps manifests are stored in a location reflecting cluster-01 (e.g., `kubernetes/clusters/cluster-01/`)
- The provisioning flow is identical for control-plane (special, single instance) and cluster-01 (generic, numbered, ephemeral)
- Documentation and mission.md are updated to reflect cattle terminology

## What NOT to do
- Do NOT hardcode "cluster-01" expectations elsewhere (keep the code generic for future cluster-02, cluster-03)
- Do NOT treat cluster-01 as special or persistent — it should be fully disposable
- Do NOT create pet-cluster patterns (e.g., data stored locally, manual configuration steps)
- Do NOT keep "apps-dev" references in manifests after migration

## Architecture impact
**Before:**
```
kind (bootstrap)
  └─ GKE control-plane (special, persistent)
     └─ GKE apps-dev (pet cluster)
```

**After:**
```
kind (bootstrap)
  └─ GKE control-plane (special, persistent)
     └─ GKE cluster-01 (cattle: numbered, disposable, reproducible)
        └─ [cluster-02, cluster-03, ... for future scaling]
```

## Phase expectations
The orchestrator's three phases will remain unchanged in structure:
- **bootstrap** — kind cluster with Crossplane + Flux ready
- **control** — GKE control-plane cluster provisioned and bootstrapped (unchanged)
- **workload** — GKE cluster-01 provisioned and bootstrapped (currently provisioning apps-dev; will change to cluster-01)

## Stale resourceRefs and cleanup
When cluster names change in Crossplane Compositions, GKECluster XRs may retain stale `spec.resourceRefs`. The orchestrator's `clear_stale_resource_refs` function will handle cleanup automatically during recovery attempts.

## Current known state
- "apps-dev" exists in all manifests, scripts, and orchestrator references
- Kubeconfig contains a context for apps-dev GKE cluster
- Provisioning flow works end-to-end with current naming
- **Next step:** orchestrator code will be updated to support cluster-01 provisioning (phase-checker, diagnostics agent, provisioning logic)
