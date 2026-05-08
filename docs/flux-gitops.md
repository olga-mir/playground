# Flux & GitOps

## Kustomize structure

Resources are organised as **base/overlay**:

- **`namespaces/base/`** — environment-agnostic resources for each namespace; referenced by Flux Kustomizations
- **`namespaces/overlays/{cluster}`** — composes the base dirs appropriate for that cluster type
- **`kubernetes/clusters/{cluster}/`** — Flux entry point; contains Flux Kustomization CRs that point at overlays or bases

Each cluster's `platform.yaml` points at its overlay; `clusters.yaml` points directly at a base (for GKE cluster provisioning — no overlay indirection needed when a single namespace is the target).

Flux PostBuild substitution (`substituteFrom`) is used for environment-specific values. Sources:
- `platform-config` ConfigMap — non-secret values (PROJECT_ID, region, cluster names)
- `platform-secrets` Secret — sensitive values (PATs, GCP credentials base64)

## Flux Operator and FluxInstance

Flux is installed and managed by the **Flux Operator** (`controlplaneio-fluxcd/flux-operator`) via a `FluxInstance` CRD in each cluster's `flux-system/` directory. The operator replaces the old `flux bootstrap` approach.

### Why Flux Operator

The old `flux bootstrap github` command wrote `gotk-sync.yaml` to git on every run, always stripping the `provider: github` field. This required a fragile post-bootstrap patch loop and git commit to restore the field. With the operator:

- `provider: github` is set once in `flux-instance.yaml` and never overwritten
- No git writes are needed from the bootstrap process — `contents: write` permission dropped from the workflow
- A single `helm upgrade --install` + `kubectl apply` replaces the entire bootstrap dance
- The operator manages Flux component rollouts; `spec.distribution.version` is the single version pin

### FluxInstance structure

Each cluster has `kubernetes/clusters/{cluster}/flux-system/flux-instance.yaml`:

```yaml
apiVersion: fluxcd.controlplane.io/v1
kind: FluxInstance
metadata:
  name: flux
  namespace: flux-system
spec:
  distribution:
    version: "2.8.x"        # minor-pinned semver range
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
    type: gcp               # "kubernetes" for kind
  sync:
    kind: GitRepository
    url: "https://github.com/olga-mir/playground.git"
    ref: "refs/heads/develop"
    path: "kubernetes/clusters/{cluster}"
    pullSecret: flux-system
    provider: github        # enables GitHub App auth — never overwritten by the operator
```

The `flux-system` secret contains the GitHub App credentials (`githubAppID`, `githubAppInstallationID`, `githubAppPrivateKey`). The `provider: github` field in the FluxInstance sync spec causes source-controller to use those credentials for automatic token refresh.

### Bootstrap flow (operator-based)

```
1. Create flux-system namespace
2. kubectl create secret generic flux-system  (GitHub App credentials)
3. helm upgrade --install flux-operator oci://ghcr.io/controlplaneio-fluxcd/charts/flux-operator
4. kubectl apply -f kubernetes/clusters/{cluster}/flux-system/flux-instance.yaml
5. operator installs Flux components and reconciles the sync GitRepository/Kustomization
```

No git writes, no patching, no fixup commits.

## Image automation

Full pipeline for automated image promotion:

```
ImageRepository  →  polls registry for new tags
ImagePolicy      →  selects latest tag matching pattern (e.g. ^main-(?P<ts>[0-9]+)-[a-f0-9]+$)
ImageUpdateAutomation  →  commits updated tag to source repo
Flux Kustomization     →  picks up the git commit and rolls out the new image
```

The image marker in the app's deployment YAML (in the source repo) must look like:
```yaml
image: olmigar/perf-lab:main-19700101000000-0000000 # {"$imagepolicy": "flux-system:perf-lab"}
```

All four resources live in `flux-system` namespace. The ImageUpdateAutomation's `sourceRef` points at the app's GitRepository, and it needs `provider: github` on that GitRepository (same as any other GitRepository using the flux-system GitHub App secret).

## Version upgrades

Flux component versions are managed via `spec.distribution.version` in the FluxInstance manifests. The value is a minor-pinned semver range (e.g. `"2.8.x"`). The operator selects the latest patch release within that range.

To upgrade:
- **Patch release** (e.g. 2.8.3 → 2.8.4): the `"2.8.x"` range already picks it up; no manifest change needed, but update README.md to reflect the current version.
- **Minor release** (e.g. 2.8.x → 2.9.x): update the version range in all three FluxInstance files and README.md.

See `docs/upgrade-versions.md` for the automated weekly upgrade workflow.

## Debugging Flux

**Check all resources across a cluster:**
```bash
flux get all -A --context <ctx>
# or use the fleet health script:
scripts/check-fleet-health.sh [short-cluster-name]
```

**Force reconciliation:**
```bash
# GitRepository
kubectl --context <ctx> annotate gitrepository flux-system -n flux-system \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite

# Kustomization
flux reconcile kustomization <name> -n flux-system --context <ctx>
```

**Notification controller logs** (for debugging Flux → GitHub dispatch):
```bash
kubectl --context <ctx> logs -n flux-system -l app=notification-controller --tail=30
```
Look for `"dispatching event"` (success) vs `"failed to send notification"` (error).

**FluxInstance status:**
```bash
kubectl --context <ctx> get fluxinstance flux -n flux-system -o yaml
kubectl --context <ctx> describe fluxinstance flux -n flux-system
```

## Flux API versions

Current versions in use:
- `source.toolkit.fluxcd.io/v1` — GitRepository, HelmRepository (v1beta2 removed)
- `kustomize.toolkit.fluxcd.io/v1` — Kustomization
- `helm.toolkit.fluxcd.io/v2` — HelmRelease
- `image.toolkit.fluxcd.io/v1beta2` — ImageRepository, ImagePolicy, ImageUpdateAutomation
- `fluxcd.controlplane.io/v1` — FluxInstance (Flux Operator CRD)

ImageUpdateAutomation message template uses `.Changed.Changes` (not `.Updated.Images` which was removed in Flux v2.7+):
```
'chore: update image to {{range .Changed.Changes}}{{.OldValue}} -> {{.NewValue}}{{end}}'
```
