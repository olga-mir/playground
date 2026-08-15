# kagent Multi-Agent Orchestration & OpenFGA Authorization

## TL;DR — how this achieves the result

kagent agents are declared as standalone `Agent` CRs (not Helm sub-charts) so their wiring
is fully visible in git. Agents can call other agents as tools (**A2A delegation**), and by
default a `kagent.dev/v1alpha2` Agent can only be called by agents in its own namespace
(`allowedNamespaces: {from: Same}`) — cross-team calls are rejected at reconcile time, before
the agent ever starts.

That static, coarse-grained boundary is not enough to express "agent X may call tool Y but
not tool Z" or "agent X may diagnose namespace A but not namespace B." **OpenFGA** replaces
that gap with a policy engine that answers `check(agent, relation, object)` at call time, and
tuples can be added or removed live — no manifest change, no restart. Two independent proof
points demonstrate this on the live apps-dev cluster:

1. **MCP proxy in front of the stock `kagent-tools` server** ([issue #103](../../issues/103)) — an
   `openfga-mcp-proxy` sits between `k8s-agent` and the ~80 raw `k8s_*` tools kagent ships
   out of the box. Every `tools/call` is checked against OpenFGA before being forwarded.
   **Fully validated end-to-end**, see [Testing walkthrough](#testing-walkthrough-1-proxy-gated-k8s-agent) below.
2. **A custom semantic MCP server with authz baked in** (`k8s-troubleshooter-mcp`) — instead
   of proxying raw primitives, this server exposes 3 aggregated diagnostic tools
   (`diagnose_namespace`, `get_pod_failure_context`, `get_namespace_resource_pressure`) and
   checks OpenFGA itself, scoped to `namespace:<ns>` rather than `tool:<name>`. Avoids the
   proxy-bypass gap (see [Why two arms](#why-two-arms)). **Deployed and Ready; the read/deny/RBAC
   test scenarios are not yet run** — see [Status](#status).

---

## Architecture

### A2A delegation baseline

Agents declare other agents as tools:

```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: cilium-network-agent
  namespace: kagent-system
spec:
  declarative:
    tools:
      - type: Agent
        agent:
          name: observability-agent
          namespace: kagent-system
    a2aConfig:
      skills:
        - id: cilium-network-debug
          description: Diagnose Cilium issues; delegates metric analysis
```

Cross-namespace calls require the **target** to opt in:

```yaml
spec:
  allowedNamespaces:
    from: All        # or: Same (default) | Selector
```

Enforcement is at **admission/reconcile time**: a tenant agent referencing a target that
hasn't opted in never reaches `Accepted: True` — it fails fast and visibly rather than
failing silently on the first call. Validated on live cluster 2026-08-08 (see
`openspec/changes/archive/2026-08-08-kagent-runtime-validation/`): `crossplane-composition-fixer`
(team-charlie) → `k8s-agent` (kagent-system) succeeds because `k8s-agent` sets
`allowedNamespaces: {from: All}`; a same-shape reference from team-charlie to a `team-alpha`
stub agent (no opt-in) was rejected by the controller with
`cross-namespace reference to agent team-alpha/stub-agent is not allowed from namespace team-charlie`.

### OpenFGA arm 1 — MCP proxy gating `k8s-agent`

```
operator prompt
  │
  ▼
k8s-agent (kagent-system)
  │  MCP tool call: k8s_delete_resource
  │  via RemoteMCPServer "k8s-tools-gated"
  ▼
openfga-mcp-proxy (kagent-system, :8080/mcp)
  │  env: AGENT_ID=k8s-agent, UPSTREAM_MCP_URL=http://kagent-tools.kagent-system:8084/mcp
  ├─► OpenFGA (openfga ns, :8080)
  │     POST /stores/{id}/check
  │     {"user":"agent:k8s-agent","relation":"can_be_invoked_by","object":"tool:k8s_delete_resource"}
  │     ← {"allowed": false} → proxy returns MCP error, never calls upstream
  │     ← {"allowed": true}  → proxy forwards to upstream
  ▼ (when allowed)
kagent-tools MCP server → Kubernetes API
```

The proxy creates its own OpenFGA store (`kagent-authz`), model, and read-only tuples
(`k8s_get_resources`, `k8s_describe_resource`, `k8s_get_events`, ...) on startup — because
OpenFGA runs with the `memory` datastore (ephemeral, POC-only), this happens on every proxy
restart too.

Key manifests:
- `kubernetes/namespaces/base/openfga/` — OpenFGA HelmRelease (memory datastore)
- `kubernetes/namespaces/base/kagent/kagent/config/mcp-proxy-deployment.yaml` — proxy Deployment/Service + `RemoteMCPServer` CR `k8s-tools-gated`
- `kubernetes/namespaces/base/kagent/kagent/config/k8s-agent.yaml` — `k8s-agent` referencing `k8s-tools-gated` as its only tool server
- `apps/openfga-mcp-proxy/main.py` — the proxy itself

### OpenFGA arm 2 — semantic MCP server with baked-in authz

```
k8s-troubleshooter-agent (team-alpha)
  │ diagnose_namespace("team-alpha")
  ▼
k8s-troubleshooter-mcp (team-alpha, :8080/mcp)
  │ authz.check(AGENT_ID, "can_diagnose", f"namespace:{namespace}")
  ├─► OpenFGA check → allowed/denied
  ▼ (when allowed)
Kubernetes API (in-cluster SA, get/list only — pods, events, nodes, quotas, limitranges)
```

### Why two arms?

Arm 1 (proxy) has a structural gap: kagent's Helm chart auto-wires the unproxied
`kagent-tool-server` `RemoteMCPServer` to agents regardless of what's explicitly declared in
the Agent CR — the proxy can only gate the path traffic actually takes through it, not a
parallel unproxied path if one exists. Arm 2 sidesteps this entirely: there is no unproxied
version of `k8s-troubleshooter-mcp`, and authorization is baked into the tool handler itself,
scoped to a more useful `namespace:<ns>` object rather than `tool:<name>` — "agent X may
diagnose namespace A" is expressible; "agent X may call k8s_get_resources" is not fine-grained
enough for a real multi-tenant policy.

Key manifests: `kubernetes/namespaces/base/team-alpha/troubleshooter/` (`agent.yaml`,
`toolserver.yaml`, `deployment.yaml`, `rbac.yaml`, `openfga-model-job.yaml`), `apps/k8s-troubleshooter-mcp/`.

---

## Status

| Arm | Deploy | End-to-end validated |
|---|---|---|
| A2A delegation + namespace isolation baseline | ✅ | ✅ (2026-08-08, see archived change) |
| Arm 1 — MCP proxy gating `k8s-agent` | ✅ | ✅ (2026-08-15, see [issue #103](../../issues/103) comment) |
| Arm 2 — `k8s-troubleshooter-mcp` semantic authz | ✅ (agent Ready, tools registered) | ❌ — read/deny/fail-closed/RBAC scenarios not yet run (`openspec/changes/k8s-troubleshooter/tasks.md`, Testing phase) |

`openspec/changes/openfga-kagent-authz-poc/` is fully complete and ready to archive
(`openspec archive openfga-kagent-authz-poc` or the `opsx-archive` skill).
`openspec/changes/k8s-troubleshooter/` should stay active until its Testing phase tasks are run.

---

## Testing walkthrough: 1. Proxy-gated k8s-agent

Everything below was run against the live apps-dev cluster on 2026-08-15 and is captured
verbatim in the [issue #103 comment](../../issues/103).

### 1. Port-forward the proxy

```bash
task port-forward:openfga-proxy   # localhost:8090 -> openfga-mcp-proxy:8080
```

### 2. Establish an MCP session

The streamable-http `/mcp` endpoint requires a session handshake — a bare `tools/call`
without first calling `initialize` gets a 500 from the proxy (the upstream `kagent-tools`
server rejects the missing session):

```bash
curl -s -i -X POST http://localhost:8090/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoketest","version":"1.0"}}}'
# → response header: mcp-session-id: proxy-<uuid>

SID="proxy-<uuid-from-above>"
curl -s -X POST http://localhost:8090/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
```

### 3. Read-only call passes through (seeded tuple)

```bash
curl -s -X POST http://localhost:8090/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"k8s_get_resources","arguments":{"resource_type":"pods","namespace":"kagent-system"}}}'
# → 200 OK, live pod list
```

Proxy log: `{"event":"authz","agent":"k8s-agent","tool":"k8s_get_resources","allowed":true}`

### 4. Destructive call blocked (no tuple)

```bash
curl -s -X POST http://localhost:8090/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"k8s_delete_resource","arguments":{}}}'
# → {"error":{"code":-32603,"message":"tool 'k8s_delete_resource' denied by OpenFGA policy for agent 'k8s-agent'"}}
```

### 5. Grant the tuple at runtime — no restart

```bash
kubectl port-forward -n openfga svc/openfga 8091:8080 --context <apps-dev-context>

STORE_ID=$(curl -s http://localhost:8090/health | jq -r .store_id)
curl -s -X POST http://localhost:8091/stores/$STORE_ID/write \
  -H 'Content-Type: application/json' \
  -d '{"writes":{"tuple_keys":[{"user":"agent:k8s-agent","relation":"can_be_invoked_by","object":"tool:k8s_delete_resource"}]}}'
```

Repeat the step 4 request — it now succeeds. Proxy log:
`{"event":"authz","agent":"k8s-agent","tool":"k8s_delete_resource","allowed":true}`

---

## Testing walkthrough: 2. Semantic authz arm (k8s-troubleshooter) — not yet run

These scenarios are defined in `openspec/changes/k8s-troubleshooter/tasks.md` (Testing
phase) but have not been executed yet:

```bash
CTX=gke_${PROJECT_ID}_${REGION}-a_apps-dev

# ToolServer ready, three tools registered
kubectl get remotemcpserver k8s-troubleshooter -n team-alpha --context $CTX

# Authorized namespace — expect a structured diagnostic result
# (send a prompt to k8s-troubleshooter-agent asking to diagnose_namespace("team-alpha"))

# Unauthorized namespace — expect an MCP error / 403, no k8s API calls logged
# (same, but diagnose_namespace("kube-system"))

# Fail-closed — patch OPENFGA_URL to something invalid, confirm all three tools error, then revert

# RBAC — exec into the pod and confirm the ServiceAccount can list pods but cannot delete them
kubectl exec -it deploy/k8s-troubleshooter-mcp -n team-alpha --context $CTX -- \
  kubectl auth can-i list pods   --as system:serviceaccount:team-alpha:troubleshooter-mcp
kubectl exec -it deploy/k8s-troubleshooter-mcp -n team-alpha --context $CTX -- \
  kubectl auth can-i delete pods --as system:serviceaccount:team-alpha:troubleshooter-mcp
```

---

## Common pitfalls hit standing this up

- **`tools[].mcpServer.kind` must be explicit.** Left unset, the v1alpha2 Agent controller
  defaults to `kind: MCPServer` (a v1alpha1 CRD, unused here) and fails with
  `"MCPServer ... not found"`. The working kind is **`RemoteMCPServer`** (kagent.dev/v1alpha2)
  — not `ToolServer` (v1alpha1; the controller rejects it with `"unknown tool server type: ToolServer"`).
- **MCP streamable-http `/mcp` returns 406 to a plain `GET`** — don't use `httpGet` liveness/
  readiness probes against it, use `tcpSocket`.
- **`python foo/server.py` vs `python -m foo.server`** — running a package entrypoint as a
  bare script breaks its own internal `from foo.x import y` imports (`ModuleNotFoundError`).
- **`kagent-anthropic` secret is per-namespace**, seeded by `.github/workflows/flux-bootstrap.yml`'s
  `for NS in kagent-system team-charlie team-alpha` loop. New tenant namespaces running a
  kagent Agent need adding there, or the agent pod sits in `CreateContainerConfigError`.
  Note this workflow is `repository_dispatch`-triggered, which GitHub always runs off the
  **default branch** (`main`) — a fix on `develop` has no effect until merged.

---

## Further detail

- `openspec/changes/openfga-kagent-authz-poc/` — proposal, design, specs for arm 1
- `openspec/changes/k8s-troubleshooter/` — proposal, design, specs for arm 2
- `openspec/changes/archive/2026-08-08-kagent-runtime-validation/` — A2A + namespace isolation baseline
- Issue [#103](../../issues/103) — OpenFGA POC tracking issue, has the arm-1 validation log comment
