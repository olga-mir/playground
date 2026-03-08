# GitHub Integration

## GitHub App authentication for Flux

Flux uses a GitHub App (not SSH deploy keys or a PAT) for all `GitRepository` auth. This survives cluster rebuilds without accumulating deploy keys in the repo.

See `docs/github-app-setup.md` for one-time App creation steps.

### How it works

`flux bootstrap --token-auth` uses a PAT only during the bootstrap push (installs Flux + pushes `gotk-sync.yaml` to git). Immediately after, the `flux-system` secret is replaced with GitHub App credentials:

```
githubAppID             → App ID
githubAppInstallationID → Installation ID
githubAppPrivateKey     → PEM private key (from file, not --from-literal)
```

source-controller natively handles App token refresh using these fields — no external token generation needed.

### Required secrets

**Local env vars** (in `.setup-env`):

| Variable | Purpose |
|---|---|
| `GITHUB_APP_ID` | GitHub App ID |
| `GITHUB_APP_INSTALLATION_ID` | Installation ID |
| `GITHUB_APP_PRIVATE_KEY_FILE` | Path to downloaded PEM file |
| `GITHUB_FLUX_PLAYGROUND_PAT` | Fine-grained PAT used during `flux bootstrap` and for `github-webhook-token` |

**GitHub Actions secrets** (repo settings → Secrets):

| Secret | Purpose |
|---|---|
| `GH_APP_ID` | GitHub App ID |
| `GH_APP_INSTALLATION_ID` | Installation ID |
| `GH_APP_PRIVATE_KEY` | Full PEM content (copy from `cat $GITHUB_APP_PRIVATE_KEY_FILE`) |
| `GH_FLUX_PAT` | PAT with `repo` scope for the `github-webhook-token` notification secret |
| `PROJECT_ID` | GCP project ID |
| `WIF_PROVIDER` / `WIF_SERVICE_ACCOUNT` | Workload Identity Federation for GKE access |

> Note: GitHub repo secrets cannot start with `GITHUB_` — hence `GH_APP_*` prefix.

### Recreating the flux-system secret manually

If `githubAppPrivateKey` is empty (common after a broken workflow run):
```bash
kubectl --context <ctx> create secret generic flux-system -n flux-system \
  --from-literal=githubAppID="${GITHUB_APP_ID}" \
  --from-literal=githubAppInstallationID="${GITHUB_APP_INSTALLATION_ID}" \
  --from-file=githubAppPrivateKey="${GITHUB_APP_PRIVATE_KEY_FILE}" \
  --dry-run=client -o yaml | kubectl --context <ctx> apply -f -
```

Always use `--from-file` for the private key (not `--from-literal`) to preserve newlines correctly.

## Cluster bootstrap workflow

`.github/workflows/flux-bootstrap.yml` is triggered by a `repository_dispatch` event from Flux when a GKE cluster is provisioned. It:

1. Extracts cluster name and location from the event payload
2. Authenticates to GCP via Workload Identity Federation
3. Waits for the GKE cluster to be accessible
4. Creates `platform-config` ConfigMap in `flux-system`
5. Runs `flux bootstrap github --token-auth`
6. Replaces `flux-system` secret with GitHub App credentials
7. Creates `github-webhook-token` secret (from `GH_FLUX_PAT`) for the notification provider
8. Patches all GitRepositories referencing `flux-system` secret to add `provider: github`
9. Pushes a fixup commit to restore `provider: github` in `gotk-sync.yaml`

The workflow runs from the **default branch** (`develop`). GitHub only reads `repository_dispatch` workflows from the default branch — if the workflow file is not on the default branch, it will not be triggered.

## Flux notifications → GitHub Actions

Flux fires a `repository_dispatch` event when the `clusters` Kustomization reconciles a GKE cluster resource. The event type format is:

```
Kustomization/clusters.flux-system
```

The workflow trigger must match this exactly:
```yaml
on:
  repository_dispatch:
    types: [Kustomization/clusters.flux-system]
```

Glob wildcards (`*`) are supported: `Kustomization/*-cluster.flux-system`.

The notification provider (`github-dispatch`) uses the `github-webhook-token` secret (key: `token`) to authenticate the dispatch call. This is separate from the `flux-system` GitHub App secret. The `github-webhook-token` must be present on the cluster **before** the GKECluster resource is created — if it's missing when the event fires, the dispatch fails and the event does not retry.

### Debugging notifications

```bash
# Check notification controller for dispatch success/failure
kubectl --context <ctx> logs -n flux-system -l app=notification-controller --tail=30

# Check Provider and Alert status
kubectl --context <ctx> describe provider github-dispatch -n flux-system
kubectl --context <ctx> describe alert github-dispatch-cluster-created -n flux-system

# Force a re-dispatch by triggering Kustomization reconciliation
kubectl --context <ctx> annotate kustomization clusters -n flux-system \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
```

Common failure causes:
- `github-webhook-token` secret missing → create it before cluster provisioning
- `401 Bad credentials` → PAT in `github-webhook-token` lacks `repo` scope or is expired
- `provider not set to github` on notification provider's GitRepository → see `docs/flux-gitops.md`
- Workflow not on default branch → change repo default branch in Settings or merge workflow to it
