#!/bin/bash

# this script is a temporary manualOps while I uild Crossplane avoiding ArgoCD

REPO_ROOT=$(git rev-parse --show-toplevel)

export MGMT_CLUSTER_CONTEXT="gke_${PROJECT_ID}_${REGION}_${GKE_MGMT_CLUSTER}"

# `$1: unbound variable` - removed "set -eoux pipefail" to avoid this error
find ${REPO_ROOT}/platform/crossplane/providers -name "*yaml" | xargs -n 1 kubectl --context=${MGMT_CLUSTER_CONTEXT} apply -f $1
sleep 15
find ${REPO_ROOT}/platform/crossplane/provider-configs -name "*yaml" | xargs -n 1 kubectl --context=${MGMT_CLUSTER_CONTEXT} apply -f $1

kubectl delete --all pods --namespace=crossplane-system
sleep 3

# kubectl apply -f ${REPO_ROOT}/aggregate-crossplane-role.yaml # doesn't work

kubectl --context=${MGMT_CLUSTER_CONTEXT} apply -f ${REPO_ROOT}/platform/crossplane/functions/function-patch-and-transform.yaml
kubectl --context=${MGMT_CLUSTER_CONTEXT} apply -f ${REPO_ROOT}/platform/crossplane/definitions/vs-landing-zone.yaml
kubectl --context=${MGMT_CLUSTER_CONTEXT} apply -f ${REPO_ROOT}/platform/crossplane/compositions/vs-landing-zone.yaml

kubectl --context=${MGMT_CLUSTER_CONTEXT} create ns team-alpha
sleep 2

kubectl --context=${MGMT_CLUSTER_CONTEXT} apply -f ${REPO_ROOT}/teams/team-alpha/landing-zone-claim.yaml
