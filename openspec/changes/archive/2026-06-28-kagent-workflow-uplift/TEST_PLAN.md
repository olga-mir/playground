# Test Plan: kagent A2A Workflow

This document outlines the test procedures for validating the kagent Agent-to-Agent (A2A) configuration after deployment.

**Note:** Replace `<APPS_DEV_CONTEXT>` with your actual apps-dev cluster context (e.g., `gke_<PROJECT_ID>_<REGION>-a_apps-dev`).

## Prerequisites

Ensure the following are deployed and healthy on the `apps-dev` GKE cluster:
- Flux GitOps reconciliation complete
- HelmRelease `kagent` in `kagent-system` namespace is reconciled
- All standalone Agent CRs created and in `Ready` state
- Prometheus accessible at `http://kube-prometheus-stack-prometheus.monitoring:9090` from agent pods
- kagent agents can communicate within `kagent-system` namespace

## T4: A2A End-to-End Demo Test

### T4.1: Cilium Network Agent A2A Delegation

**Objective:** Verify that `cilium-network-agent` can delegate metric queries to `observability-agent` and `promql-agent`.

**Procedure:**

1. Get a running agent pod in `kagent-system`:
   ```bash
   AGENT_POD=$(kubectl get pod -n kagent-system \
     --context <APPS_DEV_CONTEXT> \
     -l app=cilium-network-agent -o jsonpath='{.items[0].metadata.name}')
   ```

2. Send a test prompt that requires metric delegation:
   ```bash
   # Using kagent CLI (if available) or direct API call
   PROMPT="Check Cilium node health on apps-dev and summarise any network policy drops in the last hour."
   
   # Method 1: Direct kubectl exec (if agent has a CLI interface)
   kubectl exec -it $AGENT_POD -n kagent-system --context <apps-dev> -- \
     kagent --prompt "$PROMPT"
   
   # Method 2: API call to agent endpoint
   kubectl port-forward svc/cilium-network-agent 8080:8080 -n kagent-system \
     --context <APPS_DEV_CONTEXT> &
   
   curl -X POST http://localhost:8080/api/agents/prompt \
     -H "Content-Type: application/json" \
     -d '{"prompt": "'"$PROMPT"'"}'
   ```

3. **Verification:**
   - Agent should complete the query successfully
   - Response should indicate delegation to observability-agent and/or promql-agent
   - Check agent logs for A2A delegation traces:
     ```bash
     kubectl logs -f $AGENT_POD -n kagent-system \
       --context <APPS_DEV_CONTEXT> | grep -i "delegate\|a2a\|promql"
     ```
   - Expected log pattern: `A2A delegation to promql-agent` or `delegating metric query to observability-agent`

**Success Criteria:**
- ✓ Prompt completes without timeout or 5xx errors
- ✓ Response contains network policy analysis
- ✓ Logs show explicit delegation to observability or promql agents
- ✓ No connection errors between agents

### T4.2: Crossplane Composition Fixer A2A Delegation

**Objective:** Verify that `crossplane-composition-fixer` in `team-charlie` can delegate to `k8s-agent` in `kagent-system`.

**Procedure:**

1. Get the agent pod in `team-charlie`:
   ```bash
   AGENT_POD=$(kubectl get pod -n team-charlie \
     --context <APPS_DEV_CONTEXT> \
     -l app=crossplane-composition-fixer -o jsonpath='{.items[0].metadata.name}')
   ```

2. Send a test prompt that requires k8s-agent delegation:
   ```bash
   PROMPT="List all Crossplane XRs in the cluster and report their status."
   
   # Using direct API or CLI
   kubectl port-forward svc/crossplane-composition-fixer 8080:8080 -n team-charlie \
     --context <APPS_DEV_CONTEXT> &
   
   curl -X POST http://localhost:8080/api/agents/prompt \
     -H "Content-Type: application/json" \
     -d '{"prompt": "'"$PROMPT"'"}'
   ```

