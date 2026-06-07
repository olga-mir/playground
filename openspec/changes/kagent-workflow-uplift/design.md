# Design: kagent-workflow-uplift

## Approach

All changes are manifest-only (no new Helm charts, no custom controllers). We work entirely
within the existing GitOps structure: kagent-system lives under
`kubernetes/namespaces/base/kagent/`, team-charlie under `kubernetes/tenants/base/team-charlie/`.

## Agent Deployment Strategy

**Decision: standalone Agent CRs — do not use Helm-bundled agents for customised agents.**

kagent 0.9.2 bundles agents as opt-out Helm sub-charts. Customising them (e.g. adding A2A
tool wiring) would require `postRenderers` patches in the HelmRelease — a workaround that
fights chart ownership and makes the effective agent spec invisible in Git.

Instead:

1. **Disable all bundled Agent sub-charts** in `kagent-release.yaml` values (add `enabled: false`
   for any remaining enabled sub-chart agents — `cilium-agent`, `k8s-agent`, `observability-agent`,
   `promql-agent`, `helm-agent`).
2. **Write our own Agent CRs** directly in the Kustomize tree — full control, fully GitOps.

The kagent controller, CRDs, and built-in **ToolServers** (Kubernetes API tool, Prometheus
tool, etc.) remain Helm-managed. Only the Agent CRs move to our own manifests.

> **Before rebuilding:** confirm which Helm sub-charts are tool server *implementations* vs.
> pure Agent wrappers. Tool server sub-charts must stay enabled (or be replicated) — disabling
> them would leave agents without callable tools.

## Agents to Deploy as Standalone

**Agent 1: `cilium-network-agent` (kagent-system)**

Replaces the bundled `cilium-debug-agent`. Owns the A2A demo chain:

```yaml
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: cilium-network-agent
  namespace: kagent-system
spec:
  modelConfig: claude-model-config
  systemMessage: |
    You diagnose Cilium network issues: node health, policy hit/drop counts,
    Hubble flow state. For metric trend analysis delegate to observability-agent
    or promql-agent.
  a2aConfig:
    skills:
      - id: cilium-network-debug
        description: >
          Diagnose Cilium network issues and delegate metric analysis downstream.
        tags: [cilium, networking, observability]
  tools:
    - type: Agent
      agent:
        name: observability-agent
        namespace: kagent-system
    - type: Agent
      agent:
        name: promql-agent
        namespace: kagent-system
```

**Agent 2: `crossplane-composition-fixer` (team-charlie)**

Already written in comments — uncomment verbatim. Standalone from the start since it lives
in a tenant namespace rather than kagent-system.

## Cross-Namespace allowedNamespaces

For `k8s-agent` (still bundled, or also moved to standalone) to accept calls from
`team-charlie/crossplane-composition-fixer`:

- If the CRD exposes `allowedNamespaces`, set it directly on the Agent CR.
- If not (v1alpha1 gap), ensure the `team-charlie/kagent` ServiceAccount has a
  ClusterRoleBinding subject entry on the existing `kagent-crossplane-github-access` role so
  it can reach Crossplane and Kubernetes resources, and the controller routes by RBAC.

## File Change Map

| File | Change |
|------|--------|
| `namespaces/base/kagent/kagent/helm/kagent-release.yaml` | Add `enabled: false` for all bundled Agent sub-charts we are replacing |
| `namespaces/base/kagent/kagent/config/` | Add `cilium-network-agent.yaml` standalone Agent CR |
| `tenants/base/team-charlie/kagent-agents.yaml` | Uncomment `crossplane-composition-fixer` Agent CR |
| `namespaces/base/kagent/kagent/config/rbac.yaml` | Add `team-charlie/kagent` SA subject to cross-namespace binding |

## Validation Steps

1. After HelmRelease reconciles: `kubectl get agents -n kagent-system --context <apps-dev>` —
   confirm bundled agent pods are gone; `cilium-network-agent` pod appears.
2. Describe `cilium-network-agent` — confirm `spec.tools` lists observability and promql agents.
3. Check `crossplane-composition-fixer` is `Ready` in team-charlie.
4. Send test prompts via kagent CLI and observe A2A delegation traces.
