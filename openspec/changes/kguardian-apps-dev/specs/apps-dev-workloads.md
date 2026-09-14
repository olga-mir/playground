# Spec: apps-dev-workloads

## Overview
kguardian's Controller DaemonSet observes tenant pod traffic and syscalls on every `apps-dev` node. This capability covers what tenant workloads become observable/targetable for once kguardian is running — generating `NetworkPolicy`/`CiliumNetworkPolicy` and `SeccompProfile` YAML from real behavior. kguardian never applies anything to the cluster itself; every scenario below ends with a file on disk for an operator to review.

### Requirement: Traffic observation feeds a per-pod behavioral baseline

**Context:** The Controller runs privileged with `CAP_BPF` on every node and reports flows to the Broker, which stores them in PostgreSQL.

#### Scenario: Controller observes a tenant pod's connections
- **Given** kguardian's Controller DaemonSet is running on every `apps-dev` node
- **When** a tenant pod (e.g. in `team-alpha`) sends or receives a TCP or UDP connection
- **Then** the Controller captures the flow and the Broker records it as part of that pod's baseline, attributing the peer at capture time rather than at generation time

#### Scenario: Generating a CiliumNetworkPolicy from observed traffic
- **Given** a tenant pod has an observed traffic baseline in the Broker
- **When** an operator runs `kubectl kguardian gen netpol <pod> -n <namespace> --type cilium --output-dir ./policies`
- **Then** a `CiliumNetworkPolicy` YAML reflecting only the pod's observed peers is written to `./policies`, and nothing is applied to the cluster automatically (`--dry-run` defaults to `true`)

### Requirement: Syscall observation feeds seccomp profile generation

**Context:** Seccomp capture is tiered; only a `full` capture (the default) yields a profile that is safe to later switch from audit to enforcing.

#### Scenario: Generating a seccomp profile in audit mode
- **Given** the Controller has recorded a `full` syscall trace for a tenant pod
- **When** an operator runs `kubectl kguardian gen seccomp <pod> -n <namespace> --output-dir ./seccomp`
- **Then** a `SeccompProfile` CR is written reflecting the observed syscalls, defaulting to `SCMP_ACT_ERRNO` for unlisted syscalls rather than being pre-applied as enforcing

#### Scenario: Generated policy reflects an incomplete observation window
- **Given** a tenant pod was only exercised over part of its behavior during the observation window (e.g. one code path never ran)
- **When** an operator generates a `NetworkPolicy`, `CiliumNetworkPolicy`, or `SeccompProfile` from that baseline
- **Then** the generated file reflects only what was observed, and the operator is expected to review it before applying or enforcing anything — kguardian does not warn about coverage gaps itself
