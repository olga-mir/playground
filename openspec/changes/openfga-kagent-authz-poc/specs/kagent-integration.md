# Spec: kagent Integration

## Goal

Wire `k8s-agent` to use the approval webhook for destructive tool calls by adding
`requireApproval` to the agent manifest, and validate the end-to-end flow.

## Manifest change: k8s-agent.yaml

Add `requireApproval` to the `spec.declarative` block:

```yaml
spec:
  declarative:
    modelConfig: claude-model-config
    systemMessage: |
      You are a Kubernetes expert assistant...
    requireApproval:
      tools:
        - k8s_delete_resource
        - k8s_apply_resource
      approvalEndpoint: http://openfga-approval-webhook.kagent-system.svc.cluster.local:8080/approve
    tools:
      - type: Agent
        ...
```

**Note:** The exact `requireApproval` field name and schema must be confirmed against the
installed CRD version (v1alpha2). If the field name or nesting differs, adjust accordingly.

## Validation scenario

### Step 1 — Confirm deletion is blocked (no tuple)

Send a prompt to `k8s-agent` that triggers `k8s_delete_resource`:

```
"Delete the ConfigMap named 'test-delete-me' in the default namespace."
```

Pre-create the ConfigMap:

```bash
kubectl create configmap test-delete-me -n default \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev
```

Expected: kagent calls the webhook → webhook calls OpenFGA `check` for
`tool:k8s_delete_resource` → `{"allowed": false}` → webhook returns reject → kagent
reports the tool call was denied. ConfigMap still exists after the attempt.

### Step 2 — Write tuple at runtime

```bash
# Port-forward or exec into a pod with curl access to OpenFGA
curl -X POST http://openfga.openfga.svc.cluster.local:8080/stores/${STORE_ID}/write \
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

### Step 3 — Confirm deletion is now allowed (tuple exists)

Repeat the same prompt. Expected: webhook returns approve → kagent proceeds → ConfigMap
is deleted.

## Pass criteria

- Tool call is blocked before tuple write, allowed after — no restart required.
- The approval webhook log shows the OpenFGA `Check` call and its result for both cases.
- kagent agent log shows "tool call denied" / "tool call approved" (or equivalent).
