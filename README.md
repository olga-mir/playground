# Playground

A monorepo showcasing modern cloud-native and AI-powered workflows. Built on **Crossplane v2** for platform API abstractions and **FluxCD** for GitOps automation. Serves as a playground for exploring the intersection of infrastructure-as-code, AI agents, and Kubernetes-native tooling.

Write-ups and demos: [Repo's Wiki](https://github.com/olga-mir/playground/wiki) · [demo/](./demo)

# Tech Stack

| Logo | Name | Description | Project Version |
|------|------|-------------|-----------------|
| <img src="https://www.gstatic.com/marketing-cms/assets/images/29/8c/e1f2c0994e87b8d7edf2886f9c02/google-cloud.webp=s96-fcrop64=1,00000000ffffffff-rw" width="30"> | GKE | Google Kubernetes Engine is Google Cloud's managed Kubernetes service | 1.34.1 |
| <img src="https://raw.githubusercontent.com/kubernetes-sigs/gateway-api/dbd2ff92a93e7c8a29bce07cc331e40e6d470efe/site-src/images/logo/logo.svg" width="30"> | Gateway API | Kubernetes Gateway API is a collection of resources that model service networking in Kubernetes, providing expressive, extensible, and role-oriented interfaces. | [v1.5.1](https://github.com/kubernetes-sigs/gateway-api/releases/tag/v1.5.1) |
| <img src="https://kgateway.dev/feature-api-gateway.svg" width="30"> | kgateway | Kubernetes gateway for AI services, providing a standardized way to connect applications with AI capabilities within the cluster. | [v2.2.2](https://github.com/kgateway-dev/kgateway/releases/tag/v2.2.2) |
| <img src="https://raw.githubusercontent.com/agentgateway/agentgateway/refs/heads/main/ui/public/favicon.svg" width="30"> | Agent Gateway| Gateway Dataplane for AI workloads (MCP, A2A) | [v1.0.1](https://github.com/agentgateway/agentgateway/releases/tag/v1.0.1) |
| <img src="https://raw.githubusercontent.com/cncf/artwork/refs/heads/main/projects/crossplane/icon/color/crossplane-icon-color.svg" width="30"> | Crossplane | Open-source Kubernetes add-on that lets you provision and manage cloud infrastructure and external services using Kubernetes-style APIs and declarative configuration. | [v2.2.0](https://github.com/crossplane/crossplane/releases/tag/v2.2.0) |
| <img src="https://raw.githubusercontent.com/kagent-dev/kagent/33a48ede61be68c84f6adcfddde09db41aeb1ea7/img/icon-dark.svg" width="30"> | kagent | Kubernetes-native AI agent framework that enables the deployment and management of AI agents within Kubernetes clusters. | [v0.8.4](https://github.com/kagent-dev/kagent/releases/tag/v0.8.4) |
| <img src="https://raw.githubusercontent.com/cncf/artwork/88fa3f88ea2e4bf3e4941be8dc797b6d860c9ade/projects/flux/icon/color/flux-icon-color.svg" width="30"> | FluxCD | GitOps toolkit for Kubernetes that keeps clusters in sync with configuration sources and automates deployments. | [v2.8.3](https://github.com/fluxcd/flux2/releases/tag/v2.8.3) |
| <img src="https://raw.githubusercontent.com/cncf/artwork/refs/heads/main/projects/litmus/icon/color/litmus-icon-color.svg" width="30"> | LitmusChaos | Cloud-native chaos engineering framework for Kubernetes that helps teams find weaknesses in their deployments through controlled chaos experiments. | [v3.27.0](https://github.com/litmuschaos/litmus-helm/releases/tag/litmus-agent-3.27.0) |

# Architecture

Three-cluster hub-and-spoke fleet, provisioned in order:

```
kind (local bootstrap)
  └─ provisions → GKE control-plane   (Crossplane + Flux + platform services)
                    └─ provisions → GKE apps-dev   (tenant workloads)
```

- **Crossplane v2** handles GKE cluster provisioning (no claims — direct namespace-scoped XRs)
- **Flux GitOps** manages everything on each cluster once bootstrapped
- **GitHub Actions** bootstraps Flux on new GKE clusters, triggered by Flux notifications

# AI Orchestrator

The provisioning pipeline is driven by a **Claude-powered agentic loop** that monitors, diagnoses, and fixes the cluster fleet without human intervention:

```
task agentic:deploy
        │
        ├─ bootstrap-control-plane-cluster.sh  (background)
        │
        └─ phase loop  [bootstrap → control-plane → apps-dev]
             ├─ collect kubectl state
             ├─ phase-checker agent  →  healthy | wait | diagnose | teardown
             └─ diagnostics agent   →  fix_forward | teardown | escalate
                  fix_forward: edits manifests, commits to develop, waits for Flux to reconcile
```

Two Claude sub-agents drive the loop:

- **phase-checker** — evaluates cluster state against healthy criteria for the current phase; returns a structured JSON verdict
- **diagnostics** — investigates failures, reads the mission context, makes targeted manifest edits, and returns a commit-ready fix

All cluster changes go through git → Flux. Direct `kubectl` writes are blocked by a `PreToolUse` hook. The orchestrator tracks error signatures and escalates after 3 identical failures or 2 full teardown cycles.

→ Full reference: [docs/orchestrator.md](./docs/orchestrator.md)

# Deployment

## Prerequisites

- Access to a GCP account with sufficient permissions
- Tools: `gcloud`, `flux`, `kubectl`, `task`, `uv`, Claude Code (`claude` CLI)
- GitHub organisation or personal account

See [docs/github-integration.md](./docs/github-integration.md) for GCP OIDC / GitHub Actions setup.

## Running

```bash
# Scripted deploy (no AI)
task setup:deploy

# Agentic deploy — same goal, AI-monitored and self-fixing
task agentic:deploy

# Resume agentic deploy from a specific phase (cluster already exists)
task agentic:resume PHASE=control

# Tear everything down
task setup:cleanup
```

→ Diagnostics, load tests, and performance experiments: [docs/operations.md](./docs/operations.md)

# Domain docs

| Doc | Covers |
|-----|--------|
| [docs/orchestrator.md](./docs/orchestrator.md) | AI orchestrator loop, phases, agent prompts, escalation logic |
| [docs/infrastructure.md](./docs/infrastructure.md) | Crossplane, GKE, kind setup, provisioning flow |
| [docs/flux-gitops.md](./docs/flux-gitops.md) | Kustomize structure, Flux quirks, image automation |
| [docs/github-integration.md](./docs/github-integration.md) | GitHub App auth, Actions workflows, notifications |
| [docs/tenants.md](./docs/tenants.md) | Tenant onboarding, multi-repo GitOps, image promotion |
| [docs/upgrade-versions.md](./docs/upgrade-versions.md) | Weekly automated version upgrades |
| [docs/operations.md](./docs/operations.md) | Fleet health check, key commands, load testing |
