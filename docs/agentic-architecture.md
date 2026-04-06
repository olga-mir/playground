# Agentic Loop — Architecture & Refactor Plan

## Honest assessment of the current state

The bones are right: a Python coordinator driving a phase loop, safety hooks, agents for assessment and diagnosis, mission context. But the agent layer was grown reactively rather than designed, and two structural problems now limit how well the system works.

**Single generalist diagnostics agent.** One agent is expected to handle Crossplane provider CRD registration failures, composition rendering, Flux kustomization auth, GitRepository `provider: github`, GitHub Actions bootstrap failures, and GKE provisioning errors. A generalist cannot go deep. The agent keeps making shallow inferences because it has no focused domain expertise wired in.

**Cluster state collection in Python.** `collect_cluster_state()` in `main.py` is a growing list of hard-coded kubectl commands. It cannot be reused by a human debugging interactively, by kagent running inside a cluster, or by a GitHub Actions workflow. It's also the wrong place for this knowledge.

---

## Design principles going forward

**`.claude/` is the reusable capability layer.** Skills and agents defined here should be usable across all workflows without modification:
- Human interactive sessions (Claude Code)
- The agentic loop (`task agentic:deploy`)
- GitHub Actions workflows
- kagent running inside a Kubernetes cluster

**Skills for humans, agents for machines — same knowledge, different packaging.**

A *skill* (`.claude/skills/<name>/`) is a domain knowledge prompt invoked by a human via `/name`. It is conversational and supports broad investigation across whatever the human brings to it.

An *agent* (`.claude/agents/<name>.md`) is the same domain knowledge plus operational constraints: specific tools allowed, structured JSON output, restrictions on what it may or may not do. It is invoked by the orchestrator via `claude -p`.

They are not the same file, but they share the same domain expertise section. When the domain knowledge changes, both need updating. In a future where skills are a proper open standard they may share a file; for now they share content.

