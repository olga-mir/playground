# Disclaimer

This folder is not part of the demo. This is the quickest way I had based on previous projects to spin up real infrastructure in the cloud enviroment.

Scripts and config in this folder serves two purposes:

1. Create infra for the project playground which consists of one management and at least one workload clusters.
2. Inject credentials into infra setup. In most cases there are better ways to configure components with required credentials, but this is for now out of scope for this project

# Deploy

## Prerequisites

* `kind` (CLI only, the cluster is installed as part of the setup)
* Taskfile
* access to GCP project with sufficient permissions to create GKE clusters and manage IAM

## Deploy

Create env file with following vars and source it:

```
export GKE_VPC=
export MGMT_SUBNET_NAME=""
export APPS_DEV_SUBNET_NAME=""
export GKE_MGMT_CLUSTER=
export GKE_APPS_DEV_CLUSTER=
export MGMT_NODE_MACHINE_TYPE=
export MGMT_NODE_COUNT=
export APPS_DEV_NODE_MACHINE_TYPE=
export APPS_DEV_NODE_COUNT=
export CROSSPLANE_GSA_KEY_FILE=""
export REGION=
export PROJECT_ID=
```

For AI projects, API Keys are also required to be set as secrets in k8s.

The full setup, including all required components on GKE clusters can be deployed automatically in one of two ways. To install with Argo:

```
$ task setup:auto-deploy
```

Or without Argo, applying deployment manifests manually or with scripts to speed up iteration and avoid another "moving part", install without argo:

```
$ task setup:deploy-without-argo
```

## ArgoCD CMP Plugin

It beats me why it is implemented this way in Argo, but it is what it is. In Flux you'd do `substituteFrom` and be on your merry way.

This is notoriously hard to escape properly in such a way that only "export" part is `envsubst` while the other bits stay intact.
This configmap has to be exactly the way it is below, with only `REDACTED` placeholders substituted with real values.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-envsubst-plugin
  namespace: argocd
data:
  plugin.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata:
      name: env-substitution-plugin
      namespace: argocd
    spec:
      generate:
        command: ["sh", "-c"]
        args: ["export PROJECT_ID=<REDACTED> PROJECT_NUMBER=<REDACTED> && for file in *.yaml; do echo '---'; if grep -q '\\${PROJECT_' \"$file\"; then cat \"$file\" | sed 's/\\${PROJECT_ID}/'$PROJECT_ID'/g; s/\\${PROJECT_NUMBER}/'$PROJECT_NUMBER'/g'; else cat \"$file\"; fi; done"]
```
