# Technical Specification: Orchestrator (DSPy + LiteLLM)

## 1. Goal

A pure programmatic Python orchestrator for cluster provisioning. No subprocess CLI harness. All LLM reasoning via DSPy + LiteLLM with a local-first model chain (Local Spark → OpenRouter → Vertex AI).

## 2. Core Components

### 2.1. Router (`llm_router.py`)
- Reads `ORCHESTRATOR_MODEL` env var
- Supports `openrouter/`, `vertex_ai/`, and local `openai/` (vLLM) endpoints via LiteLLM
- Optional `ORCHESTRATOR_FALLBACK_MODELS` (comma-separated) for resilient failover
- Optional `ORCHESTRATOR_API_BASE` for local Spark/Ollama endpoints

### 2.2. Schemas (`schemas.py`)
Pydantic models for structured LLM outputs:

**`PhaseHealthVerdict`**
- `is_healthy: bool`
- `recommendation: str` — `proceed | wait | diagnose | teardown`
- `problem_domain: str` — `crossplane | flux | github-actions | unknown`
- `failing_resources: list[dict]` — each with `kind`, `name`, `namespace`, `error`
- `analysis: str`

**`DiagnosticsDecision`**
- `rationale: str`
- `confidence: float`
- `action: str` — `retry | teardown | escalate`

### 2.3. Signatures (`signatures.py`)
DSPy Signatures defining the LLM module interfaces:

**`AssessPhaseHealth`**
- Input: `phase_description` (str), `cluster_state` (str)
- Output: `verdict` (PhaseHealthVerdict)
- Used with: `dspy.ChainOfThought`

**`DiagnoseFailure`**
- Input: `phase_name` (str), `errors` (str), `cluster_state` (str)
- Output: `decision` (DiagnosticsDecision)
- Used with: `dspy.ReAct` + kubectl/file/git tools

### 2.4. Phase Definitions (`phases/*.md`)
Phase health criteria are plain markdown files (`bootstrap.md`, `control.md`, `workload.md`). Loaded directly via `Path.read_text()` and passed as `phase_description` to `AssessPhaseHealth`. No templating layer.

## 3. Runtime Flow

```
run_phase(phase):
  1. collect_cluster_state(phase)   # scripts/collect-cluster-state.sh
  2. ChainOfThought(AssessPhaseHealth)(phase_description, cluster_state)
  3. if verdict.is_healthy → return healthy
  4. if verdict.recommendation == "diagnose" → return degraded + errors

handle_failure(phase, errors):
  1. Check known patterns → apply Python fast-path if matched
  2. ReAct(DiagnoseFailure, tools)(phase_name, errors, context)
  3. Return decision.action → retry | teardown | escalate
```

## 4. ReAct Tools

Tools exposed to the `DiagnoseFailure` ReAct agent:

| Tool | Purpose |
|---|---|
| `kubectl_get(args)` | Read cluster resources |
| `kubectl_describe(args)` | Inspect resource details and events |
| `kubectl_logs(args)` | Fetch pod/container logs |
| `kubectl_patch(args)` | Apply live fixes to cluster objects |
| `kubectl_annotate(args)` | Annotate resources (e.g. force Flux reconcile) |
| `read_file(relative_path)` | Read repo manifests |
| `write_file(relative_path, content)` | Edit repo manifests |
| `git_commit_push(files, message)` | Stage, commit, fetch+rebase, push |

## 5. Constraints

- **No subprocess CLI**: No `claude -p`, `pi -p`, or equivalent harness calls
- **CLI args preserved**: `--skip-install`, `--start-phase`, `--mission`, `--initial-wait`
- **Idempotent fast-paths**: All Python remedies are safe to re-run
- **Escalation limit**: Same error signature ≥ 3 times → escalate without calling LLM again
- **git_commit_push guard**: Always fetch+rebase before push to handle concurrent changes
