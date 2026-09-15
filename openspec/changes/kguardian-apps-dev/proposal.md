# Proposal: kguardian-apps-dev

## Summary
Install [kguardian](https://github.com/kguardian-dev/kguardian) on the `apps-dev` GKE cluster via the standard Flux HelmRelease pattern. kguardian uses eBPF to observe real pod traffic and syscalls, then generates least-privilege `NetworkPolicy`/`CiliumNetworkPolicy` and `SeccompProfile` YAML from what tenant workloads actually do — giving hands-on experience with runtime-derived security policy generation on top of the fleet's existing Cilium/Dataplane V2 CNI.

## Problem
`apps-dev` currently has no NetworkPolicy, CiliumNetworkPolicy, or seccomp enforcement of any kind — tenant workloads run fully open on the pod network with the default (unconfined) syscall profile. There's also no tooling in the fleet today that derives policy from observed runtime behavior rather than hand-authored rules, which is the more realistic, prod-like way platform teams actually build least-privilege policy. This is a gap relative to the project's stated aim of prod-like solutions for a Kubernetes/platform-engineering learning environment.

## Proposed Solution
Install kguardian on `apps-dev` following the same third-party-chart recipe already used for Litmus (closest analog: ships its own CRDs, needs a dedicated namespace):

- New `kubernetes/namespaces/base/kguardian/` directory: `namespace.yaml` + `helm/{kguardian-helm-repo.yaml, kguardian-release.yaml}` (OCI `HelmRepository` pointed at `oci://ghcr.io/kguardian-dev/charts/kguardian`, mirroring kagent's OCI pattern rather than litmus's HTTP one).
- A `kguardian-crds` Flux Kustomization (`kubernetes/clusters/apps-dev/kguardian-crds.yaml`) for the chart's CRDs (`SeccompProfile`, `AuditNetworkPolicy`), wired via `dependsOn` ahead of the main `platform.yaml` Kustomization — same ordering used for kagent/litmus/kgateway CRDs.
- Add `kguardian` to `kubernetes/namespaces/overlays/apps-dev/kustomization.yaml`.
- Use the chart's **bundled PostgreSQL subchart** (`database.enabled: true`, the default) for the Broker's storage. The fleet has no CloudNativePG or Cloud SQL pattern to reuse, and standing one up is disproportionate for a disposable cluster; GKE Standard's default `standard-rwo` StorageClass should satisfy the PVC without extra provisioning.
- Enable `CiliumNetworkPolicy` output mode (`-t cilium` on the CLI, or as the default policy type) since Dataplane V2 is already the cluster's CNI.
- Set `telemetry.enabled: false` to disable the daily anonymous version check-in, consistent with the project's security-aware defaults.
- Leave the optional AI Assistant / LLM Bridge component **disabled** for this iteration (see Out of Scope).

## Capabilities Affected
- `apps-dev-workloads` — tenant pods become observable/targetable for generated NetworkPolicy and SeccompProfile
- `flux-gitops` — new HelmRepository, HelmRelease, and CRDs Kustomization added to the apps-dev overlay
- `fleet-security-tooling` — new capability: runtime-derived security policy generation (previously absent from the fleet)

## Impact & Risks
- **Improvement:** hands-on operation of an eBPF-based runtime security tool, and a path to actual least-privilege NetworkPolicy/SeccompProfile coverage on `apps-dev` tenant workloads (kguardian only generates files; applying them is a separate, deliberate step).
- **Risk — privileged DaemonSet:** the Controller runs with `securityContext.privileged: true` + `CAP_BPF` on every node. Not blocked at the cluster level since `apps-dev` is GKE Standard (`enableAutopilot: false`), not Autopilot, and there is currently no NetworkPolicy/PSA/OPA/Kyverno enforcement to work around — but it does broaden the node-level attack surface for as long as the cluster is up. Mitigated by the fleet's disposable, per-session provisioning model.
- **Risk — kernel floor:** requires Linux kernel 6.2+ on every node. The Crossplane composition doesn't currently pin `imageType`, so nodes default to COS_CONTAINERD on the `RAPID` release channel — expected to satisfy this, but must be confirmed live (`kubectl get nodes -o wide` / check kernel version) after the next `task setup:deploy`, since no GKE cluster is currently provisioned to verify against.
- **Risk — new stateful workload:** the bundled Postgres subchart is the fleet's first in-cluster stateful/PVC-backed workload. No existing backup/DR story exists or is needed here, since state is disposable by design — but this is a new pattern for the repo to carry forward if reused elsewhere.
- **Risk — license scope:** kguardian is BSL 1.1 — free for development/testing/evaluation/non-production/non-commercial use, converting to Apache 2.0 in 2029. Fine for this personal, non-production learning cluster; would need reassessment if ever used commercially.
- **Estimated effort:** small-to-medium. The Flux wiring itself is a well-worn pattern (copy litmus/kagent), but this is the fleet's first CRD-shipping *and* first Postgres-needing third-party tool, so the CRDs bootstrap ordering and PVC/StorageClass behavior are the most likely sources of iteration.

## Out of Scope
- Enabling the optional AI Assistant / LLM Bridge component (natural-language querying via an Anthropic/OpenAI/Gemini key) — possible future follow-up.
- Installing the client-side `kubectl kguardian` CLI plugin — that's a local dev-machine step (`quick-install.sh`), not a cluster manifest change.
- Applying any of kguardian's generated NetworkPolicy/CiliumNetworkPolicy/SeccompProfile output to actually enforce policy — kguardian only writes files for review; enforcement is a separate, later decision.
- Migrating to CloudNativePG or an external/managed Postgres — using the chart's bundled Postgres for this iteration.
- Installing kguardian on `control-plane` or the local `kind` cluster — `apps-dev` only.
