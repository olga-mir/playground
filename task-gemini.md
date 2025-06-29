# Task: Create Fortio Cloud Run Service with Crossplane

## Objective
Create a complete Crossplane configuration to deploy a Fortio load testing service to Google Cloud Run with proper IAM, networking, and blue-green deployment capabilities.

## Context
you have a number of environment variables sourced in the terminal and used thoughout the codebase
- **Target Cluster**: `mgmt` cluster (hub cluster running Crossplane, GKE). Ignore `infra-setup` folder completely, it is used to set the environment and is not relevant for this task
- **Crossplane Provider**: `upbound/provider-family-gcp-beta/v0.5.1` already installed and configured on mgmt cluster
- **Project**: Deployed by GitOps to ${PROJECT_ID} project
- **Network**: Use existing subnet `projects/${PROJECT_ID}/regions/australia-southeast1/subnetworks/subnet-cloud-run-main`
- **GitOps**: We have ArgoCD configured in this project. Do NOT worry about wiring your work to Argo. However you need to decide if your payload will be synced as ArgoCD Helm or directory.recurse payload. Avoid using kustomize.
- **Working Folder**: Place all your payload inside `${REPO_ROOT}/gcp-gemini` folder. You can chose any way how to structure payload inside.

## Requirements

### 1. Cloud Run Service Configuration
- **Image**: `fortio/fortio:latest`
- **Authentication**: Enable auth with invoker check, grant `allUsers` invoker role
- **Networking**: Deploy with Direct VPC Egress using the specified subnet
- **Blue-Green**: Enable traffic splitting capabilities (50/50) for future deployments
- **Service Account**: Create dedicated service account for the Cloud Run service

### 2. Crossplane Resources to Create
Since there are no existing Cloud Run compositions, create from scratch:

#### A. CompositeResourceDefinition (XRD)
- Define a custom resource type for Cloud Run services
- Include parameters for: image, region, subnet, authentication settings, traffic allocation
- Support for IAM service account creation and binding

#### B. Composition
- Use `crossplane-contrib/provider-upjet-gcp` resources
- CloudRun related code and CRDs are found locally on these paths:
/Users/olga/repos/org-crossplane/provider-upjet-gcp/cmd/provider/cloudrun
/Users/olga/repos/org-crossplane/provider-upjet-gcp/apis/cloudrun
/Users/olga/repos/org-crossplane/provider-upjet-gcp/config/cloudrun
/Users/olga/repos/org-crossplane/provider-upjet-gcp/internal/controller/cloudrun
/Users/olga/repos/org-crossplane/provider-upjet-gcp/examples/cloudrun
/Users/olga/repos/org-crossplane/provider-upjet-gcp/examples-generated/cloudrun
- Create the following GCP resources:
  - Cloud Run service with specified configuration
  - IAM service account for the Cloud Run service
  - IAM policy binding for Cloud Run Invoker role (allUsers)
  - Any additional IAM bindings needed for the service account

#### C. Composite Resource Claim
- Create a claim to instantiate the Fortio service
- Use appropriate naming conventions
- Reference the composition created above

### 3. IAM Requirements:
  - Create service account: `fortio-cloudrun-crossplane-sa@${PROJECT_ID}.iam.gserviceaccount.com` (or similar)
  - Grant `roles/run.invoker` to `allUsers` for the Cloud Run service
  - Ensure proper permissions for the service account

### 4. File Organization

### 5. Security Considerations
- Do not hardcode project IDs in the YAML files - use environment variables or parameters
- Document security recommendations, but keep this deployment very minimal at this stage

## Expected Deliverables
1. Complete Crossplane XRD for Cloud Run services
2. Composition using GCP provider resources
3. Claim for the Fortio service instance
4. Documentation with deployment and usage instructions
5. Any helper scripts or commands for easier management
6. Do not create detailed README files at this stage, will do it when project is more stable

## Additional Notes
- Ensure compatibility with Crossplane v2-preview
- Follow Crossplane best practices for naming and labeling
- The solution does not need to be production ready

