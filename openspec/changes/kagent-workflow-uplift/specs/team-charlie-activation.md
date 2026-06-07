# Spec: Team-Charlie Agent Activation

## Goal

Uncomment and activate the `crossplane-composition-fixer` Agent CR so team-charlie has a
live agent that can delegate to `kagent-system/k8s-agent` for Kubernetes operations.

## Agent CR Changes

Uncomment the Agent CR in `kubernetes/tenants/base/team-charlie/kagent-agents.yaml`.
The agent's `tools` entry references `k8s-agent` cross-namespace:

```yaml
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: crossplane-composition-fixer
  namespace: team-charlie
spec:
  modelConfig: claude-model-config
  systemMessage: |
    <existing system message — preserve verbatim>
  memory: ["crossplane-docs-memory"]
  tools:
    - type: Agent
      agent:
        name: k8s-agent
        namespace: kagent-system
```

## k8s-agent allowedNamespaces

For the cross-namespace call to succeed, `k8s-agent` in `kagent-system` must include
`team-charlie` in its `allowedNamespaces`. Confirm the CRD supports this field at v1alpha1;
if the field lives on the Agent spec add an overlay patch, if it is cluster-level RBAC only
then a ClusterRoleBinding subject entry for the team-charlie ServiceAccount suffices.

Current RBAC in `config/rbac.yaml` binds `kagent-system/kagent` SA — a parallel binding for
`team-charlie/kagent` SA to the same ClusterRole gives the SA the read/write verbs needed
for Crossplane resources.

## Acceptance Criteria

- [ ] `crossplane-composition-fixer` Agent CR is present and `Ready` in `team-charlie`.
- [ ] A test prompt routed to `crossplane-composition-fixer` causes it to call `k8s-agent`
      and return Kubernetes resource info (e.g. list Crossplane XRs).
- [ ] `kagent-system/k8s-agent` logs show an inbound A2A call from `team-charlie`.
