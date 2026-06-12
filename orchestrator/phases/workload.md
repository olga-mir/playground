# Phase: Workload Cluster
**Description:** GKE apps-dev cluster provisioned by Crossplane on control-plane; Flux bootstrapped.

## Healthy Criteria
* **GKECluster Resource:** The `GKECluster` XR for `apps-dev` must have `READY=True` and `SYNCED=True`.
* **Managed Resources:** All managed resources under `apps-dev` must be `READY=True` with no error (`Err`) states.
* **Connectivity:** The `apps-dev` GKE context is reachable and active. Running `kubectl cluster-info` against it returns successfully.
* **Flux Kustomizations:** All Flux `Kustomization` objects on the `apps-dev` cluster are `Ready=True` and not suspended.
* **Git Repository:** `GitRepository` objects on the `apps-dev` cluster are `Ready=True`.
