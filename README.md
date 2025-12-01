# Welcome

A monorepo showcasing modern cloud-native and AI-powered workflows. Built on **Crossplane v2** for platform API abstractions and **FluxCD** for GitOps automation.

Features cutting-edge AI projects including `kgateway` and `kagent` - Kubernetes-native projects designed to enable agentic AI workflows within cloud infrastructure. This repository serves as a playground for exploring the intersection of infrastructure-as-code, AI agents, and Kubernetes-native tooling.

**Architecture**: Hierarchical 3-tier cluster setup with automated "batteries included" provisioning using Crossplane compositions and GitOps deployment via Flux notifications triggering GitHub Actions.

This AI Assisted project, leveraging Claude Sonnet, `gemini-cli`, and other AI tools.

# Tech Stack

| Logo | Name | Description | Project Version | Latest Version |
|------|------|-------------|-----------------|----------------|
| <img src="https://www.gstatic.com/marketing-cms/assets/images/29/8c/e1f2c0994e87b8d7edf2886f9c02/google-cloud.webp=s96-fcrop64=1,00000000ffffffff-rw" width="30"> | GKE | Google Kubernetes Engine is Google Cloud's managed Kubernetes service that provides a secure, scalable environment for running containerized applications. | - | - |
| <img src="https://raw.githubusercontent.com/kubernetes-sigs/gateway-api/dbd2ff92a93e7c8a29bce07cc331e40e6d470efe/site-src/images/logo/logo.svg" width="30"> | Gateway API | Kubernetes Gateway API is a collection of resources that model service networking in Kubernetes, providing expressive, extensible, and role-oriented interfaces. | - | - |
| <img src="https://kgateway.dev/feature-api-gateway.svg" width="30"> | kgateway | Kubernetes gateway for AI services, providing a standardized way to connect applications with AI capabilities within the cluster. | [v2.1.1](https://github.com/Kong/kgateway/releases/tag/v2.1.1) | [v2.1.1](https://github.com/Kong/kgateway/releases/latest) |
| <img src="https://raw.githubusercontent.com/agentgateway/agentgateway/refs/heads/main/ui/public/favicon.svg" width="30"> | Agent Gateway| Gateway Dataplane for AI workloads (MCP, A2A) | - | - |
| <img src="https://raw.githubusercontent.com/cncf/artwork/refs/heads/main/projects/crossplane/icon/color/crossplane-icon-color.svg" width="30"> | Crossplane | An open source Kubernetes add-on that transforms your cluster into a universal control plane, enabling platform teams to build infrastructure abstractions. | [v2.0.0-rc.1](https://github.com/crossplane/crossplane/releases/tag/v2.0.0-rc.1) | [v2.0.1](https://github.com/crossplane/crossplane/releases/latest) |
| <img src="https://raw.githubusercontent.com/kagent-dev/kagent/33a48ede61be68c84f6adcfddde09db41aeb1ea7/img/icon-dark.svg" width="30"> | kagent | Kubernetes-native AI agent framework that enables the deployment and management of AI agents within Kubernetes clusters. | [v0.7.5](https://github.com/kagent-dev/kagent/releases/tag/v0.7.5) | [v0.7.5](https://github.com/kagent-dev/kagent/releases/latest) |
| <img src="https://raw.githubusercontent.com/cncf/artwork/88fa3f88ea2e4bf3e4941be8dc797b6d860c9ade/projects/flux/icon/color/flux-icon-color.svg" width="30"> | FluxCD | GitOps toolkit for Kubernetes that keeps clusters in sync with configuration sources and automates deployments. | [v2.7.5](https://github.com/fluxcd/flux2/releases/tag/v2.7.5) | [v2.7.5](https://github.com/fluxcd/flux2/releases/latest) |
| <img src="https://raw.githubusercontent.com/cncf/artwork/refs/heads/main/projects/litmus/icon/color/litmus-icon-color.svg" width="30"> | LitmusChaos | Cloud-native chaos engineering framework for Kubernetes that helps teams find weaknesses in their deployments through controlled chaos experiments. | [v3.23.1](https://github.com/litmuschaos/litmus-helm/releases/tag/litmus-3.23.1) | [v3.23.1](https://github.com/litmuschaos/litmus-helm/releases/latest) |
| <img src="https://argo-cd.readthedocs.io/en/stable/assets/logo.png" width="10"> | ~~ArgoCD~~ | :kill-with-fire: This project was using ArgoCD until release TBC | - | - |

These demos are found in [Wiki](https://github.com/olga-mir/playground/wiki)

# Infrastructure

This project implements a **hierarchical 3-tier architecture** with fully automated cluster provisioning and GitOps deployment:

## 🏗️ Cluster Architecture

1. **Bootstrap cluster (kind)**: Local cluster running Crossplane v2 + FluxCD. Provisions control-plane cluster.
2. **Control-plane cluster (GKE)**: Management cluster with Crossplane, platform services, and AI stack. Provisions workload clusters.
3. **Workload clusters (GKE)**: Isolated clusters for tenant applications (apps-dev, staging, prod).

## ✅ Validation & Management

**Comprehensive validation framework**:
```bash
task validate:all                   # Full infrastructure validation
task validate:architecture          # Architectural constraints
```

**Key benefits**: Zero circular dependencies, clean separation of concerns, automated failure detection.

# Deployment

## Prerequisites

### GitHub Repository Secrets

Configure these secrets in your GitHub repository settings (Settings → Secrets and variables → Actions):

```bash
# Workload Identity Federation for GitHub Actions (replace vars with your values)
WIF_PROVIDER=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_NAME/providers/$PROVIDER_NAME
WIF_SERVICE_ACCOUNT=github-actions-sa@$PROJECT_ID.iam.gserviceaccount.com

# GitHub token for Flux bootstrap (needs repo:write permissions)
FLUX_GITHUB_TOKEN=ghp_your_personal_access_token_here
```

### Enviroment Variables

All required env variables are validated in preconditions of `deploy` task, defined [here](./tasks/setup.yaml).

## Project Structure and Bootstrap

### Architectural Flow

1. **Infrastructure Provisioning** (Kind cluster → GCP):
   - Crossplane compositions create GKE clusters (infrastructure only)
   - Connection secrets with kubeconfig are generated

2. **Cluster Bootstrapping** (GitHub Actions → Target cluster):
   - Flux notification detects cluster readiness → triggers GitHub webhook
   - GitHub Actions authenticates via Workload Identity Federation
   - Flux bootstrapped on target cluster pointing to `/clusters/{cluster-type}/`

3. **"Batteries Included" Deployment** (Target cluster GitOps):
   - Flux on target cluster deploys Crossplane installation
   - Platform services (kagent, kgateway, networking) deployed
   - Applications and tenant workloads deployed

This repository hosts both platform teams and consumer teams configurations with clear separation of concerns.

Refer to [./bootstrap/README.md](./bootstrap/README.md) for detailed explanation of repository structure and deployment flow.

## Platform vs Tenants

- **Platform Products**: Core services like kagent, kgateway, networking components
- **Platform Tenants**: End-user applications and team-specific workloads
- **Flux GitOps**: Automatically syncs both platform services and tenant applications to appropriate clusters

## 🚀 Quick Start

**Deploy complete infrastructure**:
```bash
task setup:deploy
```

**Validate deployment**:
```bash
task validate:all
```

**Clean up everything**:
```bash
task setup:cleanup
```

**Available commands**:
```bash
task --list
```

## Additional Diagnostics and Experimentation

```
# Test whereami (team-alpha)
kubectl exec -n team-platform deploy/fortio-diagnostic -- \
  fortio load -c 10 -qps 100 -t 30s http://whereami.team-alpha/

# Test fortio-echo (team-bravo)
kubectl exec -n team-platform deploy/fortio-diagnostic -- \
  fortio load -c 10 -qps 100 -t 30s http://fortio-echo.team-bravo/

# High load test
kubectl exec -n team-platform deploy/fortio-diagnostic -- \
  fortio load -c 50 -qps 1000 -t 60s http://whereami.team-alpha/
```
