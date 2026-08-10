# Proposal: k8s-troubleshooter

## Summary

Build a purpose-built Kubernetes troubleshooter kagent Agent backed by a custom Python
MCP server. The MCP server exposes semantic diagnostic tools (e.g. `diagnose_namespace`,
`get_pod_failure_context`) that aggregate multiple Kubernetes API calls into a single
correlated result, rather than exposing raw kubectl primitives. OpenFGA authorization is
embedded directly in the MCP server's tool handlers, scoped to namespace-level access.
This eliminates the proxy bypass gap encountered with OOTB `kagent-tools` and demonstrates
the clean OpenFGA integration pattern for custom tooling.

## Problem

The OOTB `kagent-tools` MCP server exposes ~80 primitive tools (`k8s_get_resources`,
`k8s_get_events`, `k8s_describe_resource`, etc.). Using them for a diagnostic workflow
requires the agent to reason through multi-step sequences, resulting in many LLM
round-trips, high token usage, and fragile sequencing (the LLM may forget to check
events, or check the wrong node).

Authorizing at the primitive level is also too coarse: "can agent X call
`k8s_get_resources`?" cannot express "agent X may diagnose namespace Y but not namespace Z."

Enforcing OpenFGA on OOTB `kagent-tools` requires an intercepting proxy, which introduces
a bypass gap: the kagent Helm chart auto-wires the unproxied path (`RemoteMCPServer/
kagent-tool-server`) to all agents regardless of explicit tool declarations in the Agent
CR. The proxy can only gate the path it sits on.

## Proposed Solution

A custom MCP server (`apps/k8s-troubleshooter-mcp/`) written in Python (FastAPI +
MCP SDK) exposing 3–4 semantic diagnostic tools:

- `diagnose_namespace(namespace)` — pod status, recent events, resource pressure,
  failing containers; all collected in parallel and returned as a single structured report
- `get_pod_failure_context(namespace, pod)` — logs, describe output, and events for
  one specific pod correlated into a single response
- `get_namespace_resource_pressure(namespace)` — node pressure, ResourceQuota usage,
  LimitRange constraints

The MCP server:
- Calls the Kubernetes API directly via the in-cluster service account (no kubectl, no
  shelling out)
- Checks OpenFGA before executing each tool: `agent:{id} can_diagnose namespace:{ns}`
- Returns structured, correlated output ready for the LLM to reason over in one step

Deployed as a `ToolServer` CR + `Agent` CR in `team-alpha`. The agent is a standard
kagent Agent CR — the only difference from OOTB agents is that its declared tool server
points to the custom MCP server instead of `kagent-tool-server`.

## Capabilities Affected

- `apps/k8s-troubleshooter-mcp/` — new Python MCP server (FastAPI, kubernetes client,
  OpenFGA client)
- `kubernetes/namespaces/base/team-alpha/troubleshooter/` — ToolServer, Agent CR,
  ServiceAccount, RBAC (ClusterRole scoped to get/list on pods, events, nodes)
- OpenFGA authorization model — extend the existing `kagent-authz` store with
  namespace-scoped `can_diagnose` tuples

## Impact & Risks

**Benefits:**
- Demonstrates the clean OpenFGA pattern: check-inside-the-server, no proxy needed,
  no bypass gap
- Proves semantic aggregation reduces agent round-trips (1 tool call vs 4–5 primitives)
- Namespace-scoped authorization is the right granularity for multi-tenant clusters

**Risks:**
- Kubernetes API calls from within the cluster require correct RBAC; an over-broad
  ClusterRole (e.g. cluster-admin) defeats the security purpose — must be deliberately
  narrow
- The OpenFGA store from the `openfga-kagent-authz-poc` change must be available; hard
  dependency on that deployment being in place
- The MCP server is not authenticated (no mTLS, no token validation on the `/mcp`
  endpoint) — acceptable for a POC within the cluster, not for production

## Out of Scope

- Write or mutate operations (no apply, delete, patch, exec)
- Multi-cluster or cross-cluster diagnostics
- Productionising the MCP server (TLS, rate limiting, proper auth on the MCP endpoint)
- Replacing or modifying OOTB `kagent-tools`
- A2A delegation from this agent to other agents