3. **Verification:**
   - Agent should query Crossplane resources successfully
   - Response should contain a list of XRs with their status
   - Check agent logs for cross-namespace A2A delegation:
     ```bash
     kubectl logs -f $AGENT_POD -n team-charlie \
       --context <APPS_DEV_CONTEXT> | grep -i "k8s-agent\|xr\|crossplane"
     ```
   - Check k8s-agent logs for inbound A2A request from team-charlie:
     ```bash
     K8S_POD=$(kubectl get pod -n kagent-system \
       --context <APPS_DEV_CONTEXT> \
       -l app=k8s-agent -o jsonpath='{.items[0].metadata.name}')
     kubectl logs -f $K8S_POD -n kagent-system \
       --context <APPS_DEV_CONTEXT> | grep -i "team-charlie\|a2a\|request"
     ```

**Success Criteria:**
- ✓ Prompt completes and returns Crossplane XR status
- ✓ crossplane-composition-fixer logs show delegation to k8s-agent
- ✓ k8s-agent logs show inbound A2A request from team-charlie namespace
- ✓ No authorization or RBAC errors in logs

### T4.3: Record Session Traces

**Objective:** Document the A2A delegation flow for #103 handoff.

**Procedure:**

1. Capture logs from all three agents during T4.1 and T4.2:
   ```bash
   # Export logs for handoff
   kubectl logs --since=5m -n kagent-system \
     --context <APPS_DEV_CONTEXT> \
     -l app=cilium-network-agent > cilium-logs.txt
   
   kubectl logs --since=5m -n kagent-system \
     --context <APPS_DEV_CONTEXT> \
     -l app=observability-agent > observability-logs.txt
   
   kubectl logs --since=5m -n team-charlie \
     --context <APPS_DEV_CONTEXT> \
     -l app=crossplane-composition-fixer > crossplane-fixer-logs.txt
   ```

2. Export agent CR specs for documentation:
   ```bash
   kubectl get agent cilium-network-agent -n kagent-system \
     --context <APPS_DEV_CONTEXT> \
     -o yaml > cilium-network-agent-spec.yaml
   
   kubectl get agent crossplane-composition-fixer -n team-charlie \
     --context <APPS_DEV_CONTEXT> \
     -o yaml > crossplane-composition-fixer-spec.yaml
   ```

3. Create a summary document with:
   - Timestamps of A2A delegation calls
   - Log excerpts showing agent-to-agent communication
   - Error messages (if any) and resolutions
   - Agent specifications confirming tool wiring

**Success Criteria:**
- ✓ Logs clearly show A2A delegation flow
- ✓ Agent specs confirm tool definitions
- ✓ All traces organized for #103 handoff

---

## T5: Cross-Team Boundary Smoke Test

### T5.1: Create Test Stub Agent (if needed)

**Objective:** Verify cross-team isolation by attempting (and failing) to invoke an agent in another team namespace.

**Procedure:**

1. Check if `team-alpha` namespace has agents:
   ```bash
   kubectl get agent -n team-alpha \
     --context <APPS_DEV_CONTEXT> 2>/dev/null || echo "No agents found"
   ```

2. If no agents exist, create a minimal stub:
   ```bash
   cat <<'EOF' | kubectl apply -f - --context <APPS_DEV_CONTEXT>
   apiVersion: kagent.dev/v1alpha1
   kind: Agent
   metadata:
     name: stub-agent
     namespace: team-alpha
     labels:
       openfga-baseline-test: "true"
   spec:
     modelConfig: claude-model-config
     systemMessage: "Stub agent for baseline testing"
   EOF
   ```

3. Verify stub creation:
   ```bash
   kubectl get agent stub-agent -n team-alpha \
     --context <APPS_DEV_CONTEXT> -o yaml
   ```

### T5.2: Attempt Cross-Team Boundary Violation

**Objective:** Demonstrate that `team-charlie` cannot access `team-alpha` agents due to namespace isolation.

