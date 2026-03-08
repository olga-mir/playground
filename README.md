# Welcome

A monorepo showcasing modern cloud-native and AI-powered workflows. Built on **Crossplane v2** for platform API abstractions and **FluxCD** for GitOps automation.

Features cutting-edge AI projects including `kgateway` and `kagent` - Kubernetes-native projects designed to enable agentic AI workflows within cloud infrastructure. This repository serves as a playground for exploring the intersection of infrastructure-as-code, AI agents, and Kubernetes-native tooling.

# Tech Stack

| Logo | Name | Description | Project Version |
|------|------|-------------|-----------------|
| <img src="https://www.gstatic.com/marketing-cms/assets/images/29/8c/e1f2c0994e87b8d7edf2886f9c02/google-cloud.webp=s96-fcrop64=1,00000000ffffffff-rw" width="30"> | GKE | Google Kubernetes Engine is Google Cloud's managed Kubernetes service that provides a secure, scalable environment for running containerized applications. | 1.34.1 |
| <img src="https://raw.githubusercontent.com/kubernetes-sigs/gateway-api/dbd2ff92a93e7c8a29bce07cc331e40e6d470efe/site-src/images/logo/logo.svg" width="30"> | Gateway API | Kubernetes Gateway API is a collection of resources that model service networking in Kubernetes, providing expressive, extensible, and role-oriented interfaces. | [v1.5.0](https://github.com/kubernetes-sigs/gateway-api/releases/tag/v1.5.0) |
| <img src="https://kgateway.dev/feature-api-gateway.svg" width="30"> | kgateway | Kubernetes gateway for AI services, providing a standardized way to connect applications with AI capabilities within the cluster. | [v2.2.1](https://github.com/kgateway-dev/kgateway/releases/tag/v2.2.1) |
| <img src="https://raw.githubusercontent.com/agentgateway/agentgateway/refs/heads/main/ui/public/favicon.svg" width="30"> | Agent Gateway| Gateway Dataplane for AI workloads (MCP, A2A) | [v1.0.0-alpha.4](https://github.com/agentgateway/agentgateway/releases/tag/v1.0.0-alpha.4) |
| <img src="https://raw.githubusercontent.com/cncf/artwork/refs/heads/main/projects/crossplane/icon/color/crossplane-icon-color.svg" width="30"> | Crossplane | An open source Kubernetes add-on that transforms your cluster into a universal control plane, enabling platform teams to build infrastructure abstractions. | [v2.2.0](https://github.com/crossplane/crossplane/releases/tag/v2.2.0) |
| <img src="https://raw.githubusercontent.com/kagent-dev/kagent/33a48ede61be68c84f6adcfddde09db41aeb1ea7/img/icon-dark.svg" width="30"> | kagent | Kubernetes-native AI agent framework that enables the deployment and management of AI agents within Kubernetes clusters. | [v0.7.23](https://github.com/kagent-dev/kagent/releases/tag/v0.7.23) |
| <img src="https://raw.githubusercontent.com/cncf/artwork/88fa3f88ea2e4bf3e4941be8dc797b6d860c9ade/projects/flux/icon/color/flux-icon-color.svg" width="30"> | FluxCD | GitOps toolkit for Kubernetes that keeps clusters in sync with configuration sources and automates deployments. | [v2.8.1](https://github.com/fluxcd/flux2/releases/tag/v2.8.1) |
| <img src="https://raw.githubusercontent.com/cncf/artwork/refs/heads/main/projects/litmus/icon/color/litmus-icon-color.svg" width="30"> | LitmusChaos | Cloud-native chaos engineering framework for Kubernetes that helps teams find weaknesses in their deployments through controlled chaos experiments. | [v3.26.0](https://github.com/litmuschaos/litmus-helm/releases/tag/litmus-3.26.0) |

Explore [Wiki](https://github.com/olga-mir/playground/wiki) for demos and tutorials based on this repo.

# Infrastructure

This project implements a **hierarchical architecture** with fully automated cluster provisioning and GitOps deployment:

## 🏗️ Cluster Architecture

1. **Temporary Bootstrap cluster (kind)**: Local cluster running Crossplane v2 + FluxCD. Provisions permanent `control-plane` cluster in the cloud.
2. **Control-plane cluster (GKE)**: Management cluster with Crossplane, platform services, and AI stack. Provisions workload clusters.
3. **Workload clusters (GKE)**: Isolated clusters for tenant applications (apps-dev, staging, prod).

In this project the temporary bootstrap cluster currently stays for the lifetime of the setup.
In Cluster API (not used in this project) there is bootstrap-and-pivot concept allowing moving configuration from oneplace to another
without breaking the connection. In this way the config for permanent control-plane cluster lives in the cluster itself.
It is not entirely clear right how Day-2 for control-plane cluster should look like in Crossplane.

# Deployment

## Prerequisites

* Access to GCP account with sufficient permissions
* tools: gcloud, flux, kubectl, task
* Access to GitHub organisation or personal account

### GitHub Repository Secrets

Configure these secrets in your GitHub repository settings (Settings → Secrets and variables → Actions):

```bash
# Workload Identity Federation for GitHub Actions (replace vars with your values)
WIF_PROVIDER=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_NAME/providers/$PROVIDER_NAME
WIF_SERVICE_ACCOUNT=github-actions-sa@$PROJECT_ID.iam.gserviceaccount.com

# GitHub App for Flux bootstrap — see docs/github-app-setup.md
GH_APP_ID=your_app_id
GH_APP_INSTALLATION_ID=your_installation_id
GH_APP_PRIVATE_KEY=<path-to-private-key.pem>
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

### Performance Experimentation

This project integrates "tenant" application which is developed in another repository: https://github.com/olga-mir/playground-sre.
This repo has source code, GitHub Actions workflows to build and push image and k8s manifests that are deployed from this repo.

```
# Baseline — sleep 50ms, 10 concurrent connections, 30s
kubectl exec -n team-bravo deploy/fortio-echo -- \
  fortio load -c 10 -qps 100 -t 30s \
  'http://perf-lab.sre.svc.cluster.local/v1/scenarios/sleep?duration=50ms'

# CPU — 2 goroutines, 1s per request, 4 concurrent
kubectl exec -n team-bravo deploy/fortio-echo -- \
  fortio load -c 4 -qps 0 -t 30s \
  'http://perf-lab.sre.svc.cluster.local/v1/scenarios/cpu?duration=1s&goroutines=2'

# Fanout — 50 workers, watch goroutine scheduling overhead
kubectl exec -n team-bravo deploy/fortio-echo -- \
  fortio load -c 5 -qps 2 -t 30s \
  'http://perf-lab.sre.svc.cluster.local/v1/scenarios/fanout?workers=50&task_duration=200ms'
```
