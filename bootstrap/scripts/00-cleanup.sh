#!/bin/bash

set -eoux pipefail

echo ADD SUSPEND KUSTOMIZATIONS BEFORE RUNNING THIS
exit 0

export CONTROL_PLANE_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_CONTROL_PLANE_CLUSTER}"
export REPO_ROOT=$(git rev-parse --show-toplevel)

kind delete clusters kind-test-cluster


sleep 20

gcloud container clusters delete $GKE_CONTROL_PLANE_CLUSTER --zone "${REGION}-a" -q &
gcloud container clusters delete $GKE_APPS_DEV_CLUSTER --zone "${REGION}-a" -q