**Procedure:**

1. Send a prompt to `crossplane-composition-fixer` that asks it to delegate to the team-alpha stub:
   ```bash
   PROMPT="Query the stub-agent in team-alpha namespace and report its status."
   
   # Send prompt to crossplane-composition-fixer
   AGENT_POD=$(kubectl get pod -n team-charlie \
     --context <APPS_DEV_CONTEXT> \
     -l app=crossplane-composition-fixer -o jsonpath='{.items[0].metadata.name}')
   
   kubectl port-forward svc/crossplane-composition-fixer 8080:8080 -n team-charlie \
     --context <APPS_DEV_CONTEXT> &
   
   curl -X POST http://localhost:8080/api/agents/prompt \
     -H "Content-Type: application/json" \
     -d '{"prompt": "'"$PROMPT"'", "target_agent": "stub-agent", "target_namespace": "team-alpha"}'
   ```

2. **Expected Result:** Agent should reject the delegation with a 403 Forbidden or similar authorization error.

### T5.3: Document Rejection Error

**Objective:** Capture the exact error message for OpenFGA baseline documentation.

**Procedure:**

1. Extract the error from the agent's response:
   ```bash
   # The error should indicate:
   # - Namespace isolation enforcement
   # - Authorization denial (403)
   # - RBAC denial (if applicable)
   ```

2. Check `kagent-controller` logs for rejection:
   ```bash
   CONTROLLER_POD=$(kubectl get pod -n kagent-system \
     --context <APPS_DEV_CONTEXT> \
     -l app=kagent-controller -o jsonpath='{.items[0].metadata.name}')
   
   kubectl logs $CONTROLLER_POD -n kagent-system \
     --context <APPS_DEV_CONTEXT> | grep -i "denied\|forbidden\|team-alpha"
   ```

3. Expected log pattern:
   ```
   A2A delegation denied: team-charlie/kagent SA not allowed in team-alpha
   Reason: allowedNamespaces [kagent-system] does not include team-alpha
   ```

4. Document the exact error message and log line for #103:
   - Rejection mechanism: (namespace isolation, RBAC, allowedNamespaces field)
   - Error code: (403, 401, etc.)
   - Log timestamp and line

**Success Criteria:**
- ✓ Delegation attempt is rejected with explicit error
- ✓ Error indicates namespace isolation (not timeout or silent failure)
- ✓ Controller logs show the rejection decision
- ✓ Error message is clear and actionable for OpenFGA baseline

### T5.4: Cleanup (Optional)

**Procedure:**

If the stub agent was created for testing, remove it after verification:

```bash
kubectl delete agent stub-agent -n team-alpha \
  --context <APPS_DEV_CONTEXT>
```

Or keep it behind the feature label for #103 testing:

```bash
# Leave the agent in place with the openfga-baseline-test label
# for continued baseline testing during #103 implementation
```

---

## Troubleshooting

### Agent Pod Not Ready

```bash
kubectl get pod -n kagent-system --context <APPS_DEV_CONTEXT>
kubectl describe pod <agent-pod> -n kagent-system --context <APPS_DEV_CONTEXT>
kubectl logs <agent-pod> -n kagent-system --context <APPS_DEV_CONTEXT>
```

### Prometheus Unreachable

```bash
# Test from agent pod
kubectl exec -it <agent-pod> -n kagent-system \
  --context <APPS_DEV_CONTEXT> -- \
  curl -v http://kube-prometheus-stack-prometheus.monitoring:9090/-/healthy
```

### A2A Call Timeout

- Check network policies allow communication between namespaces
- Verify agent tool references are correct (name and namespace fields)
- Check RBAC bindings permit ServiceAccounts across namespaces

### Namespace Isolation Not Enforced

- Verify `allowedNamespaces` field on k8s-agent (or other agents)
- Check RBAC bindings don't grant excessive cross-namespace permissions
- Review kagent-controller logs for delegation decisions
