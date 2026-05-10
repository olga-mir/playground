#!/bin/bash

set -eoux pipefail

export WIF_SERVICE_ACCOUNT="github-actions-sa@$PROJECT_ID.iam.gserviceaccount.com"

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
    --member="serviceAccount:${WIF_SERVICE_ACCOUNT}" \
    --role="roles/container.developer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:${WIF_SERVICE_ACCOUNT}" \
    --role="roles/container.clusterAdmin"

# Needs additional perms do install Flux (dry-run CRD, or remove dry-run)
# "Kubernetes Engine Admin (roles/container.admin)" or
# `container.clusterRoles.update` permission

# Allow GitHub repo to impersonate the service account
GITHUB_REPO=${GITHUB_DEMO_REPO_OWNER}/${GITHUB_DEMO_REPO_NAME}
gcloud iam service-accounts add-iam-policy-binding \
    $WIF_SERVICE_ACCOUNT \
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

# Workload Identity binding: allows Crossplane provider pods on GKE clusters to impersonate
# crossplane-gke-sa without a key file. The DeploymentRuntimeConfig pins all GCP provider pods
# to the KSA name "crossplane-provider-gcp" in crossplane-system, so one binding covers them all.
gcloud iam service-accounts add-iam-policy-binding \
    crossplane-gke-sa@${PROJECT_ID}.iam.gserviceaccount.com \
    --member="serviceAccount:${PROJECT_ID}.svc.id.goog[crossplane-system/crossplane-provider-gcp]" \
    --role="roles/iam.workloadIdentityUser"

# SA key is still needed for the local kind cluster (WIF is not practical on kind).
# TODO - don't save it in the repo folder
gcloud iam service-accounts keys create crossplane-gke-sa-key.json \
    --iam-account=crossplane-gke-sa@${PROJECT_ID}.iam.gserviceaccount.com

echo "Creating VPC network: $GKE_VPC"
if ! gcloud compute networks describe $GKE_VPC --project=$PROJECT_ID &>/dev/null; then
  gcloud compute networks create $GKE_VPC \
      --project=$PROJECT_ID \
      --subnet-mode=custom
  echo "✓ VPC $GKE_VPC created"
else
  echo "✓ VPC $GKE_VPC already exists"
fi

# Create management subnet
# Using 10.1.0.0/24 for the primary range (plenty for 20 nodes)
# Using 10.1.1.0/24 for services (can accommodate ~250 services)
# Using 10.1.4.0/22 for pods (can accommodate ~1000 pods)
if ! gcloud compute networks subnets describe "${CONTROL_PLANE_SUBNET_NAME}" --region=$REGION --project=$PROJECT_ID &>/dev/null; then
  gcloud compute networks subnets create "${CONTROL_PLANE_SUBNET_NAME}" \
    --project=$PROJECT_ID \
    --network=$GKE_VPC \
    --region=$REGION \
    --range=10.1.0.0/24 \
    --secondary-range=services-range=10.1.1.0/24,pods-range=10.1.4.0/22
  echo "✓ Control Plane Subnet created"
else
  echo "✓ Control Plane Subnet already exists"
fi

# Create apps development subnet
# Using 10.2.0.0/24 for the primary range (plenty for 20 nodes)
# Using 10.2.1.0/24 for services (can accommodate ~250 services)
# Using 10.2.4.0/22 for pods (can accommodate ~1000 pods)
if ! gcloud compute networks subnets describe "${APPS_DEV_SUBNET_NAME}" --region=$REGION --project=$PROJECT_ID &>/dev/null; then
  gcloud compute networks subnets create "${APPS_DEV_SUBNET_NAME}" \
    --project=$PROJECT_ID \
    --network=$GKE_VPC \
    --region=$REGION \
    --range=10.2.0.0/24 \
    --secondary-range=services-range=10.2.1.0/24,pods-range=10.2.4.0/22
  echo "✓ Apps Dev Subnet created"
else
  echo "✓ Apps Dev Subnet already exists"
fi

echo "Subnet creation complete!"
echo "VPC: $GKE_VPC"
echo "Control Plane Subnet: "${CONTROL_PLANE_SUBNET_NAME}" (10.1.0.0/24)"
echo "  - Services Range: 10.1.1.0/24"
echo "  - Pods Range: 10.1.4.0/22"
echo "Apps Dev Subnet: "${APPS_DEV_SUBNET_NAME}" (10.2.0.0/24)"
echo "  - Services Range: 10.2.1.0/24"
echo "  - Pods Range: 10.2.4.0/22"

# bucket for logs storage
gcloud storage buckets add-iam-policy-binding gs://${LOG_BUCKET_NAME} \
  --member="serviceAccount:${WIF_SERVICE_ACCOUNT}" \
  --role="roles/storage.objectCreator"

#
# GitHub App Flux Creds secret setup
#

# Create secret and upload PEM
gcloud secrets create github-app-private-key \
  --project="${PROJECT_ID}" --replication-policy=automatic

gcloud secrets versions add github-app-private-key \
  --data-file="${GITHUB_APP_PRIVATE_KEY_FILE}" \
  --project="${PROJECT_ID}"

# Grant WIF service account access (replace with actual SA value)
gcloud secrets add-iam-policy-binding github-app-private-key \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${WIF_SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"

#
# PAT for Flux notification provider (github-webhook-token on GKE clusters)
#

if ! gcloud secrets describe gh-flux-pat --project="${PROJECT_ID}" &>/dev/null; then
  gcloud secrets create gh-flux-pat \
    --project="${PROJECT_ID}" --replication-policy=automatic
fi

# Populate the secret value after running this script:
#   echo -n "YOUR_PAT_HERE" | gcloud secrets versions add gh-flux-pat \
#     --data-file=- --project="${PROJECT_ID}"

gcloud secrets add-iam-policy-binding gh-flux-pat \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${WIF_SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"
