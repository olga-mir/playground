# Welcome

A monorepo showcasing modern cloud-native and AI-powered workflows. Built on **Crossplane v2** for platform API abstractions and **FluxCD** for GitOps automation.

Features cutting-edge AI projects including `kgateway` and `kagent` - Kubernetes-native projects designed to enable agentic AI workflows within cloud infrastructure. This repository serves as a playground for exploring the intersection of infrastructure-as-code, AI agents, and Kubernetes-native tooling.

**Architecture**: Multi-cluster setup with automated GitOps deployment using Flux notifications and GitHub Actions.

This AI Assisted project, leveraging Claude Sonnet, Github Copilot, and Gemini Code Assist.

# Tech Stack

| Logo | Name | Description |
|------|------|-------------|
| <img src="https://www.gstatic.com/marketing-cms/assets/images/29/8c/e1f2c0994e87b8d7edf2886f9c02/google-cloud.webp=s96-fcrop64=1,00000000ffffffff-rw" width="30"> | GKE | Google Kubernetes Engine is Google Cloud's managed Kubernetes service that provides a secure, scalable environment for running containerized applications. |
| <img src="https://raw.githubusercontent.com/kubernetes-sigs/gateway-api/dbd2ff92a93e7c8a29bce07cc331e40e6d470efe/site-src/images/logo/logo.svg" width="30"> | Gateway API | Kubernetes Gateway API is a collection of resources that model service networking in Kubernetes, providing expressive, extensible, and role-oriented interfaces. |
| <img src="https://kgateway.dev/feature-api-gateway.svg" width="30"> | kgateway | Kubernetes gateway for AI services, providing a standardized way to connect applications with AI capabilities within the cluster. |
| <img src="https://raw.githubusercontent.com/agentgateway/agentgateway/refs/heads/main/ui/public/favicon.svg" width="30"> | Agent Gateway| Gateway Dataplane for AI workloads (MCP, A2A) |
| <img src="https://raw.githubusercontent.com/cncf/artwork/refs/heads/main/projects/crossplane/icon/color/crossplane-icon-color.svg" width="30"> | Crossplane | An open source Kubernetes add-on that transforms your cluster into a universal control plane, enabling platform teams to build infrastructure abstractions. |
| <img src="https://raw.githubusercontent.com/kagent-dev/kagent/33a48ede61be68c84f6adcfddde09db41aeb1ea7/img/icon-dark.svg" width="30"> | kagent | Kubernetes-native AI agent framework that enables the deployment and management of AI agents within Kubernetes clusters. |
| <img src="https://fluxcd.io/img/logos/flux-horizontal-color.png" width="30"> | FluxCD | GitOps toolkit for Kubernetes that keeps clusters in sync with configuration sources and automates deployments. |
| <img src="https://argo-cd.readthedocs.io/en/stable/assets/logo.png" width="30"> | ArgoCD | :kill-with-fire: This project was using ArgoCD until release TBC |

# Demos

"Demo" is an end-to-end installation or an implementation of an idea. It is similar to a tutorial in concept but typically is a deep-dive and a more detailed view of particular piece of technology.
These demos are found in [Wiki](https://github.com/olga-mir/playground/wiki)

# Infrastructure

This project uses a **hub-and-spoke** architecture with automated cluster provisioning:

1. **kind cluster (local)**: Hub cluster running Crossplane v2 and FluxCD. Provisions GKE clusters via Composite Resources.
2. **GKE mgmt cluster**: Management cluster with Flux, platform services, and AI stack (kagent).
3. **GKE apps-dev cluster**: Applications cluster for tenant workloads.

**GitOps Flow**: Crossplane provisions clusters → Flux detects readiness → GitHub Actions bootstrap Flux → Applications deploy automatically.

Each cluster is managed in its own namespace (`gkecluster-mgmt`, `gkecluster-apps-dev`) with dedicated Flux configurations.

# Deployment

## Prerequisites

### GitHub Repository Secrets

Configure these secrets in your GitHub repository settings (Settings → Secrets and variables → Actions):

```bash
# Workload Identity Federation for GitHub Actions
WIF_PROVIDER=projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/providers/github-provider
WIF_SERVICE_ACCOUNT=github-actions-sa@PROJECT_ID.iam.gserviceaccount.com

# GitHub token for Flux bootstrap (needs repo:write permissions)
FLUX_GITHUB_TOKEN=ghp_your_personal_access_token_here
```

### Enviroment Variables
TODO

## Project Structure and Bootstrap

1. **Crossplane provisions GKE clusters** via kind cluster running Flux
2. **Flux notification controller detects cluster readiness** and triggers GitHub webhook
3. **GitHub Actions workflow authenticates to GCP** using Workload Identity Federation
4. **Workflow bootstraps Flux on the new GKE cluster** with cluster-specific configuration
5. **Flux on GKE cluster syncs platform applications** from this repository

This repository hosts both platform teams and consumer teams configurations with clear separation of concerns.

Refer to [./bootstrap/README.md](./bootstrap/README.md) for detailed explanation of repository structure and deployment flow.

## Platform vs Tenants

- **Platform Products**: Core services like kagent, kgateway, networking components
- **Platform Tenants**: End-user applications and team-specific workloads
- **Flux GitOps**: Automatically syncs both platform services and tenant applications to appropriate clusters

## Connect MCP Servers

```
% task --list | grep mcp
```

Also https://github.com/olga-mir/playground/wiki/ArgoCD-MCP-%E2%80%90-The-Networking-Aspects


## Tasks

Fully automated deployment:

```bash
$ task setup:deploy
```

Everything should be running, all manifests applied by Flux, resources provisioned by Crossplane once the above task finishes.

Uninstall everything:
```bash
$ task setup:cleanup
```

List all available tasks
```bash
$ task --list
```
