# Tasks: kagent-workflow-uplift

## T1 — Validate pruned agent set

- [x] Confirm HelmRelease `kagent` has `istio-agent.enabled: false`, `argo-rollouts-agent.enabled: false`, `kgateway-agent.enabled: false` (already in values — just verify no drift).
- [ ] After next reconcile, run `kubectl get agents -n kagent-system --context <apps-dev>` and assert exactly these agents are present: `cilium-*`, `k8s-agent`, `observability-agent`, `promql-agent`, `helm-agent`.

## T2 — Deploy standalone cilium-network-agent

- [x] ~~Audit kagent sub-charts~~ Already done (0.9.6 chart inspected). Tool servers to keep enabled: `kagent-tools`, `kmcp`, `grafana-mcp`, `querydoc`. Agent sub-charts to disable: `k8s-agent`, `kgateway-agent`, `istio-agent`, `promql-agent`, `observability-agent`, `argo-rollouts-agent`, `helm-agent`, `cilium-policy-agent`, `cilium-manager-agent`, `cilium-debug-agent`.
- [x] Add `cilium-agent.enabled: false` (and any other replaced agent sub-charts) to HelmRelease values in `kagent-release.yaml`.
- [x] Write `namespaces/base/kagent/kagent/config/cilium-network-agent.yaml` — standalone Agent CR with tools referencing `observability-agent` and `promql-agent`, plus `a2aConfig.skills` (see `specs/a2a-demo-flow.md` for full spec).
- [x] Add the new file to `namespaces/base/kagent/kagent/config/kustomization.yaml`.
- [ ] Verify Prometheus URL reachable from kagent-system: `kubectl exec -n kagent-system <any-agent-pod> -- curl -s http://kube-prometheus-stack-prometheus.monitoring:9090/-/healthy --context <apps-dev>`.
- [x] Commit and push; wait for HelmRelease to reconcile.
- [ ] Validate: `kubectl get agent cilium-network-agent -n kagent-system -o yaml --context <apps-dev>` — confirm tools list.

## T3 — Activate crossplane-composition-fixer in team-charlie

- [x] Uncomment the Agent CR block in `kubernetes/tenants/base/team-charlie/kagent-agents.yaml`.
- [x] Add `team-charlie/kagent` ServiceAccount as a subject in the ClusterRoleBinding in the same file (or `config/rbac.yaml`).
- [x] Confirm `k8s-agent` spec supports `allowedNamespaces`; if yes, add a postRenderer patch to include `team-charlie`. If the field is absent in v1alpha1, rely on RBAC only and document.
- [x] Commit and push; verify `crossplane-composition-fixer` reaches `Ready` in team-charlie. (commit done; awaiting cluster validation)

## T4 — A2A end-to-end demo test

See TEST_PLAN.md section "T4: A2A End-to-End Demo Test" for detailed procedures.

- [ ] Send test prompt to `cilium-network-agent`: "Check Cilium node health on apps-dev and summarise any network policy drops in the last hour." Confirm trace shows delegation to observability-agent or promql-agent.
- [ ] Send test prompt to `crossplane-composition-fixer`: "List all Crossplane XRs in the cluster and report their status." Confirm it delegates to `k8s-agent`.
- [ ] Record session traces / screenshots for #103 handoff.

## T5 — Cross-team boundary smoke test

See TEST_PLAN.md section "T5: Cross-Team Boundary Smoke Test" for detailed procedures.

- [ ] If no agent exists in `team-alpha`, create a minimal stub Agent CR labelled `openfga-baseline-test: "true"` in `kubernetes/tenants/base/team-alpha/`.
- [ ] Attempt to invoke the stub from a prompt on `crossplane-composition-fixer` (via an explicit tool call or by asking it to delegate to `team-alpha/stub-agent`).
- [ ] Document the rejection error (expected: A2A 403 or controller refusal) and the log line in `kagent-controller`.
- [ ] Remove the stub Agent CR after capturing the result (or keep behind a feature label if useful for #103).
