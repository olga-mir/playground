# Spec: k8s-troubleshooter-manifests

## Overview

Kubernetes manifests under `kubernetes/namespaces/base/team-alpha/troubleshooter/` that
wire the custom MCP server into the cluster: a `ToolServer` CR pointing at the service,
an `Agent` CR backed by that `ToolServer`, a `ServiceAccount` for in-cluster API access,
and a `ClusterRole`/`ClusterRoleBinding` scoped to the minimum read permissions needed.

---

### Requirement: Narrow RBAC for in-cluster API access

**Context:** The MCP server's service account must have exactly the permissions it needs
and no more. Over-broad RBAC (e.g. cluster-admin) defeats the security purpose of
namespace-scoped OpenFGA authorization.

#### Scenario: ClusterRole grants minimum required verbs
- **Given** the `ClusterRole` manifest for the troubleshooter service account
- **When** reviewing the rules
- **Then** it grants only `get` and `list` on `pods`, `events`, `nodes`, `resourcequotas`,
  and `limitranges` — no write verbs, no secrets, no exec

#### Scenario: ClusterRoleBinding scopes to the ServiceAccount
- **Given** the `ClusterRoleBinding` references the `troubleshooter-mcp` ServiceAccount
  in namespace `team-alpha`
- **When** the MCP server pod starts under that ServiceAccount
- **Then** Kubernetes API calls succeed for read operations and fail with 403 for any
  write or exec operation

---

### Requirement: ToolServer CR

**Context:** kagent uses `ToolServer` CRs to register MCP servers available to agents.

#### Scenario: ToolServer registers the custom MCP server
- **Given** a `ToolServer` CR named `k8s-troubleshooter` in namespace `team-alpha`
  with `spec.url` pointing to the MCP server service (`http://k8s-troubleshooter-mcp:8080/mcp`)
- **When** kagent reconciles the CR
- **Then** the `ToolServer` status shows `Ready` and the three diagnostic tools appear
  in the tool inventory

#### Scenario: ToolServer does not reference kagent-tool-server
- **Given** the `Agent` CR for the troubleshooter
- **When** reviewing its `spec.toolServers` list
- **Then** it references only `k8s-troubleshooter` and does NOT include
  `kagent-tool-server`, preventing auto-wiring of unproxied raw tools

---

### Requirement: Agent CR

**Context:** The kagent `Agent` CR binds the LLM model, system prompt, and tool servers
for the troubleshooter agent.

#### Scenario: Agent CR declares only the custom ToolServer
- **Given** the `Agent` CR named `k8s-troubleshooter-agent` in `team-alpha`
- **When** kagent provisions it
- **Then** the agent has access to exactly the three semantic tools exposed by the
  custom MCP server and no raw kubectl primitives

#### Scenario: Agent system prompt constrains behavior to diagnostics
- **Given** the `Agent` CR includes a system prompt
- **When** reviewing `spec.systemPrompt`
- **Then** the prompt instructs the agent to use diagnostic tools only, report findings
  in structured form, and not attempt write or mutation operations

---

### Requirement: Flux reconciliation

**Context:** All manifests are managed via Flux GitOps; no kubectl apply by hand.

#### Scenario: Kustomization reconciles cleanly
- **Given** the `kustomization.yaml` in `kubernetes/namespaces/base/team-alpha/troubleshooter/`
  references all required resources
- **When** Flux reconciles the kustomization
- **Then** all resources are created without errors, and `flux get kustomizations` shows
  the kustomization as `Ready`

#### Scenario: Image tag is managed by Flux Image Automation
- **Given** an `ImageRepository` and `ImagePolicy` are defined for the MCP server image
- **When** a new image tag is pushed to the registry
- **Then** Flux Image Automation updates the `Deployment` manifest and commits the change,
  triggering a new reconciliation
