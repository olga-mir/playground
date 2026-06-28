# Proposal: openfga-kagent-authz-poc

## Summary

Deploy OpenFGA on apps-dev and gate kagent tool invocations via relationship tuples,
replacing the static `requireApproval` list with a dynamic, tuple-driven policy check.
The integration uses kagent's existing approval hook (Option C) — a minimal webhook
service calls OpenFGA `Check` before each tool execution and auto-approves or rejects
based on whether a tuple exists for (agent, tool). No Envoy sidecar or controller fork
needed.

## Problem

kagent's current authorization is binary: tools either run freely or pause for a human
to click approve in the UI. There is no programmatic, policy-driven way to say "agent X
can invoke tool Y but not tool Z" without hardcoding it into manifests and redeploying.
The namespace isolation implemented in `kagent-workflow-uplift` (#107) enforces which
agents can call which agents but does not control which *tools* an agent may invoke at
runtime. Destructive operations (delete, patch, apply) are only guarded by the
systemMessage prompt — not by an enforceable policy layer.

## Proposed Solution

1. **Deploy OpenFGA** on apps-dev via a Flux-managed HelmRelease using the `memory`
   datastore (ephemeral — sufficient for POC; CloudSQL deferred).
2. **Define an authorization model** with three types: `agent`, `tool`, `namespace`.
   Seed initial tuples granting read-only tools freely and requiring explicit tuples for
   destructive tools (`k8s_delete_resource`, `k8s_apply_resource`).
3. **Add `requireApproval`** to the destructive tool entries in `k8s-agent.yaml`,
   pointing to the approval webhook URL.
4. **Build a minimal approval webhook** (Python, deployed as a Deployment + Service in
   `kagent-system`) that receives the kagent approval callback, extracts `(agent_id,
   tool_name)`, calls `POST /stores/{id}/check` on OpenFGA, and returns approve/reject.
5. **Validate** the full tuple-driven flow: confirm a delete call is blocked without a
   tuple, write the tuple via OpenFGA API at runtime, confirm the call is then allowed —
   no restart of any component.

## Capabilities Affected

- `kubernetes/namespaces/base/kagent/kagent/config/k8s-agent.yaml` — add `requireApproval`
- `kubernetes/namespaces/overlays/apps-dev/kustomization.yaml` — add openfga namespace
- New: `kubernetes/namespaces/base/openfga/` — namespace, HelmRepository, HelmRelease,
  model bootstrap Job
- New: `kubernetes/namespaces/base/kagent/kagent/config/approval-webhook-deployment.yaml`
- New: `apps/openfga-approval-webhook/` — Python service source + Dockerfile + k8s manifests

## Impact & Risks

- Enables runtime, tuple-driven authz without manifest changes or restarts.
- Risk: kagent's `requireApproval` approval callback URL format and payload schema are
  not fully documented publicly — may need to inspect controller source or logs.
- Risk: `memory` datastore loses all tuples on OpenFGA pod restart — acceptable for POC,
  must seed tuples via init Job or startup script.
- Risk: approval webhook must respond within kagent's timeout window (unknown — to be
  measured).
- Effort: ~1 day of implementation once apps-dev is running and `kagent-runtime-validation`
  is complete.
- **Prerequisite:** `kagent-runtime-validation` must be complete (A2A baseline proven,
  negative isolation documented).

## Out of Scope

- CloudSQL or any persistent datastore for OpenFGA
- Envoy ext_authz filter (Option A) or MCP proxy wrapper (Option B)
- Multi-cluster OpenFGA federation
- OpenFGA Playground UI
- Policy for agent-to-agent calls (namespace isolation stays in `allowedNamespaces`)
- Any tenant other than the platform `k8s-agent` as the first integration target
