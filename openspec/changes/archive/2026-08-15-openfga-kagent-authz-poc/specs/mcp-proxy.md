# Spec: MCP Proxy

## Goal

A minimal MCP-protocol-aware proxy that sits between a kagent agent and the real
`kagent-tools` MCP server. For each tool call it receives, it calls OpenFGA `Check`
and either forwards the call upstream or returns an MCP error. Agent identity is
provided at deploy time via env var — one proxy instance per agent.

## Transport discovery (T1 — COMPLETED)

Confirmed from live cluster (apps-dev, 2026-08-08):

| Item | Confirmed value |
|------|----------------|
| Transport | **StreamableHttp** (NOT SSE) |
| Upstream endpoint | `http://kagent-tools.kagent-system:8084/mcp` |
| Session header | `Mcp-Session-Id` (returned by server on initialize, required on subsequent requests) |
| Total tools | 124 |
| HelmRelease subchart agents | All disabled (`enabled: false`) — no auto-wired duplicates from Helm |

**How tools reach agents:** The kagent controller maintains an internal `kagent-tool-server`
RemoteMCPServer that points at `kagent-tools.kagent-system:8084/mcp`. This is auto-wired
to all agents at runtime by the controller — it is NOT a user-managed ToolServer CR.

**k8s read-only tools (seeded as allowed in OpenFGA):**
`k8s_get_resources`, `k8s_describe_resource`, `k8s_get_events`, `k8s_get_pod_logs`,
`k8s_get_resource_yaml`, `k8s_get_available_api_resources`, `k8s_get_cluster_configuration`,
`k8s_check_service_connectivity`

**k8s destructive tools (blocked by default — no tuple seeded):**
`k8s_delete_resource`, `k8s_apply_manifest`, `k8s_create_resource`, `k8s_patch_resource`,
`k8s_execute_command`, `k8s_scale`, `k8s_rollout`, `shell`

**ToolServer config for StreamableHttp:**
```yaml
spec:
  config:
    streamableHttp:
      url: http://openfga-mcp-proxy.kagent-system.svc.cluster.local:8080/mcp
```

**Agent tool reference format (v1alpha2):**
```yaml
spec:
  declarative:
    tools:
      - type: McpServer
        mcpServer:
          name: k8s-tools-gated
```

## Service design

Language: Python. Transport implementation depends on T1 discovery.

```
apps/openfga-mcp-proxy/
  main.py
  Dockerfile
  requirements.txt    # fastapi, httpx, uvicorn, httpx-sse (if SSE needed)
```

### StreamableHttp variant (simpler — implement this if upstream uses StreamableHttp)

```python
@app.post("/mcp")
async def proxy_tool_call(request: Request):
    body = await request.json()
    tool_name = body.get("params", {}).get("name", "")

    if body.get("method") == "tools/call":
        allowed = await openfga_check(AGENT_ID, tool_name)
        if not allowed:
            return JSONResponse({"jsonrpc": "2.0", "id": body["id"],
                "error": {"code": -32603,
                          "message": f"tool '{tool_name}' denied by policy"}})

    resp = await client.post(UPSTREAM_MCP_URL, json=body)
    return JSONResponse(resp.json())
```

### SSE variant (if upstream uses SSE)

Maintain a per-session upstream SSE connection. On each `tools/call` message: run
OpenFGA check; if blocked send error event back on the inbound SSE stream; if allowed
forward the message to upstream SSE and relay the response event.

SSE is stateful — use `asyncio` with background tasks to bridge the two streams.
Prefer StreamableHttp if the upstream supports it.

## Environment variables

| Var | Value | Source |
|-----|-------|--------|
| `AGENT_ID` | `k8s-agent` | Deployment manifest (hardcoded per instance) |
| `OPENFGA_STORE_ID` | `<store_id>` | ConfigMap `openfga-store` via `envFrom` |
| `UPSTREAM_MCP_URL` | `http://kagent-tools.kagent-system.svc.cluster.local:<port>/sse` | Deployment manifest (confirmed in T1) |
| `OPENFGA_URL` | `http://openfga.openfga.svc.cluster.local:8080` | Deployment manifest |

## OpenFGA check helper

```python
async def openfga_check(agent_id: str, tool_name: str) -> bool:
    resp = await client.post(
        f"{OPENFGA_URL}/stores/{OPENFGA_STORE_ID}/check",
        json={"tuple_key": {
            "user": f"agent:{agent_id}",
            "relation": "can_be_invoked_by",
            "object": f"tool:{tool_name}"
        }}
    )
    return resp.json().get("allowed", False)
```

## Kubernetes manifests

All in `kubernetes/namespaces/base/kagent/kagent/config/mcp-proxy-deployment.yaml`:

**Deployment** `openfga-mcp-proxy-k8s-agent` in `kagent-system`:
- Image: `${REGION}-docker.pkg.dev/${PROJECT_ID}/platform/openfga-mcp-proxy:poc`
- `envFrom` the `openfga-store` ConfigMap; inline env for `AGENT_ID` and `UPSTREAM_MCP_URL`

**Service** `openfga-mcp-proxy-k8s-agent`, ClusterIP, port 8080

**ToolServer** `k8s-tools-gated` in `kagent-system`:
```yaml
apiVersion: kagent.dev/v1alpha1
kind: ToolServer
metadata:
  name: k8s-tools-gated
  namespace: kagent-system
spec:
  description: "k8s tools gated by OpenFGA policy"
  config:
    sse:
      url: http://openfga-mcp-proxy-k8s-agent.kagent-system.svc.cluster.local:8080/sse
```
Adjust `config` field to match transport confirmed in T1.

## Image build

```bash
docker build -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/platform/openfga-mcp-proxy:poc \
  apps/openfga-mcp-proxy/
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/platform/openfga-mcp-proxy:poc
```

## Pass criteria

- Proxy pod Running in `kagent-system`.
- Direct curl for `k8s_get_resources` tool call → forwarded (read-only tuple seeded).
- Direct curl for `k8s_delete_resource` → MCP error returned (no tuple).
- After writing the delete tuple, same call → forwarded to upstream.
