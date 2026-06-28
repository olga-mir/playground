# Tasks: kagent-runtime-validation

## T1 — Provision and verify cluster

- [ ] Run `task agentic:deploy` (or `task agentic:resume PHASE=workload` if control-plane
      is already up). Wait for apps-dev cluster to be healthy.
- [ ] Confirm all kagent agents are Ready: `kubectl get agents -A --context gke_${PROJECT_ID}_${REGION}-a_apps-dev`
      — expect `cilium-network-agent`, `k8s-agent`, `observability-agent`, `promql-agent`,
      `helm-agent` in kagent-system and `crossplane-composition-fixer` in team-charlie, all
      `READY=True`.
- [ ] Discover prompt invocation method (kagent CLI / kubectl exec / UI) and record it.

## T2 — A2A end-to-end: Chain 1

See `specs/a2a-end-to-end-validation.md`.

- [ ] Send test prompt to `cilium-network-agent` ("Check Cilium node health and summarise
      any network policy drops in the last hour.").
- [ ] Capture delegation log line showing `observability-agent` or `promql-agent` was called.
- [ ] Confirm final response is coherent (not an error message).

## T3 — A2A end-to-end: Chain 2

See `specs/a2a-end-to-end-validation.md`.

- [ ] Send test prompt to `crossplane-composition-fixer` ("List all Crossplane XRs in the
      cluster and report their status.").
- [ ] Capture outbound delegation log in team-charlie pod and inbound log in k8s-agent pod.
- [ ] Confirm final response lists XR status.

## T4 — Cross-team boundary baseline

See `specs/cross-team-boundary-baseline.md`.

- [ ] Create `team-alpha` namespace if it doesn't exist.
- [ ] Apply stub Agent CR in `team-alpha` (labelled `openfga-baseline-test: "true"`).
- [ ] Attempt cross-team call from `crossplane-composition-fixer` to `stub-agent`.
- [ ] Capture the exact rejection log line from kagent-controller or agent pod.
- [ ] Document which component enforces the block and what the log says.
- [ ] Delete `stub-agent` and `team-alpha` namespace.

## T5 — Evidence capture and doc update

- [ ] Paste all captured log lines/outputs into `docs/kagent-a2a-workflow.md` under a new
      `## Validation Evidence` section.
- [ ] Close issue #107 or leave a comment with the evidence link.
- [ ] Confirm `openfga-kagent-authz-poc` prerequisites are met and that change is unblocked.
