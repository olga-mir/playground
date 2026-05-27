# Setup Guide: New Orchestrator Architecture

This guide outlines the dependencies and configuration required to run the new orchestrator using DSPy, LiteLLM, and Pi.

## 1. Prerequisites

*   **Python 3.10+**: Ensure you have a compatible Python version installed.
*   **uv**: We use `uv` for lightning-fast package management and project isolation.
    *   Installation: `curl -LsSf https://astral.sh/uv/install.sh | sh`
*   **Environment Variables**:
    *   `ORCHESTRATOR_MODEL`: The identifier for the model you want to use (e.g., `openrouter/anthropic/claude-3-sonnet`, `vertex_ai/gemini-1.5-pro`).
    *   `OPENROUTER_API_KEY`: Required if using OpenRouter.
    *   `PROJECT_ID`: Your GCP Project ID (required for Vertex AI and Telemetry).
    *   `GOOGLE_APPLICATION_CREDENTIALS`: Path to your GCP service account key (if not using `gcloud auth application-default login`).
    *   `OPENAI_API_BASE`: Set this if pointing to a local vLLM / DGX Spark endpoint.

## 2. Dependencies

The new orchestrator requires the following core Python libraries:

| Library | Purpose |
| :--- | :--- |
| `dspy-ai` | The reasoning and programming framework for LLMs. |
| `litellm` | Universal proxy/translator for multiple LLM providers. |
| `pi-prompt` | (Referred to as `pi`) For prompt management and context injection. |
| `pydantic` | Data validation and settings management using Python type hints. |
| `opentelemetry-*` | For distributed tracing and metrics (already in project). |

## 3. Local Development Setup

### Step 1: Initialize the project
In the `orchestrator/` directory:
```bash
uv init
```

### Step 2: Add dependencies
```bash
uv add dspy-ai litellm pydantic pi-prompt
```

### Step 3: Configure LiteLLM for DGX Spark (Optional)
If you are using a local DGX Spark endpoint, you can test connectivity with LiteLLM:
```bash
export OPENAI_API_BASE="http://your-dgx-spark-url/v1"
litellm --model openai/your-model-name
```

## 4. Verification

To verify your setup is correct, you can run the diagnostic check (once implemented):
```bash
uv run python check_env.py
```
*(This script will be created as part of Phase 1 of the implementation).*
