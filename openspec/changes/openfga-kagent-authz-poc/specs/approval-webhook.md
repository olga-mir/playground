# Spec: Approval Webhook

## Goal

A minimal HTTP service that receives kagent's approval callback, calls OpenFGA `Check`,
and returns approve or reject — enabling tuple-driven tool gating without UI interaction.

## Unknowns to resolve first (from live cluster)

Before implementing, confirm from the live cluster:

1. **Callback URL format** — what URL does kagent POST to when `requireApproval` triggers?
   Check kagent Agent CRD spec or controller logs.
2. **Request payload schema** — what JSON does kagent send? Likely includes tool name and
   agent context. Check controller source or intercept with a stub HTTP server.
3. **Response schema** — what does kagent expect back? Likely `{"approved": true/false}` or
   similar. Check controller source.
4. **Timeout** — how long does kagent wait before treating non-response as rejection?

Discovery approach: deploy a stub `httpbin`-style service as the `requireApproval` endpoint,
trigger a tool call, inspect the logged request payload.

## Service design

Language: Python (FastAPI), containerised.

```
apps/openfga-approval-webhook/
  main.py
  Dockerfile
  requirements.txt
```

Core logic (pseudocode):

```python
@app.post("/approve")
async def approve(request: Request):
    body = await request.json()
    agent_id = f"agent:{body['agent_name']}"   # exact field TBD from discovery
    tool_id  = f"tool:{body['tool_name']}"     # exact field TBD from discovery

    store_id = os.environ["OPENFGA_STORE_ID"]  # from ConfigMap via envFrom
    resp = httpx.post(
        f"http://openfga.openfga.svc.cluster.local:8080/stores/{store_id}/check",
        json={"tuple_key": {"user": agent_id, "relation": "can_be_invoked_by", "object": tool_id}}
    )
    allowed = resp.json().get("allowed", False)
    return {"approved": allowed}   # exact response schema TBD
```

## Kubernetes manifests

Deployed in `kagent-system` (same namespace as k8s-agent — avoids NetworkPolicy issues):

```
kubernetes/namespaces/base/kagent/kagent/config/
  approval-webhook-deployment.yaml   # Deployment + Service
```

```yaml
# Deployment key fields
image: <gcr or artifact registry>/openfga-approval-webhook:latest
env:
  - name: OPENFGA_STORE_ID
    valueFrom:
      configMapKeyRef:
        name: openfga-store
        key: store_id
```

Service: `ClusterIP`, port 8080, name `openfga-approval-webhook`.

## Image build and publish

For the POC, build locally and push to Artifact Registry:

```bash
docker build -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/platform/openfga-approval-webhook:poc \
  apps/openfga-approval-webhook/
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/platform/openfga-approval-webhook:poc
```

Or use Cloud Build if a trigger is already wired.

## Pass criteria

- Webhook pod is Running in `kagent-system`.
- A `curl POST /approve` with a tuple that exists returns `{"approved": true}`.
- A `curl POST /approve` with a tool that has no tuple returns `{"approved": false}`.
- kagent correctly treats the response and proceeds or blocks the tool call.
