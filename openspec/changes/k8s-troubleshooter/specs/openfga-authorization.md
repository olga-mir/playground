# Spec: openfga-authorization

## Overview

Extend the existing `kagent-authz` OpenFGA store with a `can_diagnose` relation scoped
to namespaces, and seed the tuples that permit the `k8s-troubleshooter-agent` to diagnose
`team-alpha`. The authorization model change must be backwards-compatible with existing
tuples from the `openfga-kagent-authz-poc` change.

---

### Requirement: Authorization model extension

**Context:** The existing model has relations for agent-to-tool-server access. This change
adds a namespace-scoped `can_diagnose` relation on a `namespace` object type, separate
from tool-level authorization.

#### Scenario: can_diagnose relation added to the model
- **Given** the updated OpenFGA authorization model DSL
- **When** the model is written to the `kagent-authz` store
- **Then** the store accepts tuples of the form
  `(agent:<id>, can_diagnose, namespace:<name>)` without error

#### Scenario: Existing tuples remain valid after model update
- **Given** the updated model is applied to the store that already has
  agent-to-tool-server tuples from the `openfga-kagent-authz-poc`
- **When** a check is run against an existing tuple
- **Then** the check succeeds; no existing authorization is broken by the model update

---

### Requirement: Namespace-scoped authorization tuples

**Context:** The troubleshooter agent is permitted to diagnose `team-alpha` only.
All other namespaces must be denied by default (no tuple = deny in OpenFGA).

#### Scenario: Agent authorized for team-alpha
- **Given** the tuple `(agent:k8s-troubleshooter-agent, can_diagnose, namespace:team-alpha)`
  exists in the store
- **When** the MCP server calls `Check(user=agent:k8s-troubleshooter-agent, relation=can_diagnose, object=namespace:team-alpha)`
- **Then** OpenFGA returns `allowed: true`

#### Scenario: Agent denied for all other namespaces
- **Given** no `can_diagnose` tuple exists for `namespace:kube-system` (or any other namespace)
- **When** the MCP server calls `Check(user=agent:k8s-troubleshooter-agent, relation=can_diagnose, object=namespace:kube-system)`
- **Then** OpenFGA returns `allowed: false`

#### Scenario: Unknown agent identity
- **Given** a request arrives with an unrecognized agent identifier
- **When** the MCP server calls the OpenFGA Check API
- **Then** OpenFGA returns `allowed: false` (no tuple matches); the MCP server rejects
  the tool call with a 403 error

---

### Requirement: Tuple seeding is declarative and idempotent

**Context:** The store must be seeded as part of deployment, not via one-off manual
commands. The seeding job must be idempotent so that re-running it on an existing
store does not produce errors.

#### Scenario: Seeding job runs at deploy time
- **Given** a Kubernetes Job or init container that calls the OpenFGA Write Tuples API
  with the required tuples
- **When** Flux reconciles the troubleshooter kustomization
- **Then** the tuples are present in the store after the Job completes successfully

#### Scenario: Seeding job is idempotent
- **Given** the tuples already exist in the store
- **When** the seeding job runs again (e.g. after a pod restart or Flux re-reconcile)
- **Then** the job completes without error; it handles `already exists` responses from
  the OpenFGA Write API gracefully (write-or-ignore semantics)

---

### Requirement: Agent identity propagation

**Context:** The MCP server must know which agent is making the tool call in order to
pass the correct `user` to the OpenFGA Check. In the kagent model, the agent identity
is not automatically injected into MCP tool calls.

#### Scenario: Agent identity passed via MCP tool metadata or env var
- **Given** the Agent CR includes the agent's identifier in its configuration
- **When** the MCP server receives a tool call
- **Then** it resolves the caller identity from a known mechanism (env var injected at
  deploy time, MCP request metadata, or a fixed identity per-deployment) and uses that
  identity in the OpenFGA check

#### Scenario: Identity mechanism is documented
- **Given** the POC uses a simplified identity model (fixed env var per deployment)
- **When** reviewing the implementation
- **Then** the identity propagation approach is noted as a POC simplification, with
  a comment indicating the production alternative (e.g. SPIFFE/SVID, signed JWT)
