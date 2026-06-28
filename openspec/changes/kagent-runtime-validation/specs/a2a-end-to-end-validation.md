# Spec: A2A End-to-End Validation

## Goal

Confirm that the two A2A delegation chains work at runtime on a live apps-dev cluster.
Capture log traces as evidence for the OpenFGA baseline.

## Chain 1: cilium-network-agent → observability/promql agents

### Test prompt

```
kagent run --agent cilium-network-agent --namespace kagent-system \
  "Check Cilium node health on apps-dev and summarise any network policy drops in the last hour."
```

Or via kubectl exec if kagent CLI is unavailable:

```bash
AGENT_POD=$(kubectl get pod -n kagent-system \
  -l app=cilium-network-agent -o jsonpath='{.items[0].metadata.name}' \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev)
# Send prompt via agent HTTP API (port 8083)
kubectl exec -n kagent-system "$AGENT_POD" \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev -- \
  curl -s -X POST http://localhost:8083/run \
  -H 'Content-Type: application/json' \
  -d '{"message": "Check Cilium node health and summarise any network policy drops in the last hour."}'
```

### Expected evidence

Agent logs show delegation to at least one downstream agent:

```
kubectl logs -n kagent-system "$AGENT_POD" \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev | \
  grep -i "observability\|promql\|delegate\|a2a\|tool_call"
```

Acceptable outcome: either delegation trace in logs OR a final response that contains
metrics/PromQL output (proving the downstream agent was called).

## Chain 2: crossplane-composition-fixer → k8s-agent (cross-namespace)

### Test prompt

```bash
CF_POD=$(kubectl get pod -n team-charlie \
  -l app=crossplane-composition-fixer -o jsonpath='{.items[0].metadata.name}' \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev)
kubectl exec -n team-charlie "$CF_POD" \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev -- \
  curl -s -X POST http://localhost:8083/run \
  -H 'Content-Type: application/json' \
  -d '{"message": "List all Crossplane XRs in the cluster and report their status."}'
```

### Expected evidence

Log line in `crossplane-composition-fixer` showing outbound A2A call to `k8s-agent`:

```bash
kubectl logs -n team-charlie "$CF_POD" \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev | \
  grep -i "k8s-agent\|delegate\|tool_call\|a2a"
```

And corresponding inbound log in `k8s-agent`:

```bash
K8S_POD=$(kubectl get pod -n kagent-system \
  -l app=k8s-agent -o jsonpath='{.items[0].metadata.name}' \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev)
kubectl logs -n kagent-system "$K8S_POD" \
  --context gke_${PROJECT_ID}_${REGION}-a_apps-dev | \
  grep -i "team-charlie\|request\|a2a"
```

## Pass Criteria

- At least one log line per chain demonstrating delegation occurred.
- Final response is coherent (not an error).
- No `Ready: False` on any agent during the test.
