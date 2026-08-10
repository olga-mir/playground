# Spec: k8s-troubleshooter-mcp-server

## Overview

A custom Python MCP server (`apps/k8s-troubleshooter-mcp/`) exposing semantic diagnostic
tools that aggregate Kubernetes API calls into correlated, single-response results. Each
tool handler checks OpenFGA before executing, enforcing namespace-scoped authorization
without an intercepting proxy.

---

### Requirement: Semantic diagnostic tools

**Context:** Raw kubectl primitives require multi-step agent reasoning. Semantic tools
pre-aggregate all relevant signals into one structured response, reducing LLM round-trips.

#### Scenario: Diagnose a namespace
- **Given** the MCP server is running with in-cluster credentials
- **When** `diagnose_namespace(namespace="team-alpha")` is called
- **Then** the server returns a single structured report containing pod statuses, recent
  Warning events (last 1h), resource pressure indicators, and any containers in
  CrashLoopBackOff or OOMKilled state — collected in parallel

#### Scenario: Get pod failure context
- **Given** a pod in a non-Running state exists in the target namespace
- **When** `get_pod_failure_context(namespace="team-alpha", pod="my-app-xyz")` is called
- **Then** the server returns correlated output: tail-100 logs from all containers,
  `describe` output, and events scoped to that pod — as a single response

#### Scenario: Get namespace resource pressure
- **Given** the target namespace has ResourceQuota and/or LimitRange objects defined
- **When** `get_namespace_resource_pressure(namespace="team-alpha")` is called
- **Then** the server returns ResourceQuota usage vs limits, LimitRange defaults,
  and node-level pressure conditions (DiskPressure, MemoryPressure, PIDPressure)
  for nodes running pods in that namespace

---

### Requirement: In-cluster Kubernetes API access

**Context:** The server must not shell out to kubectl; it must call the Kubernetes API
directly via the kubernetes-client Python library using the in-cluster service account.

#### Scenario: In-cluster API calls succeed
- **Given** the server's pod is running with a ServiceAccount bound to a narrow ClusterRole
- **When** a tool handler makes a Kubernetes API call (e.g. list pods)
- **Then** the call succeeds without shelling out, and errors surface as structured
  tool errors rather than unhandled exceptions

#### Scenario: Missing RBAC permission
- **Given** the ServiceAccount lacks permission for a specific resource type
- **When** a tool handler attempts to access that resource
- **Then** the server returns a structured error with `403 Forbidden` details, not a
  stack trace, and the overall tool response is still valid (partial data where available)

---

### Requirement: OpenFGA authorization check per tool call

**Context:** Authorization must be enforced inside the tool handler, not via an external
proxy, so there is no bypass gap.

#### Scenario: Authorized agent diagnoses an allowed namespace
- **Given** an OpenFGA tuple `(agent:troubleshooter-agent, can_diagnose, namespace:team-alpha)`
  exists in the store
- **When** the agent calls `diagnose_namespace(namespace="team-alpha")`
- **Then** the OpenFGA check passes and the diagnostic result is returned

#### Scenario: Agent attempts to diagnose an unauthorized namespace
- **Given** no `can_diagnose` tuple exists for `namespace:team-beta` for this agent
- **When** the agent calls `diagnose_namespace(namespace="team-beta")`
- **Then** the OpenFGA check fails and the tool returns a `403 Forbidden` error;
  no Kubernetes API calls are made for that namespace

#### Scenario: OpenFGA store is unreachable
- **Given** the OpenFGA service is down or its endpoint is misconfigured
- **When** any tool handler attempts an authorization check
- **Then** the server fails closed: the tool returns an error and no Kubernetes data
  is returned

---

### Requirement: Deployment packaging

**Context:** The server must be containerizable and deployable via Flux with minimal
operational overhead in a POC context.

#### Scenario: Local development build
- **Given** a developer runs `docker build` in `apps/k8s-troubleshooter-mcp/`
- **When** the build completes
- **Then** the image runs the MCP server on port 8080 with no external dependencies
  beyond the Kubernetes API and OpenFGA endpoint (both provided via env vars)

#### Scenario: Helm/Kustomize deployment
- **Given** a `ToolServer` CR referencing the built image exists in
  `kubernetes/namespaces/base/team-alpha/troubleshooter/`
- **When** Flux reconciles the kustomization
- **Then** the server pod starts, passes readiness checks, and the `ToolServer` status
  shows `Ready`
