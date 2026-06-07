# Spec: A2A Demo Flow (cilium → observability/promql)

## Goal

Wire a cilium-debug-agent that can delegate metric queries to observability-agent and
promql-agent, demonstrating end-to-end A2A orchestration:

```
operator (kubectl / kagent CLI)
  → cilium-debug-agent   (Cilium node health, policy hits, flow state)
      → observability-agent   (Prometheus trend query)
      → promql-agent          (PromQL anomaly analysis)
```

## Agent Tool Wiring

`cilium-debug-agent` must declare both downstream agents as tools in its spec:

```yaml
spec:
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

Because all three agents live in `kagent-system`, cross-namespace RBAC is not required for
this part — but `observability-agent` and `promql-agent` must permit delegation from
`cilium-debug-agent` via `allowedNamespaces` (or default to same-namespace, which already
applies here).

## A2A Skills Metadata

`cilium-debug-agent` should advertise its capability so callers can discover it:

```yaml
spec:
  a2aConfig:
    skills:
      - id: cilium-network-debug
        description: >
          Diagnose Cilium network issues: node health, policy hit/drop counts,
          Hubble flow state. Delegates metric trend analysis to observability-agent
          and promql-agent.
        examples:
          - "Check Cilium node health and report any policy drops in the last hour"
          - "Analyse network latency trends for namespace team-alpha"
        tags:
          - cilium
          - networking
          - observability
```

## Prometheus Endpoint Requirement

- kube-prometheus-stack is already deployed on apps-dev.
- The promql-agent needs a `PROMETHEUS_URL` (or equivalent env/tool config) pointing at the
  in-cluster Prometheus service: `http://kube-prometheus-stack-prometheus.monitoring:9090`
- Verify connectivity from the agent pod before committing the URL.

## Acceptance Criteria

- [ ] `cilium-debug-agent` lists `observability-agent` and `promql-agent` in its tool set.
- [ ] A test prompt ("check Cilium node health and analyse any drop trends") produces a
      multi-step trace showing delegation to the downstream agents.
- [ ] No errors in agent pod logs related to A2A endpoint resolution.
