# Spec: flux-gitops

## Overview
Wires kguardian into the `apps-dev` cluster using the fleet's established third-party-chart pattern: a dedicated namespace, an OCI `HelmRepository` + `HelmRelease` under `namespaces/base/kguardian/`, a separate CRDs `Kustomization` reconciled ahead of the main platform release (mirroring kagent/litmus/kgateway), and an entry in the `apps-dev` overlay.

### Requirement: kguardian's CRDs are installed ahead of the main release

**Context:** The chart ships `SeccompProfile` and `AuditNetworkPolicy` CRDs. Installing the HelmRelease before these CRDs exist would fail, so CRDs get their own Flux `Kustomization` with a `dependsOn` ordering — the same pattern already used for kagent, litmus, and kgateway.

#### Scenario: CRDs Kustomization reconciles before the platform Kustomization
- **Given** `kubernetes/clusters/apps-dev/kguardian-crds.yaml` defines a Flux `Kustomization` pointed at the chart's CRDs
- **When** Flux reconciles the `apps-dev` cluster
- **Then** the `kguardian-crds` Kustomization completes (both CRDs registered) before the main `platform.yaml` Kustomization — which installs the HelmRelease — via `dependsOn`

### Requirement: kguardian installs via HelmRelease sourced from an OCI HelmRepository

**Context:** kguardian publishes its chart at `oci://ghcr.io/kguardian-dev/charts/kguardian`, matching kagent's OCI `HelmRepository` pattern rather than litmus's HTTP one.

#### Scenario: HelmRelease reconciles successfully
- **Given** `namespaces/base/kguardian/helm/kguardian-helm-repo.yaml` (OCI `HelmRepository`) and `kguardian-release.yaml` (`HelmRelease`, pinned chart version, `install.createNamespace: true`) exist under `namespaces/base/kguardian/`
- **When** `kguardian` is added to `kubernetes/namespaces/overlays/apps-dev/kustomization.yaml`
- **Then** Flux creates the `kguardian` namespace and installs the chart with `telemetry.enabled: false`

#### Scenario: A transient install failure is retried, not left stuck
- **Given** the kguardian `HelmRelease` sets `remediation.retries` on install and upgrade, matching the litmus/kagent convention
- **When** the initial Helm install fails (e.g. a transient delay provisioning the bundled Postgres PVC)
- **Then** Flux retries the install up to the configured retry count instead of leaving the release permanently failed
