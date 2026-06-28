# Tasks: openfga-kagent-authz-poc

**Prerequisite:** `kagent-runtime-validation` must be complete before starting T1.

## T1 — Resolve unknowns from live cluster

Before writing any code, confirm the four unknowns documented in design.md.

- [ ] Inspect the kagent v1alpha2 Agent CRD for `requireApproval` field: name, nesting,
      and whether an `approvalEndpoint` URL can be configured.
      `kubectl get crd agents.kagent.dev -o jsonpath='{.spec.versions[?(@.name=="v1alpha2")].schema}' | jq . --context <apps-dev>`
- [ ] Deploy a stub HTTP server (e.g. `httpbin` or `python3 -m http.server`) as the
      `requireApproval` endpoint, add one destructive tool to `requireApproval` in
      k8s-agent, trigger a tool call, and capture the exact request payload.
- [ ] Confirm the expected response schema (check kagent controller source or logs for
      what it reads from the approval response body).
- [ ] List MCP tool names as registered: check kagent-tools or kmcp pod logs for
      registered tool names (look for `k8s_delete_resource` vs `DeleteResource` etc.).
- [ ] Document all four answers — update `specs/approval-webhook.md` with confirmed field
      names before proceeding to T2.

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
- [ ] Write bootstrap Job manifest (curl-based or Python) that:
      - Creates the store → captures store_id
      - Writes the authorization model
      - Seeds read-only tuples for k8s_get_resources and k8s_list_resources
      - Writes store_id to ConfigMap `openfga-store` in `kagent-system`
- [ ] Add Job and ConfigMap to `kubernetes/namespaces/base/openfga/`.
- [ ] Commit and verify Job completes; confirm ConfigMap contains store_id.

## T4 — Build and deploy approval webhook

See `specs/approval-webhook.md`.

- [ ] Write `apps/openfga-approval-webhook/main.py` (FastAPI, using confirmed field names
      from T1).
- [ ] Write `apps/openfga-approval-webhook/Dockerfile` and `requirements.txt`.
- [ ] Build and push image to Artifact Registry.
- [ ] Write `kubernetes/namespaces/base/kagent/kagent/config/approval-webhook-deployment.yaml`
      (Deployment + Service, using openfga-store ConfigMap for store_id env var).
- [ ] Add to `kubernetes/namespaces/base/kagent/kagent/config/kustomization.yaml`.
- [ ] Commit and verify webhook pod is Running; smoke-test with curl POST /approve.

## T5 — Wire k8s-agent requireApproval

See `specs/kagent-integration.md`.

- [ ] Add `requireApproval` block to `kubernetes/namespaces/base/kagent/kagent/config/k8s-agent.yaml`
      listing `k8s_delete_resource` and `k8s_apply_resource` with the webhook URL.
- [ ] Commit; verify k8s-agent reconciles without error.
- [ ] Pre-create test ConfigMap: `kubectl create configmap test-delete-me -n default --context <apps-dev>`.

## T6 — Validate end-to-end

See `specs/kagent-integration.md`.

- [ ] Step 1: Send delete prompt to k8s-agent — confirm tool call is blocked (no tuple).
      Capture webhook log showing `{"allowed": false}` from OpenFGA.
- [ ] Step 2: Write tuple at runtime via curl to OpenFGA `/write` endpoint. No restart.
- [ ] Step 3: Repeat delete prompt — confirm tool call now succeeds. Capture webhook log
      showing `{"allowed": true}`.
- [ ] ConfigMap `test-delete-me` is gone after step 3.
- [ ] Document the three log snippets (blocked, tuple write, allowed) in issue #103 comment.
