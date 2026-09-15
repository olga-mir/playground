# Tasks: kguardian-apps-dev

## Progress
9 / 21 complete

## Implementation Tasks

### Phase: Setup
- [x] Look up the current kguardian chart version at `oci://ghcr.io/kguardian-dev/charts/kguardian` to pin in the `HelmRelease` (1.23.1 at research time — confirm current)
- [x] Create `kubernetes/namespaces/base/kguardian/helm/` with `namespace.yaml`, `kguardian-helm-repo.yaml` (OCI `HelmRepository`), `kguardian-release.yaml`, and `kustomization.yaml` referencing all three — mirroring `namespaces/base/litmus/helm/`
- [x] Create `kubernetes/clusters/apps-dev/kguardian-crds.yaml` — Flux `Kustomization` with `path: ./kubernetes/namespaces/base/kguardian/helm`, matching the shape of `litmus-crds.yaml`/`kagent-crds.yaml` (interval, timeout, prune, wait, sourceRef, `postBuild.substituteFrom` the `platform-config` ConfigMap)
- [x] Add `- name: kguardian-crds` to `platform.yaml`'s `dependsOn` list

### Phase: Core Implementation
- [x] Set `telemetry.enabled: false` in `kguardian-release.yaml` values
- [x] Leave `database.enabled` at its chart default (bundled Postgres on) and `ai.enabled` at its chart default (off) — no `storageClassName` override, no AI secret
- [x] Set `install.createNamespace: true`, `install.timeout: 15m`, `install.remediation.retries: 3`, `upgrade.timeout: 15m`, `upgrade.remediation.retries: 3` on the `HelmRelease`
- [x] Validate the new/changed kustomizations with `task validate:kustomize-build`
- [x] Validate `kguardian-crds.yaml` and the `platform.yaml` diff with `yq` before committing

### Phase: Testing
- [ ] Provision the fleet (`task setup:deploy`) and confirm apps-dev nodes meet the kernel ≥ 6.2 floor: `kubectl --context <apps-dev-context> get nodes -o wide`
- [ ] Watch `flux get kustomizations --context <apps-dev-context>` until `kguardian-crds` reports `Ready`
- [ ] Watch `flux get helmreleases -n kguardian --context <apps-dev-context>` until the `kguardian` release reports `Ready` (Controller DaemonSet, Broker, bundled Postgres, Evaluator, Web UI all healthy)
- [ ] Run `scripts/check-fleet-health.sh` to confirm no fleet regression
- [ ] Verify scenario (apps-dev-workloads): Controller observes a tenant pod's connections — confirm flows are captured for a `team-alpha` pod
- [ ] Verify scenario (apps-dev-workloads): generate a `CiliumNetworkPolicy` from observed traffic via `kubectl kguardian gen netpol <pod> -n team-alpha --type cilium --output-dir ./policies` (install the CLI plugin locally via `quick-install.sh` first)
- [ ] Verify scenario (apps-dev-workloads): generate a `SeccompProfile` in audit mode via `kubectl kguardian gen seccomp <pod> -n team-alpha --output-dir ./seccomp`
- [ ] Verify scenario (fleet-security-tooling): telemetry check-in is disabled — confirm no daily check-in request in Broker logs
- [ ] Verify scenario (fleet-security-tooling): optional AI Assistant remains off — confirm no LLM Bridge deployment and no LLM API key `Secret` exists
- [ ] Verify scenario (flux-gitops): a transient install failure is retried — check `flux get helmreleases` events show remediation retries configured, not a permanently failed release

### Phase: Cleanup
- [ ] Confirm `task setup:cleanup` removes kguardian's namespace and the bundled Postgres PVC without leaving an orphaned GCE persistent disk behind
- [ ] If kguardian becomes a durable part of the fleet (beyond this exploration), document install/usage steps in `docs/operations.md` or `docs/tenants.md` — only on explicit request, per this repo's no-proactive-`.md`-files rule
