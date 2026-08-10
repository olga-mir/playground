# Tasks: k8s-troubleshooter

## Progress
0 / 18 complete

## Implementation Tasks

### Phase: Setup

- [ ] Scaffold `apps/k8s-troubleshooter-mcp/` — `pyproject.toml` (FastAPI, mcp, kubernetes-asyncio, openfga-sdk), `Dockerfile` (multi-stage, port 8080), `src/` directory structure (`server.py`, `k8s_client.py`, `authz.py`, `tools/`)
- [ ] Write OpenFGA authorization model DSL extension — add `namespace` object type with `can_diagnose` relation, preserving existing `tool` type and `can_be_invoked_by` relation

### Phase: MCP Server — Core

- [ ] Implement `authz.py` — async OpenFGA check helper; reads `OPENFGA_HOST`, `OPENFGA_STORE_ID`, `AGENT_ID` from env; 2s timeout; fails closed on any error (returns `False`, never raises)
- [ ] Implement `k8s_client.py` — async Kubernetes API wrappers using `kubernetes_asyncio`; `load_incluster_config()` on init; surface `ApiException` as structured dicts, never raise to callers
- [ ] Implement `tools/diagnose_namespace.py` — `authz.check(namespace)` guard; parallel `asyncio.gather` for pod statuses, Warning events (last 1h), ResourceQuota usage, CrashLoopBackOff/OOMKilled containers; return single structured dict
- [ ] Implement `tools/get_pod_failure_context.py` — `authz.check(namespace)` guard; correlate tail-100 logs (all containers), describe output, and pod-scoped events into a single response
- [ ] Implement `tools/get_namespace_resource_pressure.py` — `authz.check(namespace)` guard; collect ResourceQuota usage vs limits, LimitRange defaults, and node pressure conditions (DiskPressure, MemoryPressure, PIDPressure) for nodes running pods in the namespace
- [ ] Implement `server.py` — `FastMCP` app with `transport="streamable-http"` on `/mcp`; register all three tools; wire `AGENT_ID` env var into each tool handler via closure or dependency injection

### Phase: Kubernetes Manifests

- [ ] Write `serviceaccount.yaml`, `clusterrole.yaml`, `clusterrolebinding.yaml` — SA `troubleshooter-mcp` in `team-alpha`; ClusterRole grants only `get`+`list` on `pods`, `events`, `nodes`, `resourcequotas`, `limitranges`; no write verbs, no secrets, no exec
- [ ] Write `deployment.yaml` + `service.yaml` — Deployment references the MCP server image with `AGENT_ID`, `OPENFGA_HOST`, `OPENFGA_STORE_ID` env vars (latter two from `openfga-store` ConfigMap); Service ClusterIP port 8080
- [ ] Write `toolserver.yaml` — `ToolServer` CR named `k8s-troubleshooter` in `team-alpha`; `spec.url: http://k8s-troubleshooter-mcp.team-alpha.svc.cluster.local:8080/mcp`
- [ ] Write `agent.yaml` — `Agent` CR `k8s-troubleshooter-agent` in `team-alpha`; `spec.declarative.tools` lists only `k8s-troubleshooter` ToolServer; system prompt constrains to read-only diagnostics, structured output, no mutation
- [ ] Write `openfga-model-job.yaml` — Kubernetes `Job` (`restartPolicy: OnFailure`) that POSTs updated model DSL to OpenFGA, then writes the `(agent:k8s-troubleshooter-agent, can_diagnose, namespace:team-alpha)` tuple; handles `already exists` (write-or-ignore)
- [ ] Write `imagerepository.yaml` + `imagepolicy.yaml` — Flux image automation for `${REGION}-docker.pkg.dev/${PROJECT_ID}/platform/k8s-troubleshooter-mcp`
- [ ] Write `kustomization.yaml` wiring all resources; add `dependsOn` in the Flux `Kustomization` CR referencing the `openfga-kagent-authz-poc` kustomization to ensure the `openfga-store` ConfigMap is populated before this deploys

### Phase: Testing

- [ ] Verify ToolServer Ready: `kubectl get toolserver k8s-troubleshooter -n team-alpha --context <control-plane>` shows `Ready` and three tools in status
- [ ] Verify scenario — authorized namespace: send prompt to `k8s-troubleshooter-agent` requesting `diagnose_namespace("team-alpha")`; confirm structured diagnostic result returned
- [ ] Verify scenario — unauthorized namespace: send prompt requesting `diagnose_namespace("kube-system")`; confirm MCP error (403) returned and no Kubernetes API calls are logged
- [ ] Verify scenario — fail-closed: patch Deployment with invalid `OPENFGA_HOST`; confirm all three tools return errors; restore env var
- [ ] Verify RBAC: exec into MCP server pod and run `kubectl auth can-i list pods --as system:serviceaccount:team-alpha:troubleshooter-mcp` (expect yes) and `kubectl auth can-i delete pods --as ...` (expect no)
