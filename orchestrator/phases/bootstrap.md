# Phase: Bootstrap
**Description:** Kind cluster with Crossplane + Flux installed and reconciling.

## Healthy Criteria
* **Crossplane Pods:** All pods in `crossplane-system` namespace are in `Running` state, with no `CrashLoopBackOff` or persistent `Pending` status.
* **GCP Provider Families:** `upbound-provider-family-gcp` must be `INSTALLED=True` and `HEALTHY=True`.
* **GCP GKE Provider:** `provider-gcp-gke` must be `INSTALLED=True` and `HEALTHY=True`.
* **Failed revisions:** No `ProviderRevision` is in a `Failed` or `Unhealthy` state.
  * *Exception:* `crossplane-contrib-provider-family-gcp` may be present with `HEALTHY=False` — this is an auto-installed dependency of `crossplane-contrib` providers (cloudrun, iam) and does NOT affect functionality; ignore it.
* **Flux Kustomizations:** All Flux `Kustomization` objects are `Ready=True` and not suspended.
* **Git Repository:** `GitRepository` objects are `Ready=True` and successfully synced to the latest remote commit.
* **Helm Releases:** No `HelmRelease` is in a `Failed` state.
