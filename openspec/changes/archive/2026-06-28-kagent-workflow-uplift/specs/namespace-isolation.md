# Spec: Cross-Team Namespace Isolation

## Goal

Establish and verify that agent namespace boundaries enforce team isolation: team-charlie can
reach platform agents in `kagent-system`, but cannot reach agents in other tenant namespaces
(e.g. a hypothetical `team-alpha/some-agent`). This is the behavioural baseline OpenFGA will
later enforce via tuple-driven policy.

## Expected Allowed Path

```
team-charlie/crossplane-composition-fixer  →  kagent-system/k8s-agent   ✓ allowed
```

Mechanism: `k8s-agent.allowedNamespaces` includes `team-charlie` (or `All` for platform
agents), AND the `team-charlie/kagent` ServiceAccount has the necessary RBAC to make the
A2A HTTP call.

## Expected Blocked Path

```
team-charlie/crossplane-composition-fixer  →  team-alpha/<any-agent>   ✗ blocked
```

Mechanism: `team-alpha` agents' `allowedNamespaces` does not include `team-charlie`, and
the kagent controller rejects the delegation attempt. No RBAC binding exists between
`team-charlie/kagent` SA and `team-alpha` namespace resources.

## Smoke Test Procedure

1. Attempt to invoke `team-alpha/some-agent` from a test prompt sent to
   `crossplane-composition-fixer`. Document the error returned (expected: 403 or equivalent
   A2A rejection).
2. Confirm the rejection appears in the `kagent-controller` logs, not just silently fails.
3. Record the exact error message — this becomes the baseline assertion for the OpenFGA POC.

## Acceptance Criteria

- [ ] Allowed path (→ k8s-agent) verified working per team-charlie-activation spec.
- [ ] Blocked path rejection is confirmed with explicit error (not timeout/silent failure).
- [ ] Error message and log line documented in the tasks artifact for #103 handoff.

## Notes

If team-alpha has no agents deployed, create a minimal stub Agent CR for test purposes only,
clearly labelled `openfga-baseline-test: "true"` so it can be cleaned up after #103.
