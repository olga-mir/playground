apiVersion: container.gcp-beta.upbound.io/v1beta2
kind: Cluster
metadata:
  name: ${GKE_MGMT_CLUSTER}
  namespace: gke
spec:
  providerConfigRef:
    name: crossplane-provider-gcp
  forProvider:
    network: "projects/${PROJECT_ID}/global/networks/${GKE_VPC}"
    subnetwork: "projects/${PROJECT_ID}/regions/${REGION}/subnetworks/${MGMT_SUBNET_NAME}"
    location: "${REGION}-a"
    #nodeLocations:
    #- "${REGION}-a"
    workloadIdentityConfig:
      workloadPool: "${PROJECT_ID}.svc.id.goog"
    initialNodeCount: 1
    removeDefaultNodePool: true
    gatewayApiConfig:
      #channel: CHANNEL_EXPERIMENTAL
      channel: CHANNEL_STANDARD
    enableAutopilot: false
    releaseChannel:
      channel: RAPID
  writeConnectionSecretToRef:
    namespace: crossplane-system
    name: ${GKE_MGMT_CLUSTER}-kubeconfig
---
apiVersion: container.gcp-beta.upbound.io/v1beta2
kind: NodePool
metadata:
  name: ${GKE_MGMT_CLUSTER}-pool
  namespace: gke
spec:
  forProvider:
    clusterRef:
      name: ${GKE_MGMT_CLUSTER}
    maxPodsPerNode: 32
    nodeConfig:
      spot: true
      machineType: ${MGMT_NODE_MACHINE_TYPE}
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
