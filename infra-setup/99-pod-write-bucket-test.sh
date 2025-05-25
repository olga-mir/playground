#!/bin/bash

export KUBE_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_APPS_DEV_CLUSTER}"
export NAMESPACE="team-alpha-service-one"
export KSA_NAME="team-alpha-service-one-ksa"
export TIMESTAMP=$(date +%Y%m%d%H%M%S)
export POD_NAME="bucket-writer-${TIMESTAMP}"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Get bucket name from managed resource
# TODO - CONTEXT
BUCKET_NAME=$(kubectl get bucket.storage.gcp.upbound.io -o jsonpath='{.items[0].status.atProvider.id}')

if [ -z "$BUCKET_NAME" ]; then
    echo -e "${RED}Error: Could not retrieve bucket name from managed resource${NC}"
    exit 1
fi

echo -e "${GREEN}Retrieved bucket name: ${BUCKET_NAME}${NC}"
echo -e "${GREEN}Creating pod to write to bucket${NC}"

FILENAME="${TIMESTAMP}.txt"

kubectl --context "${KUBE_CONTEXT}" apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${POD_NAME}
  namespace: ${NAMESPACE}
spec:
  serviceAccountName: ${KSA_NAME}
  containers:
  - name: bucket-writer
    image: gcr.io/google.com/cloudsdktool/cloud-sdk:alpine
    command: ["/bin/sh"]
    args:
    - "-c"
    - |
      echo 'Starting bucket writer...'
      echo "Writing empty file to bucket: ${BUCKET_NAME}/${FILENAME}"
      touch ${FILENAME}
      gsutil cp ${FILENAME} gs://${BUCKET_NAME}/${FILENAME}
      echo 'Listing files in bucket:'
      gsutil ls gs://${BUCKET_NAME}/
  restartPolicy: Never
EOF

echo -e "\n${GREEN}Waiting for pod to complete...${NC}"
kubectl --context "${KUBE_CONTEXT}" wait --for=condition=Ready pod/${POD_NAME} -n ${NAMESPACE} --timeout=60s

echo -e "\n${GREEN}Pod logs:${NC}"
kubectl --context "${KUBE_CONTEXT}" logs ${POD_NAME} -n ${NAMESPACE}
