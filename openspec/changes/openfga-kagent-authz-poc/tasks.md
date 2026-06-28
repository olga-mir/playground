# Tasks: openfga-kagent-authz-poc

**Prerequisite:** `kagent-runtime-validation` must be complete before starting T1.

## T1 — Discover MCP transport and tool names from live cluster

See `specs/mcp-proxy.md` (Transport discovery section).

- [ ] Find the `kagent-tools` Service name and port in `kagent-system`.
- [ ] Inspect auto-created ToolServer CRs to confirm transport (SSE vs StreamableHttp)
      and the upstream URL format.
- [ ] Capture exact MCP tool names as registered (especially `k8s_delete_resource`,
      `k8s_apply_manifest`, `k8s_get_resources`, `k8s_list_resources`).
- [ ] Determine whether HelmRelease values support disabling auto-wired tool servers
      per-agent (to avoid duplicate tool entries on k8s-agent).
- [ ] Update `specs/mcp-proxy.md` with confirmed transport type and `UPSTREAM_MCP_URL`
      value before proceeding to T4.

## T2 — Deploy OpenFGA

See `specs/openfga-deployment.md`.

- [ ] Write `kubernetes/namespaces/base/openfga/namespace.yaml`.
- [ ] Write `kubernetes/namespaces/base/openfga/helm/openfga-helm-repo.yaml` (HelmRepository).
- [ ] Write `kubernetes/namespaces/base/openfga/helm/openfga-release.yaml` (HelmRelease,
      memory datastore, pin chart version).
- [ ] Write kustomization files for the openfga base.
- [ ] Add `- ../../base/openfga` to `kubernetes/namespaces/overlays/apps-dev/kustomization.yaml`.
- [ ] Commit and push; wait for HelmRelease to reconcile and pod to reach `Running`.
- [ ] Verify: `curl http://openfga.openfga.svc.cluster.local:8080/healthz` returns
      `{"status":"SERVING"}` (via kubectl exec).

## T3 — Bootstrap: store, model, and initial tuples

See `specs/authorization-model.md`.

- [ ] Write authorization model JSON (from DSL in spec) into a ConfigMap.
- [ ] Write bootstrap Job manifest that:
      - Creates the store → captures store_id
      - Writes the authorization model
      - Seeds read-only tuples for `k8s_get_resources` and `k8s_list_resources`
        (exact names confirmed in T1)
      - Patches ConfigMap `openfga-store` in `kagent-system` with the store_id
- [ ] Add Job and ConfigMap skeleton to `kubernetes/namespaces/base/openfga/`.
- [ ] Commit and verify Job completes; confirm ConfigMap `openfga-store` in `kagent-system`
      contains a non-empty `store_id`.

## T4 — Build and deploy MCP proxy

See `specs/mcp-proxy.md`.

- [ ] Write `apps/openfga-mcp-proxy/main.py` using the transport confirmed in T1
      (StreamableHttp preferred; SSE if required).
- [ ] Write `apps/openfga-mcp-proxy/Dockerfile` and `requirements.txt`.
- [ ] Build and push image to Artifact Registry.
- [ ] Write `kubernetes/namespaces/base/kagent/kagent/config/mcp-proxy-deployment.yaml`
      containing Deployment, Service, and ToolServer `k8s-tools-gated`.
      Set `AGENT_ID=k8s-agent` and `UPSTREAM_MCP_URL` (confirmed in T1) in the Deployment.
- [ ] Add to `kubernetes/namespaces/base/kagent/kagent/config/kustomization.yaml`.
- [ ] Commit; verify proxy pod is Running.
- [ ] Smoke-test directly: send a raw MCP tool call to the proxy and confirm it calls
      OpenFGA and returns the expected result.

## T5 — Wire k8s-agent to the proxy ToolServer

See `specs/kagent-integration.md`.

- [ ] Add explicit `tools` entry in `k8s-agent.yaml` referencing `k8s-tools-gated`
      with tool names confirmed in T1.
- [ ] If HelmRelease supports per-agent tool server disable, add that value.
- [ ] Commit; verify k8s-agent reconciles without error and ToolServer appears in
      agent status.
- [ ] Pre-create test resource: `kubectl create configmap test-delete-me -n default
      --context <apps-dev>`.

## T6 — Validate end-to-end

See `specs/kagent-integration.md`.

- [ ] Step 1: Send read-only prompt — confirm k8s_list_resources passes through
      (seeded tuple). Capture proxy log showing `{"allowed": true}`.
- [ ] Step 2: Send delete prompt — confirm k8s_delete_resource is blocked (no tuple).
      Capture proxy log showing `{"allowed": false}`. Confirm ConfigMap still exists.
- [ ] Step 3: Write delete tuple at runtime via curl (no restart). Repeat delete
      prompt — confirm ConfigMap is deleted. Capture proxy log showing `{"allowed": true}`.
- [ ] Post the three log snippets as a comment on issue #103.
