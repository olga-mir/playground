# Spec: MCP Proxy

## Goal

A minimal MCP-protocol-aware proxy that sits between a kagent agent and the real
`kagent-tools` MCP server. For each tool call it receives, it calls OpenFGA `Check`
and either forwards the call upstream or returns an MCP error. Agent identity is
provided at deploy time via env var — one proxy instance per agent.

## Transport discovery (T1 prerequisite)

Before implementing, confirm the transport protocol from the live cluster:

```bash
# Find kagent-tools service
kubectl get svc -n kagent-system --context gke_${PROJECT_ID}_${REGION}-a_apps-dev \
  | grep -i tool

# Inspect the auto-created ToolServer to find URL and transport
kubectl get toolservers -n kagent-system -o yaml \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev

# Confirm exact registered tool names from kagent-tools pod logs
TOOLS_POD=$(kubectl get pod -n kagent-system -l app=kagent-tools \
  -o jsonpath='{.items[0].metadata.name}' \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev)
kubectl logs "$TOOLS_POD" -n kagent-system \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev | grep -i "register\|tool\|k8s_"
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
