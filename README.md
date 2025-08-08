# Welcome

A monorepo containing experimental mini-demos showcasing modern cloud-native and AI-powered workflows. Built on Crossplane for platform API abstractions and infrastructure orchestration, with GitOps practices for deployment automation.
It includes cutting-edge AI projects such as `kgateway` and `kagent` - emerging Kubernetes-native projects designed to enable agentic AI workflows within cloud infrastructure.
This repository serves as a playground for exploring the intersection of infrastructure-as-code, AI agents, and Kubernetes-native tooling.

This AI Assisted project, leveraging Claude Sonnet/Opus, Github Copilot with GPT 4.1, Gemini Code Assist.

# Tech Stack

| Logo | Name | Description |
|------|------|-------------|
| <img src="https://www.gstatic.com/marketing-cms/assets/images/29/8c/e1f2c0994e87b8d7edf2886f9c02/google-cloud.webp=s96-fcrop64=1,00000000ffffffff-rw" width="30"> | GKE | Google Kubernetes Engine is Google Cloud's managed Kubernetes service that provides a secure, scalable environment for running containerized applications. |
| <img src="https://raw.githubusercontent.com/kubernetes-sigs/gateway-api/dbd2ff92a93e7c8a29bce07cc331e40e6d470efe/site-src/images/logo/logo.svg" width="30"> | Gateway API | Kubernetes Gateway API is a collection of resources that model service networking in Kubernetes, providing expressive, extensible, and role-oriented interfaces. |
| <img src="https://kgateway.dev/feature-api-gateway.svg" width="30"> | kgateway | Kubernetes gateway for AI services, providing a standardized way to connect applications with AI capabilities within the cluster. |
| <img src="https://raw.githubusercontent.com/agentgateway/agentgateway/refs/heads/main/ui/public/favicon.svg" width="30"> | Agent Gateway| Gateway Dataplane for AI workloads (MCP, A2A) |
| <img src="https://raw.githubusercontent.com/cncf/artwork/refs/heads/main/projects/crossplane/icon/color/crossplane-icon-color.svg" width="30"> | Crossplane | An open source Kubernetes add-on that transforms your cluster into a universal control plane, enabling platform teams to build infrastructure abstractions. |
| <img src="https://raw.githubusercontent.com/kagent-dev/kagent/33a48ede61be68c84f6adcfddde09db41aeb1ea7/img/icon-dark.svg" width="30"> | kagent | Kubernetes-native AI agent framework that enables the deployment and management of AI agents within Kubernetes clusters. |
| <img src="https://argo-cd.readthedocs.io/en/stable/assets/logo.png" width="30"> | ArgoCD | GitOps continuous delivery tool for Kubernetes that automates the deployment of applications and manages their lifecycle based on Git repositories. |

# Demos

"Demo" is an end-to-end installation or an implementation of an idea. It is similar to a tutorial in concept but typically is a deep-dive and a more detailed view of particular piece of technology.
These demos are found in [Wiki](https://github.com/olga-mir/playground/wiki)

# Infrastructure

This project consists of 2 or more GKE clusters (terminology should be switched to hub/spoke instead of management):

1. **Management Cluster**: Infrastructure management and provisioning, running Crossplane and ArgoCD with ApplicationSet controller
2. **Apps Cluster(s)**: One or more clusters for application workload hosting, running ArgoCD

**Refactor in progress** from bash scripts to GKE Crossplane compositions: https://github.com/olga-mir/playground/pull/13
Cluster provisioning with Argo and Crossplane installed on target clusters with HelmRelease is already functional.

-![infra-demo](./docs/images/demo-infra.png)

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

Fully automated deployment:

```bash
$ task setup:deploy
```

Everything should be running, all manifests applied by Flux, resources provisioned by Crossplane once the above task finishes.

## How It Works - Flux Bootstrap Flow

1. **Crossplane provisions GKE clusters** via kind cluster running Flux
2. **Flux notification controller detects cluster readiness** and triggers GitHub webhook
3. **GitHub Actions workflow authenticates to GCP** using Workload Identity Federation
4. **Workflow bootstraps Flux on the new GKE cluster** with cluster-specific configuration
5. **Flux on GKE cluster syncs platform applications** from this repository

Uninstall everything:
```
$ task setup:cleanup
```

List all available tasks
```
$ task --list
```

# Repository Structure

This repository hosts both platform teams and consumer teams configurations. Typically they are spread across multiple repos.
Despite being hosted here in one repo for the demonstration purposes, these platform vs development teams sepration of concerns is still maintained.

## Platform Building Blocks

**Note** `config` in most folder paths usually mean "payload" to a specific system. e.g. `ai/kagent/config` contains kagent CR manifests that create kagent resources such as custom agents, model config, etc.

These are foundational objects to configure ArgoCD and umbrella ApplicationSets that include all apps managed in this repo. More on this in [./docs/demo/01-argocd.md](./docs/demo/01-argocd.md)
Because they are the base for Argo itself, files in this folder are applied during cluster provisioning by scripts in [./infra-setup](./infra-setup/)

```
platform/argocd-foundations/
├── argo-projects.yaml                 # Definitions for all ArgoCD Projects
├── platform-applicationsets.yaml      # ApplicationSet for all apps managed in this repo
├── helm-applicationsets.yaml          # ApplicationSet for all apps installed as external helm
└── teams-applicationsets.yaml         # Teams discovery
```

applicationsets files are ArgoCD `ApplicationSets` That generate applications from config provided in:
I don't think this is great approach, I'm still finding my feet in Argo-land and it is not my primary focus (but oh boy did argo quirkiness take so much of my time!)
`cmp` in the filename is important - it will tell ApplicationSet to run these through ArgoCD CMP mechnism to substitute variables (for future refactor)

```
platform/config
├── applications
│   ├── crossplane-infra-environment-configs-cmp.yaml
│   ├── crossplane-infra-functions.yaml
│   ├── ....
│   └── mcp-gateway-config.yaml
├── helm-applications
│   ├── ...
│   └── kgateway-crds.yaml
└── repository.yaml
```

## Consumers

All folders at the repo root which are not aux, are payloads that are managed by platform users.

```
├── ai          # AI tenancy, manifests required to create resources in AI space (kagent, kgateway, etc)
└── teams       # Software Engineering teams Crossplane tenancy
```

## Connect MCP Servers

```
% task --list | grep mcp
```

Also https://github.com/olga-mir/playground/wiki/ArgoCD-MCP-%E2%80%90-The-Networking-Aspects

More details to be updated soon

