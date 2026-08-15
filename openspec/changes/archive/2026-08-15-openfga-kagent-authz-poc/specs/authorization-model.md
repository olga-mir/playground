# Spec: Authorization Model

## Goal

Define the OpenFGA type system and seed tuples that represent "which kagent agent may
invoke which tool". Start minimal — only what's needed for the POC validation scenario.

## Type system (OpenFGA DSL)

```
model
  schema 1.1

type agent

type tool
  relations
    define can_be_invoked_by: [agent]
```

Deliberately minimal: one relation, two types. Namespace-scoping is out of scope for
this POC (handled by kagent `allowedNamespaces`).

Serialised to JSON for the API call:

```json
{
  "schema_version": "1.1",
  "type_definitions": [
    { "type": "agent" },
    {
      "type": "tool",
      "relations": {
        "can_be_invoked_by": {
          "this": {},
          "union": {
            "child": [{ "this": {} }]
          }
        }
      },
      "metadata": {
        "relations": {
          "can_be_invoked_by": { "directly_related_user_types": [{ "type": "agent" }] }
        }
      }
    }
  ]
}
```

## Initial tuples (seeded by bootstrap Job)

| Agent | Relation | Tool | Meaning |
|-------|----------|------|---------|
| `agent:k8s-agent` | `can_be_invoked_by` | `tool:k8s_get_resources` | allowed — read-only |
| `agent:k8s-agent` | `can_be_invoked_by` | `tool:k8s_list_resources` | allowed — read-only |

**Not seeded initially (blocked by default):**

| Tool | Meaning |
|------|---------|
| `tool:k8s_delete_resource` | destructive — requires explicit tuple to allow |
| `tool:k8s_apply_resource` | mutating — requires explicit tuple to allow |

## Check call (used by approval webhook)

```
POST /stores/{store_id}/check
{
  "tuple_key": {
    "user": "agent:k8s-agent",
    "relation": "can_be_invoked_by",
    "object": "tool:k8s_delete_resource"
  }
}
```

Response: `{"allowed": false}` → webhook returns reject.

## Runtime tuple write (validation step)

```bash
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

After this write, the same `check` call returns `{"allowed": true}` — no restart needed.

## Agent and tool identifier convention

- Agent IDs: `agent:<agent-name>` using the kagent Agent CR `.metadata.name`
  (e.g. `agent:k8s-agent`, `agent:crossplane-composition-fixer`)
- Tool IDs: `tool:<tool-name>` using the MCP tool name as reported in kagent logs
  (exact names to be confirmed from live cluster — see tasks)
