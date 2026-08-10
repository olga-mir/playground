# Design: k8s-troubleshooter

## Approach

Embed authorization inside the MCP server's tool handlers rather than intercepting via a
proxy. Each tool call: (1) resolves agent identity from an env var, (2) calls OpenFGA
`/check`, (3) only proceeds to Kubernetes API if allowed. This eliminates the bypass gap
that exists when the proxy sits on a separate path — there is no unproxied path to exploit.

The MCP server is a new Python application (`FastAPI` + `mcp` SDK) deployed as a
`Deployment` + `Service` in `team-alpha`. A kagent `ToolServer` CR points at it. The
kagent `Agent` CR references only this `ToolServer`, not `kagent-tool-server`.

The OpenFGA store from `openfga-kagent-authz-poc` is reused; the authorization model is
extended with a new `namespace` object type and `can_diagnose` relation.

## Architecture

```
operator prompt
  │
  ▼
k8s-troubleshooter-agent  (team-alpha, kagent Agent CR)
  │  MCP tool call: diagnose_namespace / get_pod_failure_context / get_namespace_resource_pressure
  │  ToolServer: k8s-troubleshooter  →  http://k8s-troubleshooter-mcp.team-alpha.svc:8080/mcp
  │
  ▼
k8s-troubleshooter-mcp  (team-alpha, Deployment/Service)
  │  env: AGENT_ID=k8s-troubleshooter-agent
  │  env: OPENFGA_HOST, OPENFGA_STORE_ID  (from openfga-store ConfigMap)
  │
  ├─► OpenFGA  (openfga namespace, :8080)
  │     POST /stores/{id}/check
  │     {"user": "agent:k8s-troubleshooter-agent", "relation": "can_diagnose", "object": "namespace:team-alpha"}
  │     ← {"allowed": false}  →  return MCP error; no k8s calls made
  │     ← {"allowed": true}   →  proceed
  │
  ▼  (when allowed)
Kubernetes API  (in-cluster, via ServiceAccount troubleshooter-mcp)
  │  ClusterRole: get/list on pods, events, nodes, resourcequotas, limitranges
  └─► returns aggregated diagnostic result to agent
```

## Key Decisions

### Decision: Check-inside-server vs proxy

- **Options considered:** (a) extend existing openfga-mcp-proxy to cover the new tools;
  (b) write authorization checks directly inside the new MCP server's tool handlers
- **Chosen:** (b) in-server checks
- **Rationale:** The proxy approach demonstrated in `openfga-kagent-authz-poc` has a
  structural bypass gap: kagent auto-wires `kagent-tool-server` to all agents regardless
  of the Agent CR's tool declarations. The proxy can only gate the path it controls.
  With a fully custom MCP server, there is no unproxied path — the check is inseparable
  from the tool execution.

### Decision: Agent identity via env var (POC simplification)

- **Options considered:** (a) SPIFFE/SVID minted per pod; (b) signed JWT in MCP request
  metadata; (c) fixed env var per deployment
- **Chosen:** (c) fixed `AGENT_ID` env var in the MCP server `Deployment`
- **Rationale:** kagent does not currently inject caller identity into MCP requests. For
  a POC with a single-agent deployment this is acceptable — the server is bound to one
  agent by construction. Production would use SPIFFE/SVID or signed JWT.

### Decision: OpenFGA model extension (additive, not replacement)

- **Options considered:** (a) write a new store; (b) extend the existing `kagent-authz`
  store's model with the new `namespace` type
- **Chosen:** (b) extend existing store
- **Rationale:** Keeps all kagent authorization in a single store; simpler operational
  model. The existing `tool` type and `can_be_invoked_by` relation are unchanged.

### Decision: Parallel Kubernetes API calls within each tool

- **Options considered:** (a) sequential calls; (b) `asyncio.gather` for concurrent calls
- **Chosen:** (b) concurrent via `asyncio.gather`
- **Rationale:** `diagnose_namespace` aggregates 3–4 independent API calls (pods, events,
  resource quotas, node pressure). Sequential calls add unnecessary latency visible to the
  LLM. The kubernetes-asyncio client supports this natively.

### Decision: MCP transport — StreamableHttp

- **Options considered:** SSE (`GET /sse` + `POST /messages`), StreamableHttp (`POST /mcp`)
- **Chosen:** StreamableHttp
- **Rationale:** The existing cluster uses StreamableHttp (confirmed during
  `openfga-kagent-authz-poc` T1). The `mcp` Python SDK's `FastMCP` class supports it
  with `transport="streamable-http"`. Simpler than maintaining SSE session state.

