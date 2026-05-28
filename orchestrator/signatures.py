import dspy
from orchestrator.schemas import PhaseHealthVerdict, DiagnosticsDecision

class AssessPhaseHealth(dspy.Signature):
    """
    Assess the health of the Kubernetes cluster for the current provisioning phase.
    Analyze the phase requirements and health criteria against the collected kubectl cluster state.
    """
    phase_description: str = dspy.InputField(
        desc="Markdown description of the requirements and health criteria for the current phase."
    )
    cluster_state: str = dspy.InputField(
        desc="The collected Kubernetes cluster state snapshot (kubectl outputs, resource statuses, events, etc.)."
    )
    
    verdict: PhaseHealthVerdict = dspy.OutputField(
        desc="Structured health verdict including status, recommended action, and problem domain."
    )

class DiagnoseFailure(dspy.Signature):
    """
    Diagnose a provisioning or reconciliation failure on the Kubernetes cluster.
    Review the phase context, the active errors discovered, and the collected cluster state
    to decide on the best remediation path (retry/remediate, teardown/recreate, or escalate).
    """
    phase_name: str = dspy.InputField(
        desc="The name of the current provisioning phase (e.g. bootstrap, control-plane, apps-dev)."
    )
    errors: str = dspy.InputField(
        desc="List or summary of errors and failing resources identified during phase assessment."
    )
    cluster_state: str = dspy.InputField(
        desc="The collected Kubernetes cluster state snapshot (kubectl outputs, resource statuses, events, etc.)."
    )
    
    decision: DiagnosticsDecision = dspy.OutputField(
        desc="Structured diagnostics decision including rationale, confidence score, and remediation action."
    )
