# Proposal: kagent-runtime-validation

## Summary

Run the live-cluster validation tasks deferred from `kagent-workflow-uplift` (#107) because
they require a provisioned apps-dev GKE cluster. Produces evidence that the A2A delegation
chain works end-to-end and that namespace isolation blocks cross-team calls — the baseline
that OpenFGA must replicate in tuple-driven form before `openfga-kagent-authz-poc` begins.

## Problem

All manifests from #107 are merged and Flux-reconciled, but two task groups have never
been executed against a live cluster:

- **T4** — no proof that `cilium-network-agent` actually delegates to observability/promql
  agents at runtime, or that `crossplane-composition-fixer` delegates to `k8s-agent` across
  namespaces.
- **T5** — no captured rejection evidence that team-charlie cannot reach team-alpha — the
  "blocked by default" baseline that OpenFGA will eventually govern with tuples.

Without this evidence, `openfga-kagent-authz-poc` has no ground truth to verify against.

## Proposed Solution

Runtime-only session (no new manifests required):

1. Provision apps-dev cluster (normal session start via `task agentic:deploy`).
2. **T4** — Send two test prompts via kagent CLI and capture delegation traces in agent logs.
3. **T5** — Deploy a minimal stub Agent in `team-alpha`, attempt a cross-team call from
   `crossplane-composition-fixer`, capture the rejection log line, remove the stub.
4. Append captured output to `docs/kagent-a2a-workflow.md` as a validation evidence section.

## Capabilities Affected

- No manifest changes — runtime validation only.
- `docs/kagent-a2a-workflow.md` — append captured evidence (optional, low-cost doc update).

## Impact & Risks

- Unblocks `openfga-kagent-authz-poc`; without this, OpenFGA POC has no baseline to verify
  against.
- Risk: kagent CLI / A2A prompt interface may differ from doc examples — may need to discover
  the actual invocation method (kagent CLI vs. kubectl exec into agent pod).
- Risk: Prometheus endpoint reachability from agent pods not yet confirmed; promql-agent may
  fail to connect if kube-prometheus-stack service DNS differs from assumed value.
- Effort: ~1 hour of cluster time once apps-dev is provisioned.

## Out of Scope

- Any manifest changes to kagent agents.
- OpenFGA installation or tuple policy.
- Re-enabling pruned agents (istio, argo-rollouts, kgateway).
