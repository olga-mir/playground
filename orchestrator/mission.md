# Current Mission

## Goal
Migrate the Crossplane GKE cluster provider from the deprecated `provider-gcp-beta-container`
to the current provider package, using the Crossplane v2 `.m.` managed-resource API groups.
Reference: https://github.com/olga-mir/playground/issues/47

## What was intentionally changed
- `provider-gcp-gke` is now installed (HEALTHY=True)
- Old `provider-gcp-beta-container` is removed from provider manifests
- The Composition in `kubernetes/components/crossplane-compositions/` has been updated
  to use `container.gcp.m.upbound.io/v1beta1` for both `Cluster` and `NodePool`

## What "fix" means
The Composition must use the correct API group and namespace for Crossplane v2:

- **API group**: `container.gcp.m.upbound.io/v1beta1` — this is the `.m.` managed-resource
  variant installed by `provider-gcp-gke`. Do NOT use `gke.gcp.upbound.io` (that group only
  has `backupbackupplans`, not `Cluster`/`NodePool`). Do NOT use `container.gcp.upbound.io`
  (the non-`.m.` classic group; prefer the `.m.` variant for Crossplane v2 compatibility).
- **Namespace**: In Crossplane v2, managed resources under `.m.upbound.io` groups are
  namespace-scoped (not cluster-scoped). Each composed resource must have a namespace.
  The convention is `namespace: {{ .observed.composite.resource.spec.parameters.clusterName }}`
  — i.e., the same name as the GKE cluster being provisioned (`control-plane` or `apps-dev`).
  These namespaces are pre-created by kustomize manifests in each cluster's base directory.

## What NOT to do
- Do NOT use `gke.gcp.upbound.io` — this group does not have Cluster or NodePool CRDs
- Do NOT use `container.gcp.upbound.io` without `.m.` — prefer the `.m.` variant
- Do NOT use `namespace: crossplane-system` for composed resources
- Do NOT treat Cluster/NodePool as cluster-scoped — they are namespace-scoped in Crossplane v2
- Do NOT revert to the old provider (`provider-gcp-beta-container`)
- Do NOT modify the GKECluster XRD — only the Composition needs updating

## Verifying API groups
Always verify against what is actually installed in the cluster:
```bash
kubectl get crds --context kind-kind-test-cluster | grep -E "cluster|nodepool" | grep container
# Should show: clusters.container.gcp.m.upbound.io and nodepools.container.gcp.m.upbound.io
```

## Stale resourceRefs
When the Composition changes namespace or API group, the GKECluster XR retains
`spec.resourceRefs` pointing to old composed objects. These stale refs cause:
  "cannot get composed resource: an empty namespace may not be set when a resource name is provided"

Fix: `kubectl patch gkecluster <name> -n <namespace> --type=merge -p '{"spec":{"resourceRefs":null}}'`
The orchestrator handles this automatically via its `clear_stale_resource_refs` function.

## Current known state
- Composition: updated to `container.gcp.m.upbound.io/v1beta1` with namespace = clusterName
- Namespace manifests for `control-plane` and `apps-dev` added to respective kustomizations
- GKECluster XR `control-plane-cluster`: stale resourceRefs need clearing (or handled by orchestrator)
