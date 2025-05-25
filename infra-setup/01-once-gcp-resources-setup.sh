#!/bin/bash

set -eoux pipefail


echo THIS SETUP ONLY NEEDED ONCE
exit 0


# Validate required environment variables
required_vars=("GKE_VPC" "GKE_MGMT_CLUSTER" "GKE_APPS_DEV_CLUSTER" "REGION" "PROJECT_ID")
for var in "${required_vars[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "Error: $var environment variable is not set"
        exit 1
    fi
done

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
gcloud compute networks subnets create "${MGMT_SUBNET_NAME}" \
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
echo "Management Subnet: "${MGMT_SUBNET_NAME}" (10.1.0.0/24)"
echo "  - Services Range: 10.1.1.0/24"
echo "  - Pods Range: 10.1.4.0/22"
echo "Apps Dev Subnet: "${APPS_DEV_SUBNET_NAME}" (10.2.0.0/24)"
echo "  - Services Range: 10.2.1.0/24"
echo "  - Pods Range: 10.2.4.0/22"
