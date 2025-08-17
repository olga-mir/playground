#!/bin/bash

set -eoux pipefail

echo THIS SETUP ONLY NEEDED ONCE
exit 0

# Create Workload Identity Pool
gcloud iam workload-identity-pools create github-pool \
    --project=$PROJECT_ID \
    --location=global \
    --display-name="GitHub Actions Pool"

# Create Workload Identity Provider
gcloud iam workload-identity-pools providers create-oidc github-provider \
    --project=$PROJECT_ID \
    --location=global \
    --workload-identity-pool=github-pool \
    --display-name="GitHub Actions Provider" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="attribute.repository.startsWith('${GITHUB_DEMO_REPO_OWNER}')" \
    --issuer-uri="https://token.actions.githubusercontent.com"

# Create service account for GitHub Actions
gcloud iam service-accounts create github-actions-sa \
    --project=$PROJECT_ID \
    --display-name="GitHub Actions Service Account"

# Grant necessary permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-actions-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/container.developer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-actions-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/container.clusterAdmin"

# Allow GitHub repo to impersonate the service account
GITHUB_REPO=${GITHUB_DEMO_REPO_OWNER}/${GITHUB_DEMO_REPO_NAME}
gcloud iam service-accounts add-iam-policy-binding \
    github-actions-sa@$PROJECT_ID.iam.gserviceaccount.com \
    --project=$PROJECT_ID \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/$GITHUB_REPO"

# Validate required environment variables
# TODO - env var validation has been removed. use taskfile to validate setup

gcloud iam service-accounts create crossplane-gke-sa \
    --display-name="Crossplane GKE Service Account"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:crossplane-gke-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/container.admin"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:crossplane-gke-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:crossplane-gke-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/storage.objectCreator"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:crossplane-gke-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/storage.admin"


# TODO - don't save it in the repo folder
gcloud iam service-accounts keys create crossplane-gke-sa-key.json \
    --iam-account=crossplane-gke-sa@${PROJECT_ID}.iam.gserviceaccount.com

echo "Creating VPC network: $GKE_VPC"
gcloud compute networks create $GKE_VPC \
  --project=$PROJECT_ID \
  --subnet-mode=custom

# Create management subnet
# Using 10.1.0.0/24 for the primary range (plenty for 20 nodes)
# Using 10.1.1.0/24 for services (can accommodate ~250 services)
# Using 10.1.4.0/22 for pods (can accommodate ~1000 pods)
gcloud compute networks subnets create "${CONTROL_PLANE_SUBNET_NAME}" \
  --project=$PROJECT_ID \
  --network=$GKE_VPC \
  --region=$REGION \
  --range=10.1.0.0/24 \
  --secondary-range=services-range=10.1.1.0/24,pods-range=10.1.4.0/22

# Create apps development subnet
# Using 10.2.0.0/24 for the primary range (plenty for 20 nodes)
# Using 10.2.1.0/24 for services (can accommodate ~250 services)
# Using 10.2.4.0/22 for pods (can accommodate ~1000 pods)
gcloud compute networks subnets create "${APPS_DEV_SUBNET_NAME}" \
  --project=$PROJECT_ID \
  --network=$GKE_VPC \
  --region=$REGION \
  --range=10.2.0.0/24 \
  --secondary-range=services-range=10.2.1.0/24,pods-range=10.2.4.0/22

echo "Subnet creation complete!"
echo "VPC: $GKE_VPC"
echo "Control Plane Subnet: "${CONTROL_PLANE_SUBNET_NAME}" (10.1.0.0/24)"
echo "  - Services Range: 10.1.1.0/24"
echo "  - Pods Range: 10.1.4.0/22"
echo "Apps Dev Subnet: "${APPS_DEV_SUBNET_NAME}" (10.2.0.0/24)"
echo "  - Services Range: 10.2.1.0/24"
echo "  - Pods Range: 10.2.4.0/22"
