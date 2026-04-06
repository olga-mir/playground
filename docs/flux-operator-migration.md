# Flux Operator Migration

Migration plan from `flux bootstrap` to the [Flux Operator](https://github.com/controlplaneio-fluxcd/flux-operator).

## Why

`flux bootstrap github` regenerates `gotk-sync.yaml` from an internal template on every run.
That template has no concept of `spec.provider: github`, so the field is stripped each time,
breaking GitHub App authentication. The workaround — patching the live GitRepository and
committing a fixup — is fragile and must be repeated on every re-bootstrap.

Root cause (from Flux maintainer Stefan Prodan, [fluxcd/flux2#5471](https://github.com/fluxcd/flux2/issues/5471#issuecomment-3182999417)):

> The reason `spec.provider` is not supported in the CLI is that the CLI needs write access,
> while the GH App can be granted read-only. Forcing users to give the GH App write access
> just for bootstrap to push the manifests is something we wanted to avoid.
> Using the Flux Operator is a workaround for this CLI limitation, as the operator, by design,
> doesn't write to the source.

The operator manages Flux purely in-cluster via a `FluxInstance` CRD. It never pushes to git,
so `provider: github` is set once and never overwritten.

---

## What changes

### 1. Bootstrap workflow (`.github/workflows/flux-bootstrap.yml`)

**Current flow:**
1. `flux bootstrap github --token-auth` (requires `contents:write` on GITHUB_TOKEN)
2. Replace `flux-system` secret with GitHub App credentials
3. Patch `provider: github` on all live GitRepositories
4. Commit a fixup to prevent kustomize-controller from reverting the patch

**Operator flow:**
1. `helm install flux-operator oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator -n flux-system --create-namespace`
2. Create the `flux-system` secret with GitHub App credentials (same as today)
3. `kubectl apply -f kubernetes/clusters/<cluster>/flux-system/flux-instance.yaml`
4. Done — no patching, no git commits

The `GITHUB_TOKEN` no longer needs `contents:write`. The entire post-bootstrap patching
block disappears.

### 2. `kubernetes/clusters/*/flux-system/` directories

**Current structure (per cluster):**
```
gotk-components.yaml   # ~900-line auto-generated Flux CRDs and controller manifests
gotk-sync.yaml         # GitRepository + Kustomization — loses provider:github on re-bootstrap
kustomization.yaml
```

**New structure:**
```
flux-instance.yaml     # FluxInstance CRD — owns both component lifecycle and sync config
kustomization.yaml
```

`gotk-components.yaml` is gone — the operator manages Flux controller lifecycle directly.
`gotk-sync.yaml` is replaced by a `FluxInstance`. Example for `control-plane`:

```yaml
apiVersion: fluxcd.controlplane.io/v1
kind: FluxInstance
metadata:
  name: flux
  namespace: flux-system
  annotations:
    fluxcd.controlplane.io/reconcileEvery: "1h"
    fluxcd.controlplane.io/reconcileTimeout: "5m"
spec:
  distribution:
    version: "2.x"          # operator resolves to latest patch
    registry: ghcr.io/fluxcd
  components:
    - source-controller
    - kustomize-controller
    - helm-controller
    - notification-controller
    - image-reflector-controller
    - image-automation-controller
  cluster:
    networkPolicy: true
  sync:
    kind: GitRepository
    url: https://github.com/olga-mir/playground.git
    ref: refs/heads/develop
    path: kubernetes/clusters/control-plane  # cluster-specific
    pullSecret: flux-system
    provider: github                          # never overwritten
```

Each cluster gets its own manifest with the appropriate `spec.sync.path`.

### 3. Local bootstrap script (`bootstrap/bootstrap-control-plane-cluster.sh`)

Same restructuring as the workflow: swap `flux bootstrap` for
`helm install flux-operator` + `kubectl apply FluxInstance`.

### 4. Version upgrades

Currently the upgrade process bumps image tags in `gotk-components.yaml`.
With the operator, `spec.distribution.version` in `FluxInstance` is the single pin —
the operator handles the rollout. The `/upgrade-versions` skill and any version-scanning
logic needs to target this field instead.

---

## What stays the same

| Component | Notes |
|---|---|
| GitHub App secret creation | `flux-system` secret still created before applying FluxInstance |
| `platform-config` ConfigMap | Still needed for postBuild substitutions |
| `github-webhook-token` | Unchanged — used by notification-controller |
| Notification provider and alert | Unchanged — triggers bootstrap workflow on GKECluster events |
| Everything under `kubernetes/namespaces/`, `kubernetes/tenants/` | All GitOps content untouched |
| Three-cluster hub-and-spoke topology | Unchanged |

---

## Network requirements

### Egress

No new egress hosts are introduced. All required destinations exist today:

| Destination | Port | Consumer | Reason |
|---|---|---|---|
| `github.com` | 443 | source-controller | Clone git repository |
| `api.github.com` | 443 | source-controller | GitHub App token exchange |
| `api.github.com` | 443 | notification-controller | `repository_dispatch` events |
| `ghcr.io` | 443 | All controllers + operator | Pull Flux and operator images |

The operator image (`ghcr.io/controlplaneio-fluxcd/flux-operator`) and the Flux component
images it manages (`ghcr.io/fluxcd/*`) both live on `ghcr.io`. If you already allow
`ghcr.io:443` egress for the existing Flux controllers, no allowlist changes are needed.

The Helm install of the operator chart (`helm install ... oci://ghcr.io/...`) runs on the
GitHub Actions runner, not inside the cluster, so cluster-level egress policies are not
affected by that step.

## Effort summary

| Area | Effort |
|---|---|
| Bootstrap workflow | Medium — remove ~30 lines of patching, replace bootstrap call |
| Local bootstrap script | Small — same changes as workflow |
| `flux-system/` dirs (×3 clusters) | Low — delete `gotk-components.yaml`, replace `gotk-sync.yaml` with `FluxInstance` |
| Version upgrade process | Small — change what "bump Flux version" targets |
| Docs | Low — update `flux-gitops.md`, remove the `provider:github` workaround section |

The memory entry and `docs/flux-gitops.md` section documenting the `provider: github`
workaround become obsolete after migration.
