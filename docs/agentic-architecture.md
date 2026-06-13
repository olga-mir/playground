# Agentic Loop — Architecture

## Overview

The orchestrator is a pure Python application (`orchestrator/main.py`) that drives cluster provisioning through three phases: kind bootstrap → GKE control-plane → GKE apps-dev. It uses DSPy + LiteLLM for all LLM reasoning — no subprocess CLI harness.

```
orchestrator/main.py
  │
  ├─ run_phase()
  │    └─ dspy.ChainOfThought(AssessPhaseHealth)
  │         ├─ input: phase description (orchestrator/phases/*.md)
  │         │         cluster state (scripts/collect-cluster-state.sh)
  │         └─ output: PhaseHealthVerdict (is_healthy, recommendation, problem_domain, failing_resources)
  │
  └─ handle_failure()
       ├─ Python fast-paths (known Catch-22 patterns, no LLM needed)
       └─ dspy.ReAct(DiagnoseFailure, tools=[kubectl, file, git])
            ├─ input: phase, errors, initial context
            ├─ tools: kubectl_get/describe/logs/patch/annotate
            │         read_file, write_file, git_commit_push
            └─ output: DiagnosticsDecision (action, confidence, rationale)
```

### Model chain (LiteLLM)

```
Local DGX Spark (vLLM)  →  OpenRouter  →  Vertex AI / Anthropic SDK
```

Configured via `ORCHESTRATOR_MODEL`, `ORCHESTRATOR_FALLBACK_MODELS`. No vendor lock-in; swap models by changing env vars.

---

## How LLM reasoning works

### Phase assessment — `AssessPhaseHealth`

A `dspy.ChainOfThought` module. Stateless and fast. Receives:
- `phase_description`: the full markdown spec from `orchestrator/phases/<phase>.md`
- `cluster_state`: output of `scripts/collect-cluster-state.sh <phase>`

Returns a structured `PhaseHealthVerdict`:
```json
{
  "is_healthy": false,
  "recommendation": "diagnose",
  "problem_domain": "crossplane | flux | github-actions | unknown",
  "failing_resources": [{"kind": "...", "name": "...", "error": "..."}],
  "analysis": "..."
}
```

### Failure diagnosis — `DiagnoseFailure`

A `dspy.ReAct` module with live cluster tools. Handles novel failures that the Python fast-paths don't cover. The agent iteratively:
1. Investigates the live cluster (kubectl get/describe/logs)
2. Reads and edits repository manifests
3. Commits and pushes fixes via `git_commit_push` (with fetch+rebase guard)
4. Returns a `DiagnosticsDecision` with `action: retry | teardown | escalate`

The agent receives the errors from `AssessPhaseHealth` plus initial context, then calls tools freely up to `max_iters=20`.

### Python fast-paths (no LLM)

Three known Catch-22 patterns are detected by regex on the error messages and handled directly in Python before `DiagnoseFailure` is ever called:

| Pattern | Remedy |
|---|---|
| `provider:github` missing on GitRepository | `kubectl patch` live object |
| Stale `resourceRefs` after Composition API group change | `kubectl patch spec.resourceRefs=null` |
| Flux kustomization stuck on stale `dependency not ready` | `kubectl annotate` to force-reconcile |

---

## Key files

| File | Role |
|---|---|
| `orchestrator/main.py` | Phase loop, fast-paths, DSPy module wiring |
| `orchestrator/schemas.py` | Pydantic models: `PhaseHealthVerdict`, `DiagnosticsDecision` |
| `orchestrator/signatures.py` | DSPy signatures: `AssessPhaseHealth`, `DiagnoseFailure` |
| `orchestrator/llm_router.py` | LiteLLM factory, reads `ORCHESTRATOR_MODEL` env var |
| `orchestrator/telemetry.py` | OTEL: spans + `record_llm()` + `record_shell()` |
| `orchestrator/phases/*.md` | Phase health criteria (bootstrap, control, workload) |
| `orchestrator/check_env.py` | LLM connectivity test (`task agentic:check-env`) |
| `scripts/collect-cluster-state.sh` | Cluster state snapshot, callable by orchestrator and humans |

---

## The `.claude/agents/` layer

The agent files in `.claude/agents/` (`phase-checker.md`, `crossplane-diagnostics.md`, etc.) are **not invoked by the orchestrator**. They remain available for:
- Human interactive sessions via Claude Code (e.g. manually running `/crossplane-troubleshoot`)
- Direct sub-agent invocation during human-driven debugging

The orchestrator's `DiagnoseFailure` ReAct module carries equivalent domain knowledge through its system prompt context (DSPy signatures) and exercises it via direct tool calls rather than delegating to a separate CLI harness.

---

## Cluster state collection

`scripts/collect-cluster-state.sh <phase>` is the single source of truth for pre-collected cluster state. It is:
- Called by `run_phase()` before each `AssessPhaseHealth` call
- Called by `handle_failure()` to save a reference snapshot before diagnosis
- Callable manually by a human for interactive debugging
- Writable to `orchestrator/runs/snapshot-<phase>-<ts>.txt` for session evidence

The `DiagnoseFailure` ReAct agent does **not** receive this snapshot — it collects what it needs via kubectl tools directly.

---

## Environment variables

| Variable | Purpose |
|---|---|
| `ORCHESTRATOR_MODEL` | Primary model (`openai/spark`, `openrouter/...`, `vertex_ai/...`) |
| `ORCHESTRATOR_FALLBACK_MODELS` | Comma-separated fallback chain |
| `ORCHESTRATOR_API_BASE` | API base URL (for local vLLM/Spark) |
| `ORCHESTRATOR_API_KEY` | API key (optional, provider-specific) |
| `PROJECT_ID` | GCP project for OTEL export |

---

## Future work

### Skills layer (human-facing)

The `.claude/skills/` directory currently only has `upgrade-versions/`. Planned skills that mirror the domain knowledge baked into `DiagnoseFailure`:
- `/crossplane-troubleshoot` — interactive Crossplane debugging, also the natural kagent tool entry point
- `/flux-troubleshoot` — deferred until after Flux operator migration (#71)
- `/flux-debug` — deferred until after #71

### kagent integration

A kagent tool definition would wrap crossplane/flux troubleshooting knowledge for in-cluster use. The shared knowledge layer is what gets reused; the operational wrapper differs (no `--context` flags, talks to the local API server). The `DiagnoseFailure` ReAct tools give a clear template for what a kagent tool needs to expose.
