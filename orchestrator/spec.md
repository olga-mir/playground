# Technical Specification: Orchestrator Rewrite (DSPy + LiteLLM + Pi)

## 1. Goal
Rewrite the core logic of `orchestrator/main.py` to move from a CLI-wrapper architecture to a programmatic, structured, and multi-model agentic framework.

## 2. Core Components

### 2.1. Router (`llm_router.py`)
*   **Responsibility**: Initialize and configure the LiteLLM client based on environment variables.
*   **Requirements**:
    *   Read `ORCHESTRATOR_MODEL`.
    *   Support `openrouter/`, `vertex_ai/`, and local `openai/` (vLLM) endpoints.
    *   Handle authentication (GCP ADC, OpenRouter keys).

### 2.2. Schemas (`schemas.py`)
*   **Responsibility**: Define Pydantic models for structured agent outputs.
*   **Models**:
    *   `PhaseHealthVerdict`: `is_healthy` (bool), `errors` (list[dict]), `analysis` (str), `recommendation` (str), `problem_domain` (str).
    *   `DiagnosticsDecision`: `rationale` (str), `confidence` (float), `decision` (str: retry/teardown/escalate).

### 2.3. Signatures (`signatures.py`)
*   **Responsibility**: Define DSPy Signatures for the agents.
*   **Signatures**:
    *   `AssessPhaseHealth`: Maps `phase_description` and `cluster_state` to `PhaseHealthVerdict`.
    *   `DiagnoseFailure`: Maps `phase_name`, `errors`, and `cluster_state` to `DiagnosticsDecision`.

### 2.4. Prompt Management (`pi` integration)
*   **Responsibility**: Use `pi-prompt` to manage system prompts and cluster context.
*   **Requirements**:
    *   Convert existing `.claude/agents/*.md` files into templates.
    *   Implement a context provider that gathers `kubectl` state and formats it for the LLM.

## 3. Implementation Phases

### Phase 1: Infrastructure
*   Install dependencies (`litellm`, `dspy-ai`, `pydantic`, `pi-prompt`).
*   Implement `llm_router.py` with a connectivity test.
*   Create a `check_env.py` script to validate all keys and endpoints.

### Phase 2: Structural Foundation
*   Implement `schemas.py` using Pydantic.
*   Implement `signatures.py` using DSPy.
*   Setup `pi` templates for "bootstrap", "control", and "workload" phases.

### Phase 3: Logic Refactor
*   Modify `run_phase()` in `main.py` to use `AssessPhaseHealth` (DSPy).
*   Modify `handle_failure()` in `main.py` to use `DiagnoseFailure` (DSPy).
*   Refactor "Known Remedies" into a modular dispatch system that checks `PhaseHealthVerdict.errors` against a registry of handlers.

### Phase 4: Observability & Telemetry
*   Update `telemetry.py` to ensure LiteLLM calls are tracked as spans.
*   Ensure the `traceparent` is correctly propagated through LiteLLM to supported backends (like Vertex AI).
