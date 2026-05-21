# Orchestrator Architecture Rewrite: DSPy + LiteLLM + Pi

This document serves as the blueprint for the next AI agent to execute the fundamental rewrite of the Kubernetes provisioning orchestrator.

## 1. The Problem

The current `orchestrator/main.py` is a highly pragmatic but fragile "vibecoded" script. Its core limitations are:
1.  **Fragile Integration**: It drives AI via a subprocess call to a desktop CLI (`claude -p`), capturing `stdout` and manually stripping text to find JSON.
2.  **Vendor Lock-in**: It is hardcoded to Anthropic's ecosystem. It cannot utilize the user's local DGX Spark compute, OpenRouter's massive model marketplace, or Vertex AI's enterprise endpoints.
3.  **Unstructured Reasoning**: Agents are given massive text dumps (raw `kubectl` output) and expected to return valid JSON. There is no schema validation or structured reasoning.
4.  **Regex-driven State**: "Known errors" (Catch-22s like `provider:github` missing) are caught using brittle regex parsing over the LLM's output.

## 2. Tech Stack Choice

To build a robust, multi-model, structured orchestrator, we will adopt the following stack:

*   **LiteLLM (The Universal Router)**: Acts as the translation layer. It allows the orchestrator to swap between `vllm/dgx-spark`, `openrouter/meta-llama/llama-3`, and `vertex_ai/gemini-1.5-pro` using standard environment variables, completely abstracting away the SDK differences and authentication mechanisms.
*   **DSPy (The Reasoning Engine)**: Moves the project from "prompting" to "programming". DSPy will replace the markdown agent prompts with declarative `Signatures` that enforce structured inputs and Pydantic-validated outputs. Crucially, it allows leveraging the DGX Spark to run optimizers (`teleprompters`) to auto-tune prompts.
*   **Pi (`earendil-works/pi`)**: The Context & Template Manager. We will use Pi to separate prompt construction from Python logic, managing the injection of cluster context and Phase Definitions cleanly.
*   **Pydantic (The Schema Validator)**: Ensures that any action the AI decides to take (e.g., "patch this resource", "teardown") is strictly typed and validated before the Python orchestrator executes it.

---

## 3. Detailed Execution Plan

The executing agent should follow these phases sequentially. **Do not attempt to rewrite everything in one commit.**

### Phase 1: Environment & Tooling Setup
1.  **Dependencies**: Update `orchestrator/pyproject.toml` (and sync `uv.lock`) to include `litellm`, `dspy-ai`, `pydantic`, and `pi`.
2.  **Router Configuration**: Create `orchestrator/llm_router.py`. Implement a factory function that reads an `ORCHESTRATOR_MODEL` environment variable (e.g., `openrouter/anthropic/claude-3-sonnet`, `vertex_ai/gemini-1.5-pro`, or `openai/my-local-dgx-model` with `OPENAI_API_BASE`).
3.  **DSPy Initialization**: Configure DSPy to use the LiteLLM client as its default language model.

### Phase 2: Define Pydantic Models & DSPy Signatures
1.  **Data Models**: Create `orchestrator/schemas.py`. Define Pydantic models for the outputs:
    *   `PhaseHealthVerdict`: Fields for `is_healthy` (bool), `failing_resources` (list), and `recommendation` (wait/diagnose/teardown).
    *   `DiagnosticsDecision`: Fields for `rationale` (str), `confidence` (float), and `action` (retry/teardown/escalate).
2.  **DSPy Signatures**: Create `orchestrator/signatures.py`.
    *   Define `AssessPhaseHealth(dspy.Signature)` using the Pydantic models.
    *   Define `DiagnoseFailure(dspy.Signature)`.

### Phase 3: Integrate `pi` for Context Management
1.  **Template Migration**: Move the textual descriptions of the phases (currently in `PHASE_DEFINITIONS` in `main.py`) and the system prompts (from `.claude/agents/*.md`) into `pi` compatible templates or discrete text files that `pi` can assemble.
2.  **Context Injection**: Write a wrapper that uses `pi` to construct the exact state context (the `kubectl` outputs) and feeds it into the DSPy modules.

### Phase 4: Refactor `main.py` (The Heart Transplant)
1.  **Replace `call_claude`**: Remove the `subprocess.run(["claude", "-p", ...])` logic entirely.
2.  **Wire up the Phase Runner**: Update `run_phase()` to instantiate the DSPy `ChainOfThought` module for `AssessPhaseHealth`. Pass the `pi`-templated context to it.
3.  **Wire up the Diagnostics Runner**: Update `handle_failure()` to use the `DiagnoseFailure` DSPy module.
4.  **Modularize Remedies**: Convert the hardcoded regex blocks (e.g., `is_provider_github_error`) into a list of generic "Remedy" checks evaluated against the structured output of the DSPy agent, rather than raw strings.

### Phase 5: Verification & Testing
1.  **Dry Run**: Test the pipeline using a fast/cheap model via OpenRouter to ensure the Pydantic schemas parse correctly.
2.  **Local DGX Test**: Point `ORCHESTRATOR_MODEL` to the DGX Spark endpoint and verify local inference works.
3.  **Telemetry Check**: Ensure `telemetry.py` spans still correctly wrap the new LiteLLM/DSPy network calls, replacing the old subprocess shell tracking.