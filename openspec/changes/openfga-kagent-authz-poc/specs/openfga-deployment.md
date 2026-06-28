# Spec: OpenFGA Deployment

## Goal

Deploy OpenFGA on apps-dev via Flux GitOps using the memory datastore. OpenFGA must be
reachable from within the cluster at a stable service DNS name.

## Helm chart

- Chart: `openfga/openfga` from `https://openfga.github.io/helm-charts`
- Version: latest stable at implementation time (pin in HelmRelease)
- Namespace: `openfga` (new, created by Flux)

## Kustomize layout

```
kubernetes/namespaces/base/openfga/
  namespace.yaml
  helm/
    openfga-helm-repo.yaml
    openfga-release.yaml
    kustomization.yaml
  kustomization.yaml
```

Add `- ../../base/openfga` to `kubernetes/namespaces/overlays/apps-dev/kustomization.yaml`.

## HelmRelease values (memory datastore)

```yaml
datastore:
  engine: memory
grpc:
  enabled: true   # for SDK calls from the webhook
http:
  enabled: true   # for /healthz and manual curl-based validation
```

No PVC, no external DB, no credentials needed.

## Service endpoint

After deploy, OpenFGA exposes:
- HTTP API: `http://openfga.openfga.svc.cluster.local:8080`
- gRPC: `openfga.openfga.svc.cluster.local:8081`

The approval webhook will use the HTTP API (`/stores`, `/check`).

## Store and model bootstrap

Since the memory datastore starts empty, a one-shot Kubernetes Job runs after the
HelmRelease is Ready to:

1. Create the store: `POST /stores` → capture `store_id`
2. Write the authorization model: `POST /stores/{id}/authorization-models`
3. Write initial "allow" tuples for read-only tools

The Job image can be `curlimages/curl` (model as inline JSON in a ConfigMap) or a small
Python script. Store ID is written to a ConfigMap for the webhook to read at startup.

## Pass criteria

- HelmRelease `openfga` in namespace `openfga` is `Ready: True`.
- `curl http://openfga.openfga.svc.cluster.local:8080/healthz` returns `{"status":"SERVING"}`.
- Bootstrap Job completes successfully and ConfigMap `openfga-store` contains a `store_id`.
