# Current Mission

## Goal
Migrate the Crossplane GKE cluster provider from the deprecated `provider-gcp-beta-container`
to `provider-gcp-gke`. The upstream repo for `provider-gcp-beta-container` no longer exists.
Reference: https://github.com/olga-mir/playground/issues/47

## What was intentionally changed
- `provider-gcp-gke` is now installed (HEALTHY=True)
- Old `provider-gcp-beta-container` is removed from provider manifests
- The Composition in `kubernetes/components/crossplane-compositions/` still references
  `container.gcp.upbound.io/v1beta1` (the old provider's API group) — this is the known
  breakage that needs fixing

## What "fix" means
Update the Composition to use the API group and kinds provided by `provider-gcp-gke`.
The new provider registers CRDs under `gke.gcp.upbound.io` (not `container.gcp.upbound.io`).
Specifically:
- Old: `apiVersion: container.gcp.upbound.io/v1beta1`, kinds: `Cluster`, `NodePool`
- New: `apiVersion: gke.gcp.upbound.io/v1beta1`, kinds: `Cluster`, `NodePool` (verify exact names from installed CRDs)

## What NOT to do
- Do NOT revert to the old provider (`provider-gcp-beta-container` / `container.gcp.upbound.io`)
- Do NOT remove `provider-gcp-gke`
- Do NOT modify the GKECluster XR definition (XRD) — only the Composition needs updating

## Current known state
- `crossplane-contrib-provider-family-gcp`: INSTALLED=True, HEALTHY=False — this is the
  old family provider. It may need to be replaced with `upbound-provider-family-gcp`
  (which is already INSTALLED=True, HEALTHY=True)
- GKECluster XR `control-plane-cluster`: SYNCED=False with error
  "no matches for kind Cluster in version container.gcp.upbound.io/v1beta1"
