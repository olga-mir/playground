"""
OpenFGA deployment and the two authorization arms documented in
docs/kagent-authz.md: the MCP proxy gating k8s-agent's raw tools (arm 1,
manually validated 2026-08-15, never automated), and k8s-troubleshooter-mcp's
baked-in per-namespace check (arm 2, deployed but — per that doc's Status
table — its read/deny/RBAC scenarios were "not yet run").

Determinism: every check here calls the OpenFGA HTTP API or the MCP JSON-RPC
protocol directly, and RBAC is verified via SubjectAccessReview. None of this
sends a prompt to an agent or asserts on LLM output — consistent with the
suite's determinism contract (conftest.py).

Not covered here (deliberately, see docs/kagent-authz.md walkthrough 2):
  - Fail-closed behavior (patching OPENFGA_URL to an invalid value) mutates a
    live Deployment's env and is better suited to a unit test of
    apps/k8s-troubleshooter-mcp/src/authz.py's `except Exception: return False`
    than a routinely-run e2e test against a shared disposable cluster.
"""

import logging

import pytest
import requests
from kubernetes import client
from conftest import (
    core_v1,
    k8s_api,
    get_resource,
    wait_for_condition,
    wait_for_deployment_ready,
    port_forward,
)

logger = logging.getLogger(__name__)

OPENFGA_NAMESPACE = "openfga"
KAGENT_SYSTEM = "kagent-system"
TEAM_ALPHA = "team-alpha"
STORE_NAME = "kagent-authz"

# Mirrors kubernetes/namespaces/base/team-alpha/troubleshooter/openfga-model-job.yaml —
# written idempotently at test time so these tests don't depend on that one-shot
# Job's ttlSecondsAfterFinished window, or on it having run since the last
# openfga pod restart (memory datastore; see the Job manifest's own POC-limitation note).
TROUBLESHOOTER_MODEL_TYPES = [
    {"type": "agent", "relations": {}},
    {
        "type": "tool",
        "relations": {"can_be_invoked_by": {"this": {}}},
        "metadata": {"relations": {"can_be_invoked_by": {
            "directly_related_user_types": [{"type": "agent"}]
        }}},
    },
    {
        "type": "namespace",
        "relations": {"can_diagnose": {"this": {}}},
        "metadata": {"relations": {"can_diagnose": {
            "directly_related_user_types": [{"type": "agent"}]
        }}},
    },
]
TROUBLESHOOTER_AGENT_ID = "k8s-troubleshooter-agent"
TROUBLESHOOTER_SA = "system:serviceaccount:team-alpha:troubleshooter-mcp"


# ── deployment health ─────────────────────────────────────────────────────────

@pytest.mark.apps_dev
@pytest.mark.openfga
def test_openfga_helmrelease_ready(ctx_apps_dev):
    wait_for_condition(
        ctx_apps_dev,
        "helm.toolkit.fluxcd.io", "v2", "helmreleases",
        OPENFGA_NAMESPACE, "openfga",
    )


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_openfga_pod_running(ctx_apps_dev):
    v1 = core_v1(ctx_apps_dev)
    pods = v1.list_namespaced_pod(OPENFGA_NAMESPACE, label_selector="app.kubernetes.io/name=openfga")
    running = [p for p in pods.items if p.status.phase == "Running"]
    assert running, f"No Running openfga pods. Found: {[(p.metadata.name, p.status.phase) for p in pods.items]}"


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_openfga_mcp_proxy_pod_running(ctx_apps_dev):
    v1 = core_v1(ctx_apps_dev)
    pods = v1.list_namespaced_pod(KAGENT_SYSTEM, label_selector="app=openfga-mcp-proxy")
    running = [p for p in pods.items if p.status.phase == "Running"]
    assert running, f"No Running openfga-mcp-proxy pods. Found: {[(p.metadata.name, p.status.phase) for p in pods.items]}"


