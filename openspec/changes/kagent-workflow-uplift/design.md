# Design: kagent-workflow-uplift

## Approach

All changes are manifest-only (no new Helm charts, no custom controllers). We work entirely
within the existing GitOps structure: kagent-system lives under
`kubernetes/namespaces/base/kagent/`, team-charlie under `kubernetes/tenants/base/team-charlie/`.

## A2A Wiring Strategy

kagent 0.9.2 bundles agents as Helm sub-charts. We cannot patch the sub-chart Agent CRs
directly via `values.yaml` (Helm values don't expose tool lists). Two options:

1. **Post-render Kustomize patch** — add a strategic-merge patch in the kagent Kustomize
   layer that appends `tools` entries to the cilium-debug-agent's spec after Helm renders it.
2. **Override via HelmRelease `postRenderers`** — use Flux's `postRenderers.kustomize.patches`
   in the HelmRelease to inject the tool entries at reconcile time.

**Decision: use HelmRelease `postRenderers`** — keeps the patch co-located with the
HelmRelease manifest, avoids a separate kustomization layer, and is the established Flux
pattern for patching Helm-managed CRs.

Example patch structure in `kagent-release.yaml`:

```yaml
spec:
  postRenderers:
    - kustomize:
        patches:
          - target:
              kind: Agent
              name: cilium-debug-agent
            patch: |
              - op: add
                path: /spec/tools/-
                value:
                  type: Agent
                  agent:
                    name: observability-agent
                    namespace: kagent-system
              - op: add
                path: /spec/tools/-
                value:
                  type: Agent
                  agent:
                    name: promql-agent
                    namespace: kagent-system
```

Note: verify the `spec/tools` path exists on the rendered manifest before using `add`
(use `replace` if the field is present but empty, or initialise with a full `replace`).

## team-charlie Agent

The Agent CR is already written (in comments). Uncommenting is the sole code change.
The ModelConfig and ToolServer are already active. RBAC requires one additional
ClusterRoleBinding subject for `team-charlie/kagent` SA — add it to `rbac.yaml` or
`kagent-agents.yaml` as a second subject entry.

## Cross-Namespace allowedNamespaces

Based on the A2A docs, `allowedNamespaces` is a field on the Agent spec that controls
which namespaces may invoke the agent via A2A. For `k8s-agent` to accept calls from
`team-charlie`, we need a postRenderer patch or a direct overlay entry:

```yaml
spec:
  allowedNamespaces:
    - team-charlie
```

If kagent 0.9.2's v1alpha1 CRD does not expose this field, the fallback is pure RBAC:
ensure `team-charlie/kagent` has `get`/`list`/`watch` on the A2A endpoint Service/Endpoints
in `kagent-system`, which the controller uses to validate callers.

## File Change Map

| File | Change |
|------|--------|
| `namespaces/base/kagent/kagent/helm/kagent-release.yaml` | Add `postRenderers` block to patch cilium-debug-agent tools |
| `tenants/base/team-charlie/kagent-agents.yaml` | Uncomment Agent CR; add ClusterRoleBinding subject for team-charlie/kagent SA |
| `namespaces/base/kagent/kagent/config/rbac.yaml` | (If needed) Add k8s-agent allowedNamespaces patch or team-charlie SA binding |

## Validation Steps

1. After HelmRelease reconciles: `kubectl get agents -n kagent-system --context <apps-dev>` —
   confirm only expected 5 agents present.
2. Describe `cilium-debug-agent` — confirm tools list includes observability and promql agents.
3. Check `crossplane-composition-fixer` is `Ready` in team-charlie.
4. Send test prompts via `kubectl kagent run` or the kagent CLI and observe traces.
