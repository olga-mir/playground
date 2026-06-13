import os
import dspy
import logging

logger = logging.getLogger(__name__)

def get_lm() -> dspy.LM:
    """
    Initializes and configures the default dspy.LM client using environment variables.
    
    Expected environment variables:
      - ORCHESTRATOR_MODEL: The model string in provider/name format.
                            Examples: 'openrouter/anthropic/claude-3.5-sonnet',
                                      'vertex_ai/gemini-1.5-pro',
                                      'openai/spark-local-model'
      - ORCHESTRATOR_API_BASE: Optional api_base URL (useful for local vLLM/Spark/Ollama).
      - ORCHESTRATOR_API_KEY: Optional API key.
      - ORCHESTRATOR_FALLBACK_MODELS: Optional comma-separated list of models to try if the main one fails.
                                      Example: "openrouter/meta-llama/llama-3-70b-instruct,vertex_ai/gemini-1.5-pro"
    """
    model = os.environ.get("ORCHESTRATOR_MODEL")
    if not model:
        # Fall back to a sensible default if not set
        model = "vertex_ai/gemini-1.5-pro"
        logger.info(f"ORCHESTRATOR_MODEL env var not set. Defaulting to {model}")
    else:
        logger.info(f"Initializing orchestrator LLM with model: {model}")

    api_base = os.environ.get("ORCHESTRATOR_API_BASE")
    api_key = os.environ.get("ORCHESTRATOR_API_KEY")

    # Determine fallback models
    fallbacks = []
    fallback_env = os.environ.get("ORCHESTRATOR_FALLBACK_MODELS")
    if fallback_env:
        fallback_list = [f.strip() for f in fallback_env.split(",") if f.strip()]
        for fb_model in fallback_list:
            fallbacks.append({"model": fb_model})
        logger.info(f"Configured fallback models: {fallback_list}")

    # Build constructor args
    kwargs = {}
    if api_base:
        kwargs["api_base"] = api_base
        logger.info(f"Using custom api_base: {api_base}")
    if api_key:
        kwargs["api_key"] = api_key
    if fallbacks:
        kwargs["fallbacks"] = fallbacks

    # Initialize the DSPy Language Model (which natively calls LiteLLM under the hood)
    lm = dspy.LM(model=model, **kwargs)
    
    # Configure it globally in DSPy
    dspy.configure(lm=lm)
    return lm
