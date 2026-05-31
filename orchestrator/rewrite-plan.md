# Orchestrator Architecture Rewrite: DSPy + LiteLLM

## Status: Complete

All implementation phases are done. See `docs/agentic-architecture.md` for the current architecture reference.

---

## What was built

A pure programmatic Python orchestrator. No subprocess CLI harness (`claude -p`, `pi -p`, or similar). All LLM reasoning runs inside the Python process via DSPy + LiteLLM.

```
Local DGX Spark (vLLM)  →  OpenRouter  →  Vertex AI / Anthropic SDK
         └──────────────────────────────────────────┘
                        LiteLLM (transparent fallback)
                               │
                             DSPy
                    ┌──────────┴──────────┐
         ChainOfThought              ReAct + tools
        (AssessPhaseHealth)        (DiagnoseFailure)
```

### Key design decisions

**Pi is not used in the orchestrator.** `pi` (`earendil-works/pi`) is a human-facing CLI harness (like Claude Code), not a library. Calling it via subprocess would have the same fragility as the old `claude -p` approach. Phase context is loaded directly from `orchestrator/phases/*.md`.

**`DiagnoseFailure` is `dspy.ReAct`, not `dspy.ChainOfThought`.** A stateless CoT call can only make a decision based on the error text it receives. Novel failures require live investigation and fixes — kubectl, file edits, git push. ReAct with tools enables this without any subprocess harness.

**Known Catch-22 patterns remain as Python fast-paths.** The three patterns (provider:github, stale resourceRefs, stuck dependency) are deterministic and don't need LLM reasoning. They bypass `DiagnoseFailure` entirely.

---

## Implementation phases

### Phase 1: Environment & Tooling — ✅ done
- `pyproject.toml`: `litellm`, `dspy-ai`, `pydantic` (no `pi-prompt`)
- `llm_router.py`: LiteLLM factory reading `ORCHESTRATOR_MODEL` + fallback chain
- `check_env.py`: connectivity test (`task agentic:check-env`)

### Phase 2: Pydantic Models & DSPy Signatures — ✅ done
- `schemas.py`: `PhaseHealthVerdict`, `DiagnosticsDecision`
- `signatures.py`: `AssessPhaseHealth`, `DiagnoseFailure`

### Phase 3: Context Management — ✅ done (simplified)
- Phase definitions in `orchestrator/phases/*.md`, loaded directly via `Path.read_text()`
- No `pi` templates; context injected as plain text into DSPy input fields
- Cluster state snapshot via `scripts/collect-cluster-state.sh`

### Phase 4: `main.py` — ✅ done
- `run_phase()`: `dspy.ChainOfThought(AssessPhaseHealth)` replaces phase-checker subprocess
- `handle_failure()`: Python fast-paths → `dspy.ReAct(DiagnoseFailure, tools=[...])`
- ReAct tools: `kubectl_get/describe/logs/patch/annotate`, `read_file`, `write_file`, `git_commit_push`
- CLI args preserved: `--skip-install`, `--start-phase`, `--mission`, `--initial-wait`
- Taskfile tasks restored: `task agentic:deploy/resume/check/check-env`

### Phase 5: Observability & Telemetry — ✅ done
- `telemetry.py`: `record_llm(module, duration, status)` replaces `record_gemini`
- `gemini_cli_otel_env` removed (no CLI subprocess to instrument)
- Metrics: `orchestrator.llm.*` and `orchestrator.shell.*`

---

## Next step

Run `task agentic:check-env` with `ORCHESTRATOR_MODEL` set to verify the LLM chain connects, then a full `task agentic:deploy --skip-install` against a live cluster.
