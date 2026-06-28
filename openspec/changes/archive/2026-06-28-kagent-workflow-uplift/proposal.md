# Proposal: kagent-workflow-uplift

## Summary

Uplift the kagent 0.9.2 configuration after the initial quick-wins (agent pruning + model bump)
to produce a validated, meaningful multi-agent setup: a working A2A chain from a cilium debug
agent through to observability/promql, an activated team-charlie agent with proper k8s-agent
delegation, and verified cross-namespace RBAC isolation. This is the precondition for the
OpenFGA authz POC (#103).

## Problem

The `develop` branch already disabled three unused agents and bumped ModelConfigs to
`claude-sonnet-4-6`, but:

- No A2A tool wiring exists on the remaining kagent-system agents — the Helm chart bundles
  `cilium-*`, `k8s-agent`, `observability-agent`, `promql-agent`, and `helm-agent` but there
  are no Agent-to-Agent tool references in the current manifests.
- The `crossplane-composition-fixer` Agent CR in `team-charlie` is fully commented out, so
  team-charlie has a ModelConfig but no active agent.
- There is no smoke test or evidence that cross-namespace A2A calls respect namespace
  boundaries — the baseline for OpenFGA tuple-driven policy is unestablished.

## Proposed Solution

1. **Validate pruned set** — confirm the three disabled agents are gone after HelmRelease
   reconciles; document the expected remaining set.

2. **Wire A2A demo chain** — patch the `cilium-debug-agent` (or create an overlay) to add
   `observability-agent` and `promql-agent` as Agent tools. Add `a2aConfig.skills` metadata
   so the agent advertises its capabilities. Verify a Prometheus endpoint is reachable from
   the agent pod in `apps-dev`.

3. **Activate team-charlie agent** — uncomment `crossplane-composition-fixer`, confirm it
   references `k8s-agent` via a cross-namespace Agent tool entry and that `k8s-agent` allows
   the `team-charlie` namespace via `allowedNamespaces`.

4. **Cross-team boundary test** — demonstrate team-charlie's SA cannot call a hypothetical
   `team-alpha` agent (no `allowedNamespaces` entry, no RBAC binding). Document expected
   behaviour as a smoke-test procedure for the OpenFGA baseline.

## Capabilities Affected

- `kubernetes/namespaces/base/kagent/` — HelmRelease values, agent config overlays
- `kubernetes/tenants/base/team-charlie/` — Agent CR, RBAC
- kagent A2A runtime (`allowedNamespaces`, Agent tool type)

## Impact & Risks

- **Enables** OpenFGA POC (#103) by providing a stable, tested multi-agent baseline.
- **Risk — upstream CRD field names**: kagent 0.9.2 Agent spec uses `v1alpha1`; A2A fields
  (`allowedNamespaces`, tool `agent.name` vs `agent.ref`) must be validated against the actual
  installed CRD schema, not just docs.
- **Risk — Prometheus reachability**: kube-prometheus-stack is deployed on apps-dev but the
  ServiceMonitor endpoint URL is not confirmed; needs a test query before wiring the agent.
- Estimated effort: small (half-day manifest work + one verification pass).

## Out of Scope

- OpenFGA installation and tuple policy (#103)
- Re-enabling or replacing the pruned agents (istio, argo-rollouts, kgateway)
- Multi-cluster A2A (everything is scoped to apps-dev)
