# Tasks: openfga-kagent-authz-poc

**Prerequisite:** `kagent-runtime-validation` must be complete before starting T1.

## T1 — Discover MCP transport and tool names from live cluster

See `specs/mcp-proxy.md` (Transport discovery section).

- [x] Find the `kagent-tools` Service name and port in `kagent-system`.
- [x] Inspect auto-created ToolServer CRs to confirm transport (SSE vs StreamableHttp)
      and the upstream URL format.
- [x] Capture exact MCP tool names as registered (especially `k8s_delete_resource`,
      `k8s_apply_manifest`, `k8s_get_resources`, `k8s_list_resources`).
- [x] Determine whether HelmRelease values support disabling auto-wired tool servers
      per-agent (to avoid duplicate tool entries on k8s-agent).
- [x] Update `specs/mcp-proxy.md` with confirmed transport type and `UPSTREAM_MCP_URL`
      value before proceeding to T4.

## T2 — Deploy OpenFGA

See `specs/openfga-deployment.md`.

- [x] Write `kubernetes/namespaces/base/openfga/namespace.yaml`.
- [x] Write `kubernetes/namespaces/base/openfga/helm/openfga-helm-repo.yaml` (HelmRepository).
- [x] Write `kubernetes/namespaces/base/openfga/helm/openfga-release.yaml` (HelmRelease,
      memory datastore, pin chart version).
- [x] Write kustomization files for the openfga base.
- [x] Add `- ../../base/openfga` to `kubernetes/namespaces/overlays/apps-dev/kustomization.yaml`.
- [x] Commit and push; wait for HelmRelease to reconcile and pod to reach `Running`.
- [x] Verify: `curl http://openfga.openfga.svc.cluster.local:8080/healthz` returns
      `{"status":"SERVING"}` (via kubectl exec).

## T3 — Bootstrap: store, model, and initial tuples

See `specs/authorization-model.md`.

- [x] Write authorization model JSON (from DSL in spec) into a ConfigMap.
- [x] Write bootstrap Job manifest that:
      - Creates the store → captures store_id
      - Writes the authorization model
      - Seeds read-only tuples for `k8s_get_resources` and `k8s_list_resources`
        (exact names confirmed in T1)
      - Patches ConfigMap `openfga-store` in `kagent-system` with the store_id
- [x] Add Job and ConfigMap skeleton to `kubernetes/namespaces/base/openfga/`.
- [x] Commit and verify Job completes; confirm ConfigMap `openfga-store` in `kagent-system`
      contains a non-empty `store_id`.

## T4 — Build and deploy MCP proxy

See `specs/mcp-proxy.md`.

- [x] Write `apps/openfga-mcp-proxy/main.py` using the transport confirmed in T1
      (StreamableHttp preferred; SSE if required).
- [x] Write `apps/openfga-mcp-proxy/Dockerfile` and `requirements.txt`.
- [x] Build and push image to Artifact Registry.
- [x] Write `kubernetes/namespaces/base/kagent/kagent/config/mcp-proxy-deployment.yaml`
      containing Deployment, Service, and ToolServer `k8s-tools-gated`.
      Set `AGENT_ID=k8s-agent` and `UPSTREAM_MCP_URL` (confirmed in T1) in the Deployment.
- [x] Add to `kubernetes/namespaces/base/kagent/kagent/config/kustomization.yaml`.
- [x] Commit; verify proxy pod is Running.
- [x] Smoke-test directly: send a raw MCP tool call to the proxy and confirm it calls
      OpenFGA and returns the expected result.

## T5 — Wire k8s-agent to the proxy ToolServer

See `specs/kagent-integration.md`.

- [x] Add explicit `tools` entry in `k8s-agent.yaml` referencing `k8s-tools-gated`
      with tool names confirmed in T1.
- [x] If HelmRelease supports per-agent tool server disable, add that value.
- [x] Commit; verify k8s-agent reconciles without error and ToolServer appears in
      agent status.
- [x] Pre-create test resource: `kubectl create configmap test-delete-me -n default
      --context <apps-dev>`.

## T6 — Validate end-to-end

See `specs/kagent-integration.md`.

- [x] Step 1: Send read-only prompt — confirm k8s_list_resources passes through
      (seeded tuple). Capture proxy log showing `{"allowed": true}`.
- [x] Step 2: Send delete prompt — confirm k8s_delete_resource is blocked (no tuple).
      Capture proxy log showing `{"allowed": false}`. Confirm ConfigMap still exists.
- [x] Step 3: Write delete tuple at runtime via curl (no restart). Repeat delete
      prompt — confirm ConfigMap is deleted. Capture proxy log showing `{"allowed": true}`.
- [x] Post the three log snippets as a comment on issue #103.
