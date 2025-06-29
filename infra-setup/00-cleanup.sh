#!/bin/bash

set -x

export MGMT_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${ZONE}_${GKE_MGMT_CLUSTER}"
export REPO_ROOT=$(git rev-parse --show-toplevel)

kind delete clusters kind-test-cluster

# kubectl --context "${MGMT_CLUSTER_CONTEXT}" delete -f ${REPO_ROOT}/teams/team-alpha/landing-zone-claim.yaml
helm --kube-context "${MGMT_CLUSTER_CONTEXT}" uninstall argocd -n argocd

sleep 20

gcloud container clusters delete $GKE_MGMT_CLUSTER --zone "${REGION}-a" -q &
gcloud container clusters delete $GKE_APPS_DEV_CLUSTER --zone "${REGION}-a" -q
