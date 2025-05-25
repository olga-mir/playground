#!/bin/bash

set -eoux pipefail

## cluster, nodepool on kind cluster to verify cluster creation
# echo
# kubectl get cluster
# echo
# kubectl get nodepool

echo
kubectl get providerconfig
echo
kubectl get managed
echo
kubectl get apps -A

kubectl get secret -n team-alpha
