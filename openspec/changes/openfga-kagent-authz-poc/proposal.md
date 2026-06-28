# Proposal: openfga-kagent-authz-poc

## Summary

Deploy OpenFGA on apps-dev and gate kagent tool invocations via relationship tuples,
using an MCP proxy (Option B) that intercepts calls between kagent agents and the
kagent-tools MCP server. The proxy checks OpenFGA before forwarding each tool call —
no kagent internals or undocumented APIs involved. A dedicated proxy instance per agent
solves the caller-identity problem cleanly.

## Problem

kagent's current authorization is binary: tools either run freely or pause for a human
to click approve in the UI. The `requireApproval` field triggers a UI-only flow with no
documented programmatic callback endpoint — so it cannot be wired to an external policy
engine without reverse-engineering the A2A session stream. There is no way to say "agent
X can invoke tool Y but not tool Z" programmatically without hardcoding it into manifests
and redeploying. Destructive operations (delete, apply) are only guarded by the
systemMessage prompt, not an enforceable policy layer.

## Proposed Solution

1. **Deploy OpenFGA** on apps-dev via a Flux-managed HelmRelease using the `memory`
   datastore (ephemeral — sufficient for POC; CloudSQL deferred).
2. **Define an authorization model** with two types: `agent` and `tool`. Seed initial
   tuples granting read-only tools; leave destructive tools (`k8s_delete_resource`,
   `k8s_apply_manifest`) unseeded (blocked by default).
3. **Build an MCP proxy** (Python, deployed in `kagent-system`) that:
   - Implements the MCP SSE/StreamableHttp transport on the inbound side
   - Accepts tool call requests from a kagent agent
   - Calls OpenFGA `Check` with `(agent_id, tool_name)` before forwarding
   - Forwards allowed calls to the real `kagent-tools` MCP server; returns an MCP error
     for blocked calls
   - Knows its agent identity via an env var (`AGENT_ID=k8s-agent`) — one proxy
     instance per agent avoids needing to extract identity from request headers
4. **Create a ToolServer CR** pointing to the proxy; add it to `k8s-agent`'s tools list.
5. **Validate** the end-to-end flow: confirm a delete call is blocked without a tuple,
   write the tuple via OpenFGA API at runtime, confirm it is then allowed — no restart.

## Capabilities Affected

- `kubernetes/namespaces/overlays/apps-dev/kustomization.yaml` — add openfga namespace
- New: `kubernetes/namespaces/base/openfga/` — namespace, HelmRepository, HelmRelease,
  bootstrap Job, openfga-store ConfigMap
- New: `kubernetes/namespaces/base/kagent/kagent/config/mcp-proxy-deployment.yaml`
  — Deployment + Service + ToolServer CR for the proxy
- `kubernetes/namespaces/base/kagent/kagent/config/k8s-agent.yaml` — add explicit tools
  entry referencing the proxy ToolServer
- `kubernetes/namespaces/base/kagent/kagent/config/kustomization.yaml` — add proxy manifest
- New: `apps/openfga-mcp-proxy/` — Python service source + Dockerfile

## Impact & Risks

- Enables runtime, tuple-driven tool authz without manifest changes or restarts.
- Risk: MCP transport protocol used by kagent-tools (SSE vs StreamableHttp) must be
  confirmed from the live cluster — the proxy must implement the same protocol.
- Risk: `memory` datastore loses all tuples on OpenFGA pod restart — tuples must be
  re-seeded; bootstrap Job handles initial seeding but runtime-added tuples are lost.
- Risk: k8s-agent will have both the original auto-wired kagent-tools AND the proxy
  ToolServer in its tool list; the LLM may call either. Mitigation: disable the direct
  kagent-tools wiring for k8s-agent via HelmRelease values if possible, or accept the
  ambiguity for the POC.
- Effort: ~1 day of implementation once apps-dev is running and `kagent-runtime-validation`
  is complete.
- **Prerequisite:** `kagent-runtime-validation` must be complete (A2A baseline proven,
  negative isolation documented).

## Out of Scope

- CloudSQL or any persistent datastore for OpenFGA
- Envoy ext_authz filter (Option A)
- kagent `requireApproval` hook (Option C — UI-only, no programmatic callback endpoint)
- Multi-cluster OpenFGA federation
- OpenFGA Playground UI
- Policy for agent-to-agent calls (namespace isolation stays in `allowedNamespaces`)
- Any agent other than `k8s-agent` as the first proxy target
