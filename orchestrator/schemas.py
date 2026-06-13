from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class PhaseHealthVerdict(BaseModel):
    is_healthy: bool = Field(
        description="True if the current phase meets all health criteria and has no failing resources."
    )
    recommendation: str = Field(
        description="The recommended next action: 'proceed' (healthy and ready), 'wait' (reconciliation/provisioning in progress), 'diagnose' (failures found needing troubleshooting), or 'teardown' (unrecoverable state)."
    )
    problem_domain: str = Field(
        description="The domain of the failure if unhealthy: 'crossplane', 'flux', 'github-actions', or 'unknown'. Empty if is_healthy is True."
    )
    failing_resources: List[Dict[str, str]] = Field(
        default=[],
        description="List of failing resources, each with 'kind', 'name', 'namespace', and 'error' description."
    )
    analysis: str = Field(
        description="Engineering analysis explaining the current cluster state and justifying the verdict."
    )

class DiagnosticsDecision(BaseModel):
    rationale: str = Field(
        description="Detailed technical reasoning justifying the chosen action."
    )
    confidence: float = Field(
        description="Confidence score in the diagnostics verdict between 0.0 and 1.0."
    )
    action: str = Field(
        description="The chosen diagnostic action: 'retry' (run remedial steps / reconciliation), 'teardown' (recreate the cluster), or 'escalate' (raise to human)."
    )
