# Spec: kagent Integration

## Goal

Wire `k8s-agent` to route its Kubernetes tool calls through the MCP proxy (instead of
directly to `kagent-tools`), then validate the end-to-end OpenFGA-gated flow.

## Manifest change: k8s-agent.yaml

Add an explicit `tools` entry referencing the gated ToolServer:

```yaml
spec:
  declarative:
    modelConfig: claude-model-config
    systemMessage: |
      You are a Kubernetes expert assistant...
    tools:
      - type: McpServer
        mcpServer:
          name: k8s-tools-gated
          namespace: kagent-system
          toolNames:
            - k8s_get_resources
            - k8s_list_resources
            - k8s_delete_resource
            - k8s_apply_manifest
            # add others as confirmed from T1
```

**Note on duplicate tools:** The Helm chart auto-wires `kagent-tools` to all agents.
k8s-agent will see both the direct tools (auto-wired) and the gated proxy tools
(explicit). To make the demo unambiguous, attempt to disable the auto-wiring for
k8s-agent via HelmRelease values:

```yaml
# In kagent-release.yaml values, if supported:
agents:
  k8s-agent:
    toolServers: []   # disable auto-wiring for this agent
```

If HelmRelease values don't support per-agent tool server overrides, document the
ambiguity and proceed — the LLM will likely prefer the explicitly declared tools,
and the proxy will log all calls clearly.

## Validation scenario

### Pre-condition

OpenFGA bootstrap Job has run. `openfga-store` ConfigMap has `store_id`. Proxy pod
is Running. ToolServer `k8s-tools-gated` exists and points to proxy.

Pre-create a test ConfigMap:
```bash
kubectl create configmap test-delete-me -n default \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev
```

### Step 1 — Confirm read works (seeded tuple)

Send a read-only prompt to `k8s-agent`:
```
"List all ConfigMaps in the default namespace."
```
Expected: proxy logs OpenFGA check for `k8s_list_resources` → `{"allowed": true}` →
call forwarded → k8s-agent returns the list.

### Step 2 — Confirm delete is blocked (no tuple)

Send a destructive prompt:
```
"Delete the ConfigMap named 'test-delete-me' in the default namespace."
```
Expected: proxy logs OpenFGA check for `k8s_delete_resource` → `{"allowed": false}` →
MCP error returned → k8s-agent reports the operation was denied. ConfigMap still exists.

### Step 3 — Write tuple at runtime

```bash
# exec into any pod that can reach openfga, or port-forward
kubectl exec -n kagent-system deploy/openfga-mcp-proxy-k8s-agent \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev -- \
  curl -s -X POST http://openfga.openfga.svc.cluster.local:8080/stores/${STORE_ID}/write \
  -H 'Content-Type: application/json' \
  -d '{
    "writes": {
      "tuple_keys": [{
        "user": "agent:k8s-agent",
        "relation": "can_be_invoked_by",
        "object": "tool:k8s_delete_resource"
      }]
    }
  }'
```

No restart of any component.

### Step 4 — Confirm delete is now allowed (tuple exists)

Repeat the same delete prompt. Expected: proxy logs `{"allowed": true}` → call
forwarded → ConfigMap is deleted.

## Pass criteria

- Read-only tools pass through without error (seeded tuples).
- Delete is blocked before tuple write, allowed after — no restart required.
- Proxy logs clearly show the OpenFGA check result for each tool call.
- k8s-agent response reflects the policy decision (denied / succeeded).
