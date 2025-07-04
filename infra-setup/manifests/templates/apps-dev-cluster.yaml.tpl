# --- Apps/Dev GKE Cluster ---
# old
# https://doc.crds.dev/github.com/crossplane/provider-gcp@v0.22.0
# https://doc.crds.dev/github.com/crossplane/provider-gcp/container.gcp.crossplane.io/Cluster/v1beta2@v0.22.0
# https://doc.crds.dev/github.com/crossplane/provider-gcp/container.gcp.crossplane.io/NodePool/v1beta1@v0.22.0
# new
# https://marketplace.upbound.io/providers/upbound/provider-gcp-beta-container/v0.4.4/resources/container.gcp-beta.upbound.io/Cluster/v1beta2
# https://marketplace.upbound.io/providers/upbound/provider-gcp-beta-container/v0.4.4/resources/container.gcp-beta.upbound.io/NodePool/v1beta2
# https://marketplace.upbound.io/providers/upbound/provider-gcp-beta-container/v0.5.0
apiVersion: container.gcp-beta.upbound.io/v1beta2
kind: Cluster
metadata:
  name: ${GKE_APPS_DEV_CLUSTER}
  namespace: gke
spec:
  providerConfigRef:
    name: crossplane-provider-gcp
  forProvider:
    network: "projects/${PROJECT_ID}/global/networks/${GKE_VPC}"
    subnetwork: "projects/${PROJECT_ID}/regions/${REGION}/subnetworks/${APPS_DEV_SUBNET_NAME}"
    location: "${REGION}-a"
    #nodeLocations:
    #- "${REGION}-a"
    workloadIdentityConfig:
      workloadPool: "${PROJECT_ID}.svc.id.goog"
    removeDefaultNodePool: true
    initialNodeCount: 1
    gatewayApiConfig:
      # should be supported but doesn't work
      # clusters.container.gcp-beta.upbound.io.spec.forProvider.gatewayApiConfig.channel
      #channel: CHANNEL_EXPERIMENTAL
      channel: CHANNEL_STANDARD
    enableAutopilot: false
    releaseChannel:
      channel: RAPID
  writeConnectionSecretToRef:
    namespace: crossplane-system
    name: ${GKE_APPS_DEV_CLUSTER}-kubeconfig
---
apiVersion: container.gcp-beta.upbound.io/v1beta2
kind: NodePool
metadata:
  name: ${GKE_APPS_DEV_CLUSTER}-pool
  namespace: gke
spec:
  forProvider:
    clusterRef:
      name: ${GKE_APPS_DEV_CLUSTER}
    maxPodsPerNode: 32
    nodeConfig:
      spot: true
      machineType: ${APPS_DEV_NODE_MACHINE_TYPE}
      diskSizeGb: 50
      spot: true
    autoscaling:
      minNodeCount: 2
      maxNodeCount: 5
    management:
      autoRepair: true
      autoUpgrade: true
  providerConfigRef:
    name: crossplane-provider-gcp
