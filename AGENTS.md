# Project purpose

A learning and exploration platform for experienced Kubernetes and Platform Engineers. Aims for prod-like solutions while remaining fully disposable — provisioned at the start of a session, torn down at the end. All operations must be captured in manifests, scripts, or Taskfiles. Runs in a personal GCP account: be cost- and security-aware.

# Critical rules

- **Never** proactively create `.md` or README files — only when explicitly asked
- **Never** commit project IDs or other semi-sensitive values
- Use `git mv` (not `mv`) for versioned files
- Always place a newline at the end of files
- Validate Taskfile changes with `yq` before saving
- Pass `--context` inline on every `kubectl` command — never as a separate step; combine related operations into one command to minimise approval prompts

# Architecture overview

Three-cluster hub-and-spoke fleet, provisioned in order:

```
kind (local bootstrap)
  └─ provisions → GKE control-plane   (Crossplane + Flux + platform services)
                    └─ provisions → GKE apps-dev   (tenant workloads)
```

- **Crossplane v2** handles GKE cluster provisioning (no claims — direct namespace-scoped XRs)
- **Flux GitOps** manages everything on each cluster once bootstrapped
- **GitHub Actions** bootstraps Flux on new GKE clusters, triggered by Flux notifications

### Cluster contexts

| Short name | kubeconfig context |
|---|---|
| `kind` | `kind-kind-test-cluster` |
| `control-plane` | `gke_${PROJECT_ID}_${REGION}-a_control-plane` |
| `apps-dev` | `gke_${PROJECT_ID}_${REGION}-a_apps-dev` |

### Key entry points

| Task | Command |
|---|---|
| Full deploy (orchestrated) | `task agentic:deploy` |
| Full deploy (raw script) | `bootstrap/bootstrap-control-plane-cluster.sh` |
| Resume from phase | `task agentic:resume PHASE=control` |
| Validate kustomize | `task validate:kustomize-build` |
| Fleet health check | `bootstrap/scripts/check-fleet-health.sh` |

# Domain docs

Deep-dive context for specific areas — read the relevant doc when working in that domain:

- **[Infrastructure & Cluster Provisioning](docs/infrastructure.md)** — Crossplane, GKE, kind setup, provisioning flow
- **[Flux & GitOps](docs/flux-gitops.md)** — Kustomize structure, known Flux quirks, debugging, image automation
- **[GitHub Integration](docs/github-integration.md)** — GitHub App auth, Actions workflows, notifications
- **[Tenants](docs/tenants.md)** — Tenant onboarding, multi-repo GitOps, image promotion
- **[Version Upgrades](docs/upgrade-versions.md)** — Weekly automated upgrades: how the scan works, adding new components, known quirks
- **[Orchestrator](docs/orchestrator.md)** — Automated provisioning pipeline: phases, agent prompts, escalation logic, guardrails, snapshot artifacts
- **[Operations](docs/operations.md)** — Fleet health check, key task commands, load testing and performance experiments

# Variables

Env vars in `.setup-env` are sourced in the working terminal but are not accessible to agents. Required vars are documented in each domain doc.
