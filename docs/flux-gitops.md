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

## Known Flux quirk: `flux bootstrap` strips `provider: github`

`flux bootstrap` regenerates `gotk-sync.yaml` on every run **without** the `provider: github` field. Without this field, source-controller cannot use GitHub App credentials and all syncs fail silently — the GitRepository stays stuck on its last artifact and never picks up new commits.

**Symptoms**: GitRepository shows `has github app data but provider is not set to github`. New git commits are not picked up despite the 1m interval.

**Fix** (manual, when a cluster is already broken):
```bash
# 1. Suspend so kustomize-controller stops reverting the patch
kubectl --context <ctx> patch kustomization flux-system -n flux-system --type=merge -p '{"spec":{"suspend":true}}'
# 2. Patch live resource
kubectl --context <ctx> patch gitrepository flux-system -n flux-system --type=merge -p '{"spec":{"provider":"github"}}'
# 3. Wait ~15s for GitRepository to fetch latest commits, then unsuspend
kubectl --context <ctx> patch kustomization flux-system -n flux-system --type=merge -p '{"spec":{"suspend":false}}'
```

**Prevention**: The `flux-bootstrap.yml` workflow and `bootstrap-control-plane-cluster.sh` both patch the live resource and push a fixup commit to git after bootstrap. The committed `gotk-sync.yaml` files always include `provider: github` — but bootstrap overwrites them, so the fixup step is essential.

Any GitRepository that references the `flux-system` secret (including tenant GitRepositories) also needs `provider: github` in its spec.

### Re-bootstrap failure: bootstrap wait times out

On **re-bootstrap** (running bootstrap against a cluster that already ran Flux), there is an additional failure mode that causes `flux bootstrap` itself to time out before the fixup step is even reached.

**Root cause**: `flux bootstrap --token-auth` sets up the `flux-system` secret via `kubectl apply`. Kubernetes `apply` uses 3-way merge: fields present in the live object but absent from the previous `last-applied-configuration` are preserved. After the first successful bootstrap the secret is replaced with GitHub App credentials (`githubAppID`, `githubAppInstallationID`, `githubAppPrivateKey`). On the next bootstrap run, `flux bootstrap` applies a token-only secret — but the GitHub App fields were not in the *old* `last-applied-configuration`, so 3-way merge keeps them. The secret now has both a token **and** GitHub App data.

At the same time, `flux bootstrap` pushes a fresh `gotk-sync.yaml` without `provider: github`. source-controller sees a secret with GitHub App fields but no `provider: github` declared on the GitRepository and immediately raises:

```
has github app data but provider is not set to github
```

The GitRepository never becomes Ready, the bootstrap wait (10 min) expires, and the workflow fails before it can apply the fixup.

**Fix applied**: Both `flux-bootstrap.yml` and `bootstrap-control-plane-cluster.sh` now explicitly delete the `flux-system` secret with `--ignore-not-found` before calling `flux bootstrap`. This gives bootstrap a clean slate regardless of what was left by the previous run.

**Why this is not fixed upstream**: `flux bootstrap` is designed as an idempotent installer for net-new clusters; it has no knowledge of post-bootstrap secret replacement workflows. The upstream GitRepository type does not accept `provider` in the bootstrap path, and the Flux team considers post-bootstrap patching an operator responsibility (see olga-mir/playground#62).

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

## Flux API versions

Current versions in use:
- `source.toolkit.fluxcd.io/v1` — GitRepository, HelmRepository (v1beta2 removed)
- `kustomize.toolkit.fluxcd.io/v1` — Kustomization
- `helm.toolkit.fluxcd.io/v2` — HelmRelease
- `image.toolkit.fluxcd.io/v1beta2` — ImageRepository, ImagePolicy, ImageUpdateAutomation

ImageUpdateAutomation message template uses `.Changed.Changes` (not `.Updated.Images` which was removed in Flux v2.7+):
```
'chore: update image to {{range .Changed.Changes}}{{.OldValue}} -> {{.NewValue}}{{end}}'
```

