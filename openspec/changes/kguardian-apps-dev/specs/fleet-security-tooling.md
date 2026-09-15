# Spec: fleet-security-tooling

## Overview
Introduces runtime-derived security policy generation as a new capability in the fleet — previously absent. Covers the parts of kguardian that are new *kinds* of infrastructure for this repo: a bundled stateful database, and the tool's own network/telemetry posture, kept minimal for this iteration.

### Requirement: Broker persists baselines using the chart's bundled PostgreSQL

**Context:** The fleet has no existing CloudNativePG or Cloud SQL pattern. Standing one up is disproportionate for a disposable learning cluster, so this iteration uses the chart's bundled Postgres subchart (`database.enabled: true`, the default) against GKE Standard's default `standard-rwo` StorageClass.

#### Scenario: Broker starts against the bundled database
- **Given** `database.enabled: true` and no `storageClassName` override (using the cluster's default `standard-rwo`)
- **When** the kguardian `HelmRelease` installs
- **Then** the bundled PostgreSQL pod provisions its PVC successfully and the Broker connects and begins storing flow/syscall baselines

### Requirement: No unintended data leaves the cluster

**Context:** The project is cost- and security-aware by default; kguardian's daily telemetry check-in and optional AI Assistant are both external-facing features that should stay off unless explicitly opted into.

#### Scenario: Telemetry check-in is disabled
- **Given** `telemetry.enabled: false` is set in the HelmRelease values
- **When** the Broker runs
- **Then** no daily anonymous version check-in request is made

#### Scenario: Optional AI Assistant remains off
- **Given** the AI Assistant / LLM Bridge is explicitly out of scope for this change
- **When** the kguardian `HelmRelease` is installed
- **Then** `ai.enabled` stays `false` (chart default) and no LLM API key `Secret` is created or required
