# Task: Create Fortio Cloud Run Service with Crossplane

## Objective
Update existing Crossplane Cloud Run deployment found in `${REPO_ROOT}/gcp-gemini` folder.
Make sure you fix Direct VPC egress settings (read local documentation or websites if needed)
Make sure to use latests versions of Crossplane CRDs, use v2service for Cloud Run.

## Context
you have a number of environment variables sourced in the terminal and used thoughout the codebase
- **Target Cluster**: `mgmt` cluster (hub cluster running Crossplane, GKE). Ignore `infra-setup` folder completely, it is used to set the environment and is not relevant for this task. Resources you work with will be deployed to `mgmt` cluster.
- **Crossplane Provider**: `crossplane-contrib/provider-upjet-gcp` version 1.14.0. already installed and configured on mgmt cluster
- **Project**: Deployed by GitOps to ${PROJECT_ID} project
- **Network**: Use existing subnet `projects/${PROJECT_ID}/regions/australia-southeast1/subnetworks/subnet-cloud-run-main`
- **GitOps**: This folder is connected to GitOps and will be deployed automatically, you don't need to add anything.

## Requirements

### 1. Cloud Run Service Configuration
- **Networking**: Deploy with Direct VPC Egress using the specified subnet. This is very important
- **Image**: `fortio/fortio:latest`
- **Authentication**: Enable auth with invoker check, grant `allUsers` invoker role
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
- gcp-provider source code is available locally at this path: ${HOME}/repos/org-crossplane/provider-upjet-gcp
You don't need all of this, the most important files are the CRDs, you can find relevant files using this command:
```
ls ${HOME}/repos/org-crossplane/provider-upjet-gcp/package/crds | grep cloudrun
```

- Create the following GCP resources:
  - Cloud Run service, remember - v2service, Direct VPC Egress
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
3. Crossplane Claim instantiating the above composition
6. Do not create detailed README files at this stage, will do it when project is more stable

## Additional Notes
- Ensure compatibility with Crossplane v2-preview
- Follow Crossplane best practices for naming and labeling
- The solution does not need to be production ready

