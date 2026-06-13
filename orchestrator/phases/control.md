# Phase: Control Plane
**Description:** GKE control-plane cluster provisioned by Crossplane; Flux bootstrapped on it.

## Healthy Criteria
* **GKECluster Resource:** The `GKECluster` XR (cross-resource) for `control-plane` must have `READY=True` and `SYNCED=True`.
* **Managed Resources:** All sub-managed resources (e.g. NodePool, IAM bindings, etc.) must be `READY=True` with no error (`Err`) states.
* **Connectivity:** The `control-plane` GKE context is reachable and active. Running `kubectl cluster-info` against it returns successfully.
* **Flux Kustomizations:** All Flux `Kustomization` objects on the `control-plane` cluster are `Ready=True` and not suspended.
* **Git Repository:** `GitRepository` objects on the `control-plane` cluster are `Ready=True`.
