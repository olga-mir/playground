import os
import dspy
from orchestrator.llm_router import get_lm

def test_connectivity():
    print("==================================================")
    print("Orchestrator Environment & LLM Connectivity Test")
    print("==================================================")
    
    # Print relevant env vars
    print("Environment Variables:")
    print(f"  ORCHESTRATOR_MODEL:           {os.environ.get('ORCHESTRATOR_MODEL', 'Not Set (Defaulting to vertex_ai/gemini-1.5-pro)')}")
    print(f"  ORCHESTRATOR_API_BASE:        {os.environ.get('ORCHESTRATOR_API_BASE', 'Not Set')}")
    print(f"  ORCHESTRATOR_API_KEY:         {os.environ.get('ORCHESTRATOR_API_KEY', '***' if os.environ.get('ORCHESTRATOR_API_KEY') else 'Not Set')}")
    print(f"  ORCHESTRATOR_FALLBACK_MODELS: {os.environ.get('ORCHESTRATOR_FALLBACK_MODELS', 'Not Set')}")
    print(f"  OPENROUTER_API_KEY:           {'***' if os.environ.get('OPENROUTER_API_KEY') else 'Not Set'}")
    print(f"  ANTHROPIC_API_KEY:            {'***' if os.environ.get('ANTHROPIC_API_KEY') else 'Not Set'}")
    print("--------------------------------------------------")

    try:
        print("Initializing LLM client...")
        lm = get_lm()
        print(f"LM initialized: {lm.model}")
        
        print("Querying LLM with a test prompt...")
        # Since DSPy 3.x, calling the LM instance returns a list of strings
        response = lm("Say 'Kubernetes orchestration active!' in exactly three words.")
        print(f"Response from LLM: {response}")
        print("--------------------------------------------------")
        print("Status: SUCCESS - LLM configuration is functional!")
    except Exception as e:
        print("--------------------------------------------------")
        print(f"Status: FAILED - Could not connect to LLM: {e}")
        import traceback
        traceback.print_exc()
    print("==================================================")

if __name__ == "__main__":
    test_connectivity()
