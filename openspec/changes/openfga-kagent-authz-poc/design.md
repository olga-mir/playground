# Design: openfga-kagent-authz-poc

## Architecture

```
operator prompt
  │
  ▼
k8s-agent (kagent-system)
  │  tool call: k8s_delete_resource
  │  requireApproval triggers
  │
  ▼
openfga-approval-webhook (kagent-system, ClusterIP :8080)
  │  POST /approve  {agent_name, tool_name}
  │
  ▼
OpenFGA (openfga namespace, ClusterIP :8080)
  │  POST /stores/{id}/check
  │  tuple_key: {user: "agent:k8s-agent", relation: "can_be_invoked_by", object: "tool:k8s_delete_resource"}
  │
  ▼  {"allowed": true/false}
  │
openfga-approval-webhook
  │  {"approved": true/false}
  │
k8s-agent
  │  proceed / block
```

## Component responsibilities

| Component | Responsibility |
|-----------|---------------|
| **OpenFGA** | Stores type model and tuples; answers `check` queries |
| **Bootstrap Job** | Creates store, writes model, seeds initial read-only tuples (runs once) |
| **openfga-approval-webhook** | Translates kagent callback → OpenFGA check → approve/reject |
| **k8s-agent manifest** | Lists destructive tools in `requireApproval`; points to webhook URL |
| **openfga-store ConfigMap** | Passes store ID from bootstrap Job to webhook at runtime |

## Sequence: bootstrap

```
HelmRelease openfga Ready
  └─ Job: openfga-bootstrap
       ├─ POST /stores                        → store_id
       ├─ POST /stores/{id}/authorization-models  → model_id
       ├─ POST /stores/{id}/write  (read-only tuples)
       └─ kubectl create configmap openfga-store --from-literal=store_id=...
```

## Sequence: tool call (blocked)

```
kagent receives prompt → LLM decides to call k8s_delete_resource
  → requireApproval: POST webhook /approve {agent_name: "k8s-agent", tool_name: "k8s_delete_resource"}
    → webhook: POST openfga /check {user: "agent:k8s-agent", relation: "can_be_invoked_by", object: "tool:k8s_delete_resource"}
      ← {"allowed": false}
    ← {"approved": false}
  → kagent: tool call denied, reports to operator
```

## Sequence: runtime tuple write + retry

```
operator: curl POST /stores/{id}/write  (grant delete tuple)
  → {"writes": {"tuple_keys": [...]}}   ← {"code": "no error"}

operator re-sends prompt
  → requireApproval: POST webhook /approve
    → openfga /check  ← {"allowed": true}
    ← {"approved": true}
  → kagent proceeds with k8s_delete_resource
```

## Key unknowns (resolved during implementation)

1. `requireApproval` field schema in kagent v1alpha2 CRD — field name, nesting, endpoint config.
2. kagent approval callback payload — exact JSON fields for agent and tool identity.
3. kagent approval response schema — what it expects back.
4. MCP tool names — exact strings as registered (e.g. `k8s_delete_resource` vs `DeleteResource`).

All four are discoverable from the live cluster before writing the webhook.

## Image registry

Use the existing Artifact Registry in the project:
`${REGION}-docker.pkg.dev/${PROJECT_ID}/platform/openfga-approval-webhook:poc`

No new registry provisioning needed.
