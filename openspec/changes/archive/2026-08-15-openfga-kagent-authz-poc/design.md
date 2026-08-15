# Design: openfga-kagent-authz-poc

## Architecture

```
operator prompt
  │
  ▼
k8s-agent (kagent-system)
  │  MCP tool call: k8s_delete_resource
  │  (via ToolServer "k8s-tools-gated")
  │
  ▼
openfga-mcp-proxy-k8s-agent (kagent-system, ClusterIP :8080)
  │  env: AGENT_ID=k8s-agent
  │  env: UPSTREAM_MCP_URL=http://kagent-tools.kagent-system.svc.../sse
  │
  ├─► OpenFGA (openfga namespace, ClusterIP :8080)
  │     POST /stores/{id}/check
  │     {"user": "agent:k8s-agent", "relation": "can_be_invoked_by", "object": "tool:k8s_delete_resource"}
  │     ← {"allowed": false}   →  return MCP error to k8s-agent
  │     ← {"allowed": true}    →  forward to upstream
  │
  ▼  (when allowed)
kagent-tools MCP server (kagent-system)
  │  executes k8s_delete_resource
  └─► Kubernetes API
```

## Component responsibilities

| Component | Responsibility |
|-----------|---------------|
| **OpenFGA** | Stores type model and tuples; answers `check` queries |
| **Bootstrap Job** | Creates store, writes model, seeds initial read-only tuples; writes store_id to ConfigMap |
| **openfga-mcp-proxy-k8s-agent** | Intercepts MCP tool calls from k8s-agent; calls OpenFGA; forwards or rejects |
| **ToolServer `k8s-tools-gated`** | Kubernetes CR pointing k8s-agent at the proxy instead of kagent-tools directly |
| **k8s-agent manifest** | References `k8s-tools-gated` ToolServer in its tools list |
| **openfga-store ConfigMap** | Passes store ID from bootstrap Job to proxy at runtime |

## Sequence: bootstrap

```
HelmRelease openfga → Ready
  └─ Job: openfga-bootstrap
       ├─ POST /stores                             → store_id
       ├─ POST /stores/{id}/authorization-models   → model_id
       ├─ POST /stores/{id}/write  (read-only tuples: k8s_get_resources, k8s_list_resources)
       └─ kubectl patch configmap openfga-store --from-literal=store_id=...
              (ConfigMap pre-created by the Flux Kustomization; Job populates it)
```

## Sequence: tool call blocked (no tuple)

```
k8s-agent: LLM decides to call k8s_delete_resource
  → MCP tool call → openfga-mcp-proxy-k8s-agent
    → POST openfga /check
      tuple: {user: "agent:k8s-agent", relation: "can_be_invoked_by", object: "tool:k8s_delete_resource"}
      ← {"allowed": false}
    ← MCP error: {"error": {"code": -32603, "message": "tool invocation denied by policy"}}
  ← k8s-agent reports to operator: tool call was denied
```

## Sequence: runtime tuple write + retry (no restart)

```
operator: kubectl exec ... -- curl POST /stores/{id}/write
  → {"writes": {"tuple_keys": [{"user":"agent:k8s-agent","relation":"can_be_invoked_by","object":"tool:k8s_delete_resource"}]}}
  ← {"code": "no_error"}

operator re-sends same prompt to k8s-agent
  → MCP tool call → proxy
    → POST openfga /check  ← {"allowed": true}
    → forward to kagent-tools upstream
    ← tool result: resource deleted
  ← k8s-agent reports success
```

## MCP transport

The proxy must speak the same MCP transport as kagent-tools. Confirm from live cluster:

```bash
kubectl get svc -n kagent-system --show-labels | grep -i kagent-tools
kubectl get toolserver -n kagent-system -o yaml | grep -i url
```

Likely SSE (`GET /sse` + `POST /messages?sessionId=...`) or StreamableHttp (single
`POST /mcp` per call). StreamableHttp is simpler to proxy; SSE requires maintaining a
bidirectional stream.

If StreamableHttp: proxy is a simple `POST /mcp` handler — check OpenFGA, forward request
body to upstream, return upstream response or error.

If SSE: proxy maintains per-session upstream SSE connections; forwards messages after the
OpenFGA check on each tool call message.

## Key unknowns (resolved during T1 on live cluster)

1. MCP transport protocol used by `kagent-tools` (SSE vs StreamableHttp).
2. Exact MCP tool names as registered (e.g. `k8s_delete_resource` vs `DeleteResource`).
3. Whether HelmRelease values can disable the direct kagent-tools wiring for k8s-agent
   specifically (to avoid duplicate tool entries).
4. The service name and port for `kagent-tools` in `kagent-system`.

## Image registry

`${REGION}-docker.pkg.dev/${PROJECT_ID}/platform/openfga-mcp-proxy:poc`

No new registry provisioning needed.
