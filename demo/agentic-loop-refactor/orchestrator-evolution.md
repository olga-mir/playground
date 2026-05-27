# From "Vibecoding" to Programmed Agents: Rewriting our Kubernetes Orchestrator

When we first built our Kubernetes provisioning orchestrator, it was the definition of "vibecoded." We needed an AI agent to monitor the bootstrapping of a GitOps-driven, multi-cluster environment (using Crossplane and Flux) and troubleshoot the inevitable Catch-22s that occur when declarative systems get stuck.

To get it working quickly, we did what any pragmatic developer would do: we hacked it together. 

Our Python script literally used `subprocess.run(["claude", "-p", ...])` to shell out to the Anthropic desktop CLI. We fed the agent massive dumps of `kubectl` output, crossed our fingers, and used brittle regex to scrape the `stdout` for a JSON response. It was fragile, it was locked into a single vendor's ecosystem, and the agent's "reasoning" was a black box.

But it *worked*. Until we got access to a DGX Spark.

Suddenly, we had massive local compute capable of running Llama-3 70B or Mixtral, but our architecture was hardcoded to an Anthropic CLI wrapper. Furthermore, we wanted to experiment with OpenRouter's vast model marketplace and Vertex AI's enterprise endpoints. 

We realized we needed to evolve our orchestrator from a "prompted script" into a **Programmed Agentic Framework**.

### The New Architecture

```text
[ Orchestrator (DSPy + Pi) ]
          │
          ▼
[ LiteLLM (Python Library) ]  <-- The Universal Translator
          │
    ┌─────┼─────────────────────┐
    │     │                     │
    ▼     ▼                     ▼
[ DGX ] [ OpenRouter ] [ Vertex AI / GCP ]
(vLLM)  (Aggregator)   (Direct Enterprise)
```

Here is how we rebuilt our entire orchestrator using DSPy, LiteLLM, Pi, and Pydantic.

### The New Nervous System: LiteLLM

The first step was severing the hardcoded CLI dependency. We needed a universal router that didn't care if the model was running on our local network, on Google Cloud, or behind an OpenRouter API key.

We integrated **LiteLLM**. With a few lines of code, LiteLLM abstracted away the entire SDK layer. By simply changing an environment variable (`ORCHESTRATOR_MODEL`), we could route the same logic to:
*   `vllm/dgx-spark` (Local)
*   `openrouter/google/gemini-1.5-pro` (Marketplace)
*   `vertex_ai/gemini-1.5-pro` (Enterprise/ADC Auth)

No more swapping SDKs or dealing with different authentication flows. 

### The Brain: From Prompting to Programming with DSPy

In the old system, we wrote massive Markdown files instructing the agent on how to diagnose Kubernetes failures. With **DSPy**, we stopped writing prompts and started defining `Signatures`.

Instead of begging the LLM to format its output correctly, we defined exactly what the inputs and outputs should be:

```python
class AssessPhaseHealth(dspy.Signature):
    """Assess the health of a Kubernetes provisioning phase."""
    
    phase_description = dspy.InputField()
    cluster_state = dspy.InputField()
    
    is_healthy = dspy.OutputField(desc="Boolean indicating if the phase is fully healthy")
    failing_resources = dspy.OutputField(desc="List of resources that are failing")
    recommendation = dspy.OutputField(desc="One of: wait, diagnose, teardown")
```

This was the paradigm shift. DSPy acts as a compiler. It figures out the best way to prompt the underlying model to achieve this signature. Because we had the DGX Spark, we could even use DSPy's optimizers (`teleprompters`) to run hundreds of local simulations, automatically discovering the prompt structure that yielded the most accurate Kubernetes diagnostics.

### The Safety Net: Pydantic & Pi

To inject context into these DSPy modules cleanly, we brought in **Pi** (`earendil-works/pi`). Instead of concatenating Python strings, Pi handled the template management, separating the prompt construction from the application logic. 

Finally, we used **Pydantic** to enforce the DSPy outputs. In the old system, if the LLM hallucinated a weird JSON key, the orchestrator crashed. Now, the LLM's output is cast directly into a strictly typed Pydantic model (`DiagnosticsDecision`). If the model decides to "patch a resource," Pydantic ensures the `namespace`, `name`, and `provider` fields exist and are strings before our Python code ever touches `kubectl`.

### The Result

The transformation was night and day. 

We went from a script that was duct-taped to a CLI tool, to a resilient, typed, programmatic state machine. We can now test a hypothesis using a cheap OpenRouter model, deploy to production using Vertex AI, and run heavy DSPy prompt-optimizations entirely locally on our DGX Spark—all without changing a single line of business logic.

"Vibecoding" got us off the ground, but structured AI engineering—DSPy, LiteLLM, and Pydantic—gave us wings. 
