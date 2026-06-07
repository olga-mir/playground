# Tasks: kagent-workflow-uplift

## T1 — Validate pruned agent set

- [ ] Confirm HelmRelease `kagent` has `istio-agent.enabled: false`, `argo-rollouts-agent.enabled: false`, `kgateway-agent.enabled: false` (already in values — just verify no drift).
- [ ] After next reconcile, run `kubectl get agents -n kagent-system --context <apps-dev>` and assert exactly these agents are present: `cilium-*`, `k8s-agent`, `observability-agent`, `promql-agent`, `helm-agent`.

## T2 — Wire cilium-debug-agent A2A tools

- [ ] Inspect the rendered cilium-debug-agent spec: `kubectl get agent cilium-debug-agent -n kagent-system -o yaml --context <apps-dev>` — note existing `spec.tools` structure.
- [ ] Add `postRenderers.kustomize.patches` block to `namespaces/base/kagent/kagent/helm/kagent-release.yaml` targeting `cilium-debug-agent`, injecting `observability-agent` and `promql-agent` as Agent tools (see design.md for patch syntax).
- [ ] Add `a2aConfig.skills` metadata to the same patch (cilium-network-debug skill, per `specs/a2a-demo-flow.md`).
- [ ] Verify Prometheus URL from within the agent pod: `kubectl exec -n kagent-system <cilium-debug-agent-pod> -- curl -s http://kube-prometheus-stack-prometheus.monitoring:9090/-/healthy --context <apps-dev>`.
- [ ] Commit and push; wait for HelmRelease to reconcile.
- [ ] Validate: describe agent and confirm tools list.

## T3 — Activate crossplane-composition-fixer in team-charlie

- [ ] Uncomment the Agent CR block in `kubernetes/tenants/base/team-charlie/kagent-agents.yaml`.
- [ ] Add `team-charlie/kagent` ServiceAccount as a subject in the ClusterRoleBinding in the same file (or `config/rbac.yaml`).
- [ ] Confirm `k8s-agent` spec supports `allowedNamespaces`; if yes, add a postRenderer patch to include `team-charlie`. If the field is absent in v1alpha1, rely on RBAC only and document.
- [ ] Commit and push; verify `crossplane-composition-fixer` reaches `Ready` in team-charlie.

## T4 — A2A end-to-end demo test

- [ ] Send test prompt to `cilium-debug-agent`: "Check Cilium node health on apps-dev and summarise any network policy drops in the last hour." Confirm trace shows delegation to observability-agent or promql-agent.
- [ ] Send test prompt to `crossplane-composition-fixer`: "List all Crossplane XRs in the cluster and report their status." Confirm it delegates to `k8s-agent`.
- [ ] Record session traces / screenshots for #103 handoff.

## T5 — Cross-team boundary smoke test

- [ ] If no agent exists in `team-alpha`, create a minimal stub Agent CR labelled `openfga-baseline-test: "true"` in `kubernetes/tenants/base/team-alpha/`.
- [ ] Attempt to invoke the stub from a prompt on `crossplane-composition-fixer` (via an explicit tool call or by asking it to delegate to `team-alpha/stub-agent`).
- [ ] Document the rejection error (expected: A2A 403 or controller refusal) and the log line in `kagent-controller`.
- [ ] Remove the stub Agent CR after capturing the result (or keep behind a feature label if useful for #103).