# ── arm 1: MCP proxy gating k8s-agent's raw tools ────────────────────────────

def _mcp_initialize(base_url: str) -> str:
    """Perform the MCP handshake against the proxy; return the session id."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    resp = requests.post(
        f"{base_url}/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "e2e-test", "version": "1.0"},
            },
        },
        timeout=10,
    )
    resp.raise_for_status()
    sid = resp.headers.get("Mcp-Session-Id")
    assert sid, f"proxy did not return Mcp-Session-Id on initialize: {resp.headers}"

    requests.post(
        f"{base_url}/mcp",
        headers={**headers, "Mcp-Session-Id": sid},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        timeout=10,
    )
    return sid


def _mcp_tool_call(base_url: str, sid: str, tool_name: str, arguments: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Mcp-Session-Id": sid,
    }
    resp = requests.post(
        f"{base_url}/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_proxy_gated_readonly_tool_call_allowed(ctx_apps_dev):
    """
    k8s-agent is pre-seeded (by openfga-mcp-proxy on startup) with can_be_invoked_by
    on read-only tools — k8s_get_resources must pass through to the upstream
    kagent-tools server and return a result, not an OpenFGA-denial error.
    """
    with port_forward(ctx_apps_dev, KAGENT_SYSTEM, "svc/openfga-mcp-proxy", 8080) as base_url:
        sid = _mcp_initialize(base_url)
        body = _mcp_tool_call(
            base_url, sid, "k8s_get_resources",
            {"resource_type": "pods", "namespace": KAGENT_SYSTEM},
        )
        assert "error" not in body, f"expected read-only tool call to be allowed, got: {body}"
        logger.info("k8s_get_resources allowed through the proxy as expected")


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_proxy_gated_destructive_tool_call_denied(ctx_apps_dev):
    """
    k8s_delete_resource has no can_be_invoked_by tuple for k8s-agent — the
    proxy must deny it before ever reaching the upstream tool server.
    """
    with port_forward(ctx_apps_dev, KAGENT_SYSTEM, "svc/openfga-mcp-proxy", 8080) as base_url:
        sid = _mcp_initialize(base_url)
        body = _mcp_tool_call(base_url, sid, "k8s_delete_resource", {})
        error = body.get("error", {})
        assert "denied by OpenFGA policy" in error.get("message", ""), \
            f"expected an OpenFGA-policy denial, got: {body}"
        logger.info("k8s_delete_resource correctly denied by the proxy")


# ── arm 2: k8s-troubleshooter-mcp's baked-in per-namespace check ────────────

@pytest.mark.apps_dev
@pytest.mark.openfga
def test_k8s_troubleshooter_remotemcpserver_exists(ctx_apps_dev):
    obj = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "remotemcpservers", TEAM_ALPHA,
        "k8s-troubleshooter",
    )
    assert obj["spec"]["url"].endswith("/mcp")


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_k8s_troubleshooter_agent_ready(ctx_apps_dev):
    wait_for_condition(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2", "agents",
        TEAM_ALPHA, "k8s-troubleshooter-agent",
    )


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_k8s_troubleshooter_deployment_running(ctx_apps_dev):
    wait_for_deployment_ready(ctx_apps_dev, TEAM_ALPHA, "k8s-troubleshooter-mcp")


def _openfga_store_id(base_url: str) -> str:
    resp = requests.get(f"{base_url}/stores", timeout=10)
    resp.raise_for_status()
    for store in resp.json().get("stores", []):
        if store["name"] == STORE_NAME:
            return store["id"]
    pytest.fail(
        f"OpenFGA store '{STORE_NAME}' not found — has openfga-mcp-proxy or the "
        f"troubleshooter seed Job ever run against this cluster?"
    )


def _seed_troubleshooter_model_and_tuple(base_url: str, store_id: str) -> None:
    """Idempotently (re-)write the namespace/can_diagnose model + tuple — see
    module docstring for why this happens at test time rather than relying on
    the one-shot seed Job."""
    resp = requests.post(
        f"{base_url}/stores/{store_id}/authorization-models",
        json={"schema_version": "1.1", "type_definitions": TROUBLESHOOTER_MODEL_TYPES},
        timeout=10,
    )
    resp.raise_for_status()

    tuple_key = {
        "user": f"agent:{TROUBLESHOOTER_AGENT_ID}",
        "relation": "can_diagnose",
        "object": f"namespace:{TEAM_ALPHA}",
    }
    resp = requests.post(
        f"{base_url}/stores/{store_id}/write",
        json={"writes": {"tuple_keys": [tuple_key]}},
        timeout=10,
    )
    if resp.status_code >= 400 and "already exists" not in resp.text.lower():
        resp.raise_for_status()


def _openfga_check(base_url: str, store_id: str, namespace: str) -> bool:
    resp = requests.post(
        f"{base_url}/stores/{store_id}/check",
        json={"tuple_key": {
            "user": f"agent:{TROUBLESHOOTER_AGENT_ID}",
            "relation": "can_diagnose",
            "object": f"namespace:{namespace}",
        }},
        timeout=10,
    )
    resp.raise_for_status()
    return bool(resp.json().get("allowed", False))


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_can_diagnose_authorized_namespace_allowed(ctx_apps_dev):
    """agent:k8s-troubleshooter-agent must be allowed to diagnose team-alpha."""
    with port_forward(ctx_apps_dev, OPENFGA_NAMESPACE, "svc/openfga", 8080) as base_url:
        store_id = _openfga_store_id(base_url)
        _seed_troubleshooter_model_and_tuple(base_url, store_id)
        allowed = _openfga_check(base_url, store_id, TEAM_ALPHA)
        assert allowed, "expected can_diagnose(team-alpha) to be allowed after seeding the tuple"


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_can_diagnose_unauthorized_namespace_denied(ctx_apps_dev):
    """No tuple grants can_diagnose on kube-system — must deny by default."""
    with port_forward(ctx_apps_dev, OPENFGA_NAMESPACE, "svc/openfga", 8080) as base_url:
        store_id = _openfga_store_id(base_url)
        _seed_troubleshooter_model_and_tuple(base_url, store_id)
        allowed = _openfga_check(base_url, store_id, "kube-system")
        assert not allowed, "expected can_diagnose(kube-system) to be denied — no tuple grants it"


# ── RBAC: the ServiceAccount backing k8s-troubleshooter-mcp must be read-only ─

def _can_i(ctx_apps_dev, verb: str, resource: str) -> bool:
    # conftest only exposes Core/Apps/CustomObjects clients — Authorization needs its own.
    api = client.AuthorizationV1Api(api_client=k8s_api(ctx_apps_dev))
    review = client.V1SubjectAccessReview(
        spec=client.V1SubjectAccessReviewSpec(
            user=TROUBLESHOOTER_SA,
            resource_attributes=client.V1ResourceAttributes(verb=verb, resource=resource),
        )
    )
    result = api.create_subject_access_review(review)
    return bool(result.status.allowed)


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_troubleshooter_sa_can_list_pods(ctx_apps_dev):
    assert _can_i(ctx_apps_dev, "list", "pods"), \
        f"{TROUBLESHOOTER_SA} should be allowed to list pods per its ClusterRole"


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_troubleshooter_sa_cannot_delete_pods(ctx_apps_dev):
    assert not _can_i(ctx_apps_dev, "delete", "pods"), \
        f"{TROUBLESHOOTER_SA} must not be allowed to delete pods — read-only ClusterRole"


@pytest.mark.apps_dev
@pytest.mark.openfga
def test_troubleshooter_sa_cannot_list_secrets(ctx_apps_dev):
    assert not _can_i(ctx_apps_dev, "list", "secrets"), \
        f"{TROUBLESHOOTER_SA}'s ClusterRole does not grant secrets access"
