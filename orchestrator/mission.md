Provision the full fleet (kind → control-plane → apps-dev) to healthy so the deferred
kagent runtime validation can run. See `openspec/changes/kagent-runtime-validation/` for
the session goals: capture A2A delegation evidence (T4) and the cross-namespace rejection
baseline (T5). Those validation steps run manually after provisioning — the orchestrator's
job ends when all three phases are healthy, including the kagent workloads on apps-dev.

This is also the first live run of the DSPy orchestrator; prefer conservative decisions
over clever fixes.

Guardrails:

- If credentials, secrets, or resource names (VPC, subnets, project IDs) are missing —
  DO NOT attempt to fix or invent them. Escalate immediately, explaining what is missing.
- All manifest fixes go through git commit to `develop` and Flux reconciliation. Live
  kubectl writes are reserved for the known fast-path patterns only.
