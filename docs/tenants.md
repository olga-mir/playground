# Tenants

## Pattern

Tenants use a **multi-repo** GitOps model: application manifests live in the application's own repo; the platform repo (this repo) holds only the Flux wiring (GitRepository + Kustomization + image automation resources).

```
playground (this repo)               playground-sre (app repo)
└── kubernetes/tenants/base/sre/      └── k8s/
    ├── namespace.yaml                    ├── kustomization.yaml
    ├── gitrepository.yaml                └── deployment.yaml  ← image marker here
    ├── flux-kustomization.yaml
    ├── image-repository.yaml
    ├── image-policy.yaml
    └── image-update-automation.yaml
```

Flux on the apps-dev cluster watches the app repo directly. When a new image is pushed, the ImageUpdateAutomation commits the updated tag back to the app repo, and the Kustomization rolls it out.

## Adding a new tenant

1. **In this repo** — create `kubernetes/tenants/base/<name>/` with:
   - `namespace.yaml` — namespace with `workload-type: application` label
   - `gitrepository.yaml` — points at the app repo; must include `provider: github` if using the `flux-system` GitHub App secret
   - `flux-kustomization.yaml` — watches `./k8s` in the app repo; `dependsOn: tenants`
   - `image-repository.yaml` — polls the container registry
   - `image-policy.yaml` — selects latest tag via filter pattern
   - `image-update-automation.yaml` — commits tag updates back to the app repo
   - `kustomization.yaml` — lists all of the above

2. **Add to** `kubernetes/tenants/base/kustomization.yaml` resources list

3. **In the app repo** — add Flux image marker to the deployment:
   ```yaml
   image: registry/image:placeholder # {"$imagepolicy": "flux-system:<policy-name>"}
   ```
   and a `k8s/kustomization.yaml` listing the manifests

## Image tag convention

Tags must follow the pattern Flux can sort numerically by timestamp:
```
main-<YYYYMMDDHHMMSS>-<shortsha>
```

ImagePolicy filter:
```yaml
filterTags:
  pattern: '^main-(?P<ts>[0-9]+)-[a-f0-9]+$'
  extract: '$ts'
policy:
  numerical:
    order: asc
```

The placeholder tag `main-19700101000000-0000000` (Unix epoch) appears when the marker exists but no matching image has been pushed yet. Once a real image is pushed, ImageUpdateAutomation will commit the correct tag.

## Current tenants

| Tenant | Namespace | App repo | Registry |
|---|---|---|---|
| sre | `sre` | `github.com/olga-mir/playground-sre` | `index.docker.io/olmigar/perf-lab` |

Synthetic team tenants (`team-alpha`, `team-bravo`, `team-charlie`, `team-platform`) exist for testing the tenants kustomization structure but have no real workloads.

## Namespace labels

Tenant namespaces use `workload-type: application` to distinguish them from platform namespaces.
