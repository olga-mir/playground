# Project purpose
* This is project that covers wide range of technology for learning and exploration for experienced Kubernetes and Platform Engineers
* This is not production ready project, but we aim for comprehensive prod-like solutions as much as possible
* The infrastructure in this project is disposable - it is provisioned in the beginning of a learning session and then fully destroyed after use - therefore all out-of-band commands must be captured in yaml manifests, bash scripts or taskfiles.
* The infrastructure is provisioned in a personal GCP account - we need to be aware of costs and security.

# important-instruction-reminders
* prefer editing an existing file to creating a new one.
* NEVER proactively create documentation files (.md) or README files. Only create documentation files if explicitly requested by the User.
* NEVER commit project ID or other semi-sensitve information
* when moving or creating files remember that they need to be versioned - use 'git mv' over 'mv' and similar commands.

# architecture-context
This is a multi-cluster Kubernetes setup using Crossplane for infrastructure provisioning:

## Cluster Architecture
- **kind cluster (local)**: Runs Crossplane control plane for orchestrating cloud resources
- **GKE mgmt cluster (GCP)**: Management cluster with ArgoCD for GitOps and Crossplane for managing platform
- **GKE apps-dev cluster (GCP)**: Applications cluster with minimal ArgoCD agent

## Key Components
- Crossplane compositions create GKE clusters, ArgoCD installations, and Crossplane deployments
- Helm provider deploys charts to remote GKE clusters (requires GCP auth)
- Claims define desired GKE clusters via custom resources (GKECluster)

## File Structure
```
├── ai           # misc AI stacks deployed by ArgoCD ApplicationSets to GKE clusters
├── infra-setup  # provision local `kind` cluster, configure all required access for provisioning GKE clusters with Crossplane
├── local        # supporting experiements that I run locally
├── platform     # setup platform components on target GKE clusters, wires up GitOps to deploy payload from other folders
├── tasks        # Taskfile supporting tasks
└── teams        # Platform tenants that consume platform as exposed by the platform team
```

one level in `platforms`
```
platform
├── argocd-foundations # foundations for ArgoCD on GKE Clusters - ArgoCD projects, ApplicationSets
├── config             # payload to be read by ArgoCD applicationSets and deployed to GKE clusters
└── crossplane         # Crossplane payload deployed by Argo to "mgmt" cluster
```

### Sub Goals

#### Github Config as Code powered by Crossplane
* This repo is referred to as "DEMO"
* Crossplane Github provider configured to provision resources only in "DEST" organisation - there are separate set of credentials to this end.

#### AI Networking - kgateway, agentgatway
* manifests in "${REPO_ROOT}/ai" folder

#### AI discovery
* writing my own `kagent` agent to help work with compositions
* combining agents and MCP servers
* exploring workflows
* understanding AI specific network requirements

## VARIABLES
* Some of the variables won't be available to you terminal where you are running.
* This variables are always sourced in a "working" terminal:

```
export GKE_VPC
export GKE_MGMT_CLUSTER
export GKE_APPS_DEV_CLUSTER
export REGION
export ZONE
export PROJECT_ID
export PROJECT_NUMBER
export MGMT_SUBNET_NAME
export APPS_DEV_SUBNET_NAME
export CROSSPLANE_GSA_KEY_FILE
export DOMAIN
export CERT_NAME
export DNS_PROJECT
export DNS_ZONE
export ARGOCD_STD_HOSTNAME="argocd.gcp.${DOMAIN}"
export ARGOCD_MCP_HOSTNAME="argo-mcp.gcp.${DOMAIN}"
export GITHUB_DEMO_REPO_OWNER
export GITHUB_DEMO_REPO_NAME
export GITHUB_DEMO_REPO_PAT
export GITHUB_DEST_ORG_NAME
export GITHUB_DEST_ORG_PAT
export GITHUB_DEST_ORG_REPO_LVL_PAT
export GITHUB_DEST_ORG_ORG_LVL_PAT
export ANTHROPIC_API_KEY
export OPENAI_API_KEY
export CLAUDE_MCP_CONFIG_FILE
export PINECONE_API_KEY
```
