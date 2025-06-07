#!/bin/bash

# TODO - explicit context

set -eoux pipefail
export REPO_ROOT=$(git rev-parse --show-toplevel)

main () {
  # install v1.2.1 v2.1.0-main
  # sleep 5

  agentgateway-write-config-example
  agentgateway -f $REPO_ROOT/local/agentgateway-config.json
}


function install() {
  gateway_api_version=${1-v1.2.1}
  kgateway-version=${2-v2.1.0-main}

  kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml
  helm upgrade -i kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds --version v2.1.0-main --namespace kgateway-system --create-namespace
  helm upgrade -i kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway --version v2.1.0-main --namespace kgateway-system --create-namespace --set agentGateway.enabled=true  --set image.registry=ghcr.io/kgateway-dev
}


function agentgateway-write-config-example() {

  cat << EOF > $REPO_ROOT/local/agentgateway-config.json
  {
    "type": "static",
    "listeners": [
      {
        "name": "sse",
        "protocol": "MCP",
        "sse": {
          "address": "[::]",
          "port": 3000
        }
      }
    ],
    "targets": {
      "mcp": [
        {
          "name": "everything",
          "stdio": {
            "cmd": "npx",
            "args": [
              "@modelcontextprotocol/server-everything"
            ]
          }
        }
      ]
    }
  }
EOF

# With this configuration (and running whatever magic is baked into `agentgateway` CLI),
# This is what is available out of the box:
# % k get gatewayclass -A                                                                                                                                                                                                                                                 develop 13:00:05
# NAME                CONTROLLER              ACCEPTED   AGE
# agentgateway        kgateway.dev/kgateway   True       11m
# kgateway            kgateway.dev/kgateway   True       11m
# kgateway-waypoint   kgateway.dev/kgateway   True       11m
#
# there is no Gateway or GatewayParameters resource, no special configmaps. Agent UI worked and I was able to connect to server-everything
#
# k logs -n kgateway-system kgateway-6cf8fcfdcd-dphp8 | head
# {"time":"2025-06-07T02:48:37.215650926Z","level":"INFO","msg":"probe server starting","component":"default","addr":":8765","path":"/healthz"}
# {"time":"2025-06-07T02:48:37.215653801Z","level":"INFO","msg":"global settings loaded","component":"default","settings":{"DnsLookupFamily":"V4_PREFERRED","ListenerBindIpv6":true,"EnableIstioIntegration":false,"EnableIstioAutoMtls":false,"IstioNamespace":"istio-system","XdsServiceHost":"","XdsServiceName":"kgateway","XdsServicePort":9977,"UseRustFormations":false,"EnableInferExt":false,"InferExtAutoProvision":false,"DefaultImageRegistry":"ghcr.io/kgateway-dev","DefaultImageTag":"v2.1.0-main","DefaultImagePullPolicy":"IfNotPresent","WaypointLocalBinding":false,"IngressUseWaypoints":false,"LogLevel":"info","DiscoveryNamespaceSelectors":"[]","EnableAgentGateway":true}}
# {"time":"2025-06-07T02:48:37.220646217Z","level":"INFO","msg":"starting kgateway","component":"default"}
# {"time":"2025-06-07T02:48:37.222347217Z","level":"INFO","msg":"creating krt collections","component":"default"}
# {"time":"2025-06-07T02:48:37.222606926Z","level":"INFO","msg":"initializing controller","component":"default"}
}


main