**Can an agent call a skill?** No, not via `/name` syntax — that is human UI. An agent can invoke another *agent* as a sub-agent (Claude Code's Agent tool), which is how routing works inside the agentic loop. Skills are the human entry point; sub-agents are the machine entry point for the same expertise.

**Cluster state collection belongs in a script, not Python.** A shell script run by the orchestrator, by a human, and by kagent without any Python dependency.

---

## Current file inventory

```
.claude/
├── agents/
│   ├── phase-checker.md          # assessment only, no tools, pre-collected data
│   ├── diagnostics.md            # generalist — does everything, goes shallow
│   └── github-actions-flux-debugger.md   # exists, NOT wired into the loop
└── skills/
    └── upgrade-versions/         # only skill that exists today
```

**On the flux-debugger question:** there is only an agent, no matching skill. No duplication currently. What is missing is the human-facing `/flux-debug` skill, and more importantly: the agent is not wired into the orchestrator's routing path even though it is the right tool when GitHub Actions bootstrap fails.

---

## Proposed architecture

```
┌─────────────────────────────────────────────────────┐
│                   .claude/ layer                     │
│                                                     │
│  Skills (human-invocable, reusable by kagent)       │
│  ┌─────────────────────┐  ┌──────────────────────┐  │
│  │ /crossplane-trouble │  │ /flux-troubleshoot   │  │
│  │ -shoot              │  │                      │  │
│  └─────────────────────┘  └──────────────────────┘  │
│         ▲ same domain knowledge ▼                   │
│  Agents (machine-invocable, structured output)      │
│  ┌──────────────┐  ┌────────────────┐  ┌─────────┐  │
│  │ crossplane-  │  │ flux-          │  │ github- │  │
│  │ diagnostics  │  │ diagnostics    │  │ actions │  │
│  └──────────────┘  └────────────────┘  │ -flux-  │  │
│                                        │ debugger│  │
│  ┌───────────────────────────────┐     └─────────┘  │
│  │ phase-checker (with tools)    │                  │
│  └───────────────────────────────┘                  │
└─────────────────────────────────────────────────────┘
                         │ routes based on problem_domain
┌─────────────────────────────────────────────────────┐
│            orchestrator/main.py (thin loop)          │
│  - phase loop, escalation logic, state tracking     │
│  - no kubectl, no git, no domain knowledge          │
│  - calls scripts/collect-cluster-state.sh           │
└─────────────────────────────────────────────────────┘
                         │
┌─────────────────────────────────────────────────────┐
│                   scripts/                           │
│  collect-cluster-state.sh   check-fleet-health.sh   │
│  cleanup.sh                 setup-gcp-once.sh       │
└─────────────────────────────────────────────────────┘
```

---

## Component design

### phase-checker — upgrade to active investigator

**Current problem:** works only with pre-collected data. We compensate by collecting more and more up front, which is brittle and never enough.

**Change:** give phase-checker read-only kubectl tools. It receives a baseline state snapshot but can issue `kubectl describe`, `kubectl logs`, `kubectl get crd` etc. when it finds something suspicious. It becomes an active investigator, not a passive assessor.

**Add `problem_domain` to its JSON output:**
```json
{
  "status": "degraded",
  "recommendation": "diagnose",
  "problem_domain": "crossplane | flux | github-actions | unknown",
  "errors": [...],
  "analysis": "..."
}
```

The orchestrator uses `problem_domain` to route to the correct specialist.

---

### crossplane-diagnostics — new specialist agent

Deep expertise in Crossplane v2:
- Provider installation and package resolution (upbound vs contrib family conflict)
- CRD registration patterns per provider version
- Composition rendering: why an XR does not produce managed resources
- API group migrations (e.g. `container.gcp.upbound.io` → `gke.gcp.upbound.io`)
- ProviderRevision dependency resolution failures
- Common failure modes for provider-gcp-gke, provider-gcp-container, ProviderConfig

Tools: read-only kubectl (get, describe, logs), file read/edit, git add/commit/push.

Skill counterpart: `/crossplane-troubleshoot` — same knowledge, conversational framing for interactive debugging. Also the natural entry point for a kagent tool running inside the cluster.

---

### flux-diagnostics — refocused specialist agent

Replaces the current `diagnostics.md` for Flux-specific failures:
- Kustomization dependency chains and why "dependency not ready" can be permanent
- GitRepository auth: the `provider: github` recurring issue, secret structure
- `kustomize build` failures: YAML errors in manifests
- HelmRelease failures
- Image automation and policy issues

Tools: read-only kubectl, file read/edit, git add/commit/push.

Skill counterpart: `/flux-troubleshoot`.

---

### github-actions-flux-debugger — wire into the loop

This agent already exists and is well-written. It is not yet invoked by the orchestrator. When `problem_domain = github-actions` (e.g. a Flux bootstrap workflow failed, a GKE cluster was provisioned but Flux was never bootstrapped on it), the orchestrator should route here.

The agent has different tools from the diagnostics agents: it can inspect GitHub Actions workflow runs, check workflow status, and diagnose authentication issues between GKE and GitHub.

Skill counterpart: `/flux-debug` (a lighter wrapper for human interactive use).

---

### Routing in the orchestrator

```python
domain_to_agent = {
    "crossplane":      "crossplane-diagnostics",
    "flux":            "flux-diagnostics",
    "github-actions":  "github-actions-flux-debugger",
    "unknown":         "flux-diagnostics",   # safest fallback
}
agent_name = domain_to_agent[verdict["problem_domain"]]
system     = read_agent_prompt(agent_name)
raw        = call_claude(system, user_msg, agent_name=agent_name)
```

The orchestrator stays thin. All domain logic is in the agents.

---

### Cluster state collection — move to script

Replace `collect_cluster_state()` in `main.py` with `scripts/collect-cluster-state.sh`.

```bash
# Usage
scripts/collect-cluster-state.sh bootstrap   # kind cluster state
scripts/collect-cluster-state.sh control     # kind + control-plane
scripts/collect-cluster-state.sh workload    # kind + control-plane + apps-dev
```

Outputs the same structured text as today, but is now:
- Callable by the orchestrator: `subprocess.run(["scripts/collect-cluster-state.sh", phase])`
- Callable by a human debugging manually
- Callable by kagent from inside the cluster (adapted to its own context)
- Versionable and testable independently of the Python orchestrator

The phase-checker still receives this as pre-collected baseline context, but now also has tools to dig deeper when it needs to.

---

### kagent integration (future)

A kagent tool definition wraps the skill content plus the kubectl invocations appropriate for in-cluster use (no `--context` flags needed, talks to the local API server). The shared knowledge layer in `.claude/skills/` is what gets reused. The operational wrapper differs: kagent uses its own tool calling interface rather than Claude Code's Bash tool.

The Crossplane troubleshooting skill is the most natural first kagent tool: a cluster can run an agent that diagnoses its own Crossplane state without any external tooling.

---

## Implementation phases

### Phase 1 — Structural (do first, low risk)
- [x] Move `bootstrap/scripts/` → `scripts/` at repo root
- [x] Extract `collect-cluster-state.sh` from Python logic
- [x] Update orchestrator to call script for snapshots; agents use kubectl directly

### Phase 2 — Phase-checker upgrade
- [x] Add kubectl read-only tools to phase-checker (active investigator model)
- [x] Add `problem_domain` field to its JSON output schema
- [x] Update orchestrator to use `problem_domain` for routing

### Phase 3 — Agent specialisation
- [x] Create `crossplane-diagnostics.md` agent with deep Crossplane expertise
- [ ] Refocus `flux-diagnostics.md` (rename current `diagnostics.md`) — deferred until after Flux operator migration (#71)
- [ ] Wire `github-actions-flux-debugger` into orchestrator routing — deferred

### Phase 4 — Skills layer
- [ ] Create `.claude/skills/crossplane-troubleshoot/` skill
- [ ] Create `.claude/skills/flux-troubleshoot/` skill — deferred until after #71
- [ ] Create `.claude/skills/flux-debug/` skill — deferred until after #71

### Phase 5 — kagent
- [ ] Design kagent tool interface for crossplane-troubleshoot skill
- [ ] Adapt skill content for in-cluster context (no --context flags)
