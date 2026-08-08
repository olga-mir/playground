# Spec: Cross-Team Boundary Baseline

## Goal

Confirm that namespace isolation blocks cross-team A2A calls and capture the rejection
log line. This documented rejection behaviour is the baseline that OpenFGA will replace
with tuple-driven policy in `openfga-kagent-authz-poc`.

## Setup: stub agent in team-alpha

Create a minimal Agent CR labelled for easy cleanup:

```yaml
# /tmp/team-alpha-stub-agent.yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: stub-agent
  namespace: team-alpha
  labels:
    openfga-baseline-test: "true"
spec:
  declarative:
    modelConfig: claude-model-config
    systemMessage: "Stub agent for namespace isolation testing."
    a2aConfig:
      skills:
        - id: stub
          name: Stub
          description: Stub skill for isolation test
```

Apply:

```bash
kubectl apply -f /tmp/team-alpha-stub-agent.yaml \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev
```

Note: `team-alpha` namespace may not exist — create if needed:

```bash
kubectl get namespace team-alpha \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev 2>/dev/null || \
kubectl create namespace team-alpha \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev
```

## Test: attempt cross-team call

Try to invoke the stub from `crossplane-composition-fixer`. Since stub-agent is not
declared in crossplane-composition-fixer's `spec.declarative.tools`, the kagent
controller should refuse to wire the connection.

If the kagent CLI supports explicit agent targeting:

```bash
CF_POD=$(kubectl get pod -n team-charlie \
  -l app=crossplane-composition-fixer -o jsonpath='{.items[0].metadata.name}' \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev)
kubectl exec -n team-charlie "$CF_POD" \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev -- \
  curl -s -X POST http://localhost:8083/run \
  -H 'Content-Type: application/json' \
  -d '{"message": "Delegate this task to stub-agent in team-alpha namespace."}'
```

## Expected evidence

Controller or agent logs showing rejection:

```bash
CTRL_POD=$(kubectl get pod -n kagent-system \
  -l app=kagent-controller -o jsonpath='{.items[0].metadata.name}' \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev)
kubectl logs "$CTRL_POD" -n kagent-system \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev | \
  grep -i "team-alpha\|denied\|not allowed\|allowedNamespaces\|forbidden"
```

Acceptable outcomes (any one is sufficient):
- kagent controller log: `allowedNamespaces check failed` or similar
- Agent response: "I cannot delegate to agents outside my configured tools"
- HTTP 403 from the A2A endpoint

**Capture the exact log line** — this is what OpenFGA replaces.

## Teardown

```bash
kubectl delete agent stub-agent -n team-alpha \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev
kubectl delete namespace team-alpha \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev
```

## Pass Criteria

- A clear rejection signal (log line, error response, or 403) is captured.
- `crossplane-composition-fixer` does NOT successfully communicate with `stub-agent`.
- The rejection mechanism is documented (which component enforces it and what log it emits).
