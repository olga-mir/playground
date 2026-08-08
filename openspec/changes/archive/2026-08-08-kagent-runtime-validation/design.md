# Design: kagent-runtime-validation

## Approach

This change is **validation-only** — no new manifests, no code changes. The design is
a structured session procedure rather than a software architecture.

## Session sequence

```
task agentic:deploy          # provision apps-dev (or resume if already running)
  └─ Flux reconciles kagent HelmRelease
  └─ All agents reach Ready: True

T4: A2A end-to-end
  ├─ Chain 1: cilium-network-agent → observability-agent / promql-agent
  └─ Chain 2: crossplane-composition-fixer → k8s-agent (cross-namespace)

T5: Cross-team boundary baseline
  ├─ Create team-alpha/stub-agent
  ├─ Attempt call from crossplane-composition-fixer
  ├─ Capture rejection log line
  └─ Delete stub-agent + team-alpha namespace

doc update (optional)
  └─ Append evidence to docs/kagent-a2a-workflow.md
```

## Invocation method discovery

The exact method to send prompts to kagent agents is unknown until the cluster is live.
Try in order:

1. `kagent` CLI if available in PATH on the local machine.
2. Direct HTTP POST to the agent pod via `kubectl exec` (port 8083).
3. kagent UI if exposed via the HTTPRoute (`kagent.kagent-system.svc`).

Document which method worked — this informs the `openfga-kagent-authz-poc` validation
procedure.

## Evidence format

For each test, capture:

```
# Chain/test name
# Command used:
<command>

# Output:
<truncated output showing delegation or rejection>

# Log line:
<exact log line from agent or controller>
```

Paste into `docs/kagent-a2a-workflow.md` under a new `## Validation Evidence` section.