### Decision: Tuple seeding via Kubernetes Job (not init container)

- **Options considered:** (a) init container in the MCP server Deployment; (b) standalone Job
- **Chosen:** (b) standalone `Job` with `restartPolicy: OnFailure`
- **Rationale:** Consistent with the pattern used in `openfga-kagent-authz-poc`
  (`openfga-bootstrap` Job). Jobs are independently observable via `kubectl get jobs`.
  An init container would block the server from starting if OpenFGA is transiently unavailable.

## Implementation Notes

- **OpenFGA store ID**: read from the `openfga-store` ConfigMap (key `store_id`) already
  populated by the `openfga-kagent-authz-poc` bootstrap Job. The troubleshooter Job and
  MCP server both mount this ConfigMap as an env var.
- **Model update**: the OpenFGA authorization model must be rewritten (OpenFGA replaces
  the whole model on write, not patched). The new model must include the existing `tool`
  type and `can_be_invoked_by` relation alongside the new `namespace` type and
  `can_diagnose` relation.
- **Namespace for the MCP server**: `team-alpha`. This means the Kubernetes Service is
  `k8s-troubleshooter-mcp.team-alpha.svc.cluster.local`. The `ToolServer` CR and `Agent`
  CR must also live in `team-alpha`.
- **RBAC scope**: `ClusterRole` (not `Role`) because the server reads node resources
  which are cluster-scoped. The `ClusterRoleBinding` restricts the subject to the
  `troubleshooter-mcp` ServiceAccount in `team-alpha`.
- **Fail-closed on OpenFGA error**: if the HTTP call to OpenFGA returns a non-200 or
  times out, the tool handler must return a MCP error — never proceed to Kubernetes API.
  Use a short timeout (2s) to avoid blocking the agent on an unavailable authz service.
- **Image registry**: `${REGION}-docker.pkg.dev/${PROJECT_ID}/platform/k8s-troubleshooter-mcp:latest`
  — consistent with the pattern used for `openfga-mcp-proxy`. Flux `ImageRepository` +
  `ImagePolicy` manage tag automation.
- **Ordering**: the troubleshooter `Deployment` depends on the `openfga-store` ConfigMap
  being populated. Add a `dependsOn` reference to the `openfga-kagent-authz-poc`
  kustomization in the Flux `Kustomization` CR, or use an init container that waits for
  the ConfigMap key to be non-empty.

## File layout

```
apps/k8s-troubleshooter-mcp/
  Dockerfile
  pyproject.toml
  src/
    server.py          # FastMCP app, tool registrations
    k8s_client.py      # Kubernetes API wrappers (asyncio)
    authz.py           # OpenFGA check helper (fail-closed)
    tools/
      diagnose_namespace.py
      get_pod_failure_context.py
      get_namespace_resource_pressure.py

kubernetes/namespaces/base/team-alpha/troubleshooter/
  kustomization.yaml
  namespace.yaml          # team-alpha (if not already present)
  serviceaccount.yaml     # troubleshooter-mcp SA
  clusterrole.yaml        # read-only on pods/events/nodes/resourcequotas/limitranges
  clusterrolebinding.yaml
  deployment.yaml         # k8s-troubleshooter-mcp
  service.yaml            # ClusterIP :8080
  toolserver.yaml         # kagent ToolServer CR
  agent.yaml              # kagent Agent CR
  openfga-model-job.yaml  # Job: update OpenFGA model + seed can_diagnose tuple
  imagepolicy.yaml
  imagerepository.yaml
```

## Testing Strategy

1. **OpenFGA check blocks unauthorized namespaces**: call `diagnose_namespace("kube-system")`
   via the agent — confirm the tool returns a 403 MCP error with no Kubernetes API calls.
2. **OpenFGA check allows team-alpha**: call `diagnose_namespace("team-alpha")` — confirm
   a structured diagnostic result is returned.
3. **ToolServer Ready**: `kubectl get toolserver k8s-troubleshooter -n team-alpha` shows
   `Ready` and lists the three tools.
4. **RBAC enforcement**: exec into the MCP server pod and confirm `kubectl auth can-i`
   returns "no" for write verbs and "yes" for get/list on the permitted resources.
5. **Fail-closed**: temporarily break the `OPENFGA_HOST` env var and confirm all tool
   calls return errors rather than bypassing the check.
