"""MCP StreamableHttp proxy with OpenFGA authorization.

Sits between a kagent agent and the kagent-tools MCP server. For every
tools/call the proxy checks OpenFGA before forwarding. Agent identity is
fixed at deploy time via AGENT_ID env var (one instance per agent).

On startup the proxy creates (or reopens) an OpenFGA store named
"kagent-authz", writes the authorization model, and seeds read-only allow
tuples. Because kagent uses the memory datastore the proxy must re-initialize
on every restart of either service.
"""

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

AGENT_ID = os.environ["AGENT_ID"]
UPSTREAM_MCP_URL = os.environ["UPSTREAM_MCP_URL"]
OPENFGA_URL = os.environ["OPENFGA_URL"]
STORE_NAME = "kagent-authz"

# Pre-seeded as allowed — read-only k8s tools AGENT_ID may call freely.
READ_ONLY_TOOLS = [
    "k8s_get_resources",
    "k8s_describe_resource",
    "k8s_get_events",
    "k8s_get_pod_logs",
    "k8s_get_resource_yaml",
    "k8s_get_available_api_resources",
    "k8s_get_cluster_configuration",
    "k8s_check_service_connectivity",
]

# OpenFGA schema 1.1: agent type + tool type with can_be_invoked_by relation.
AUTH_MODEL = {
    "schema_version": "1.1",
    "type_definitions": [
        {"type": "agent", "relations": {}},
        {
            "type": "tool",
            "relations": {"can_be_invoked_by": {"this": {}}},
            "metadata": {
                "relations": {
                    "can_be_invoked_by": {
                        "directly_related_user_types": [{"type": "agent"}]
                    }
                }
            },
        },
    ],
}

_http: httpx.AsyncClient | None = None
_store_id: str | None = None
# Map proxy-issued session IDs to upstream session IDs.
_sessions: dict[str, str] = {}


async def _init_openfga() -> None:
    global _store_id

    resp = await _http.get(f"{OPENFGA_URL}/stores")
    resp.raise_for_status()
    for store in resp.json().get("stores", []):
        if store["name"] == STORE_NAME:
            _store_id = store["id"]
            log.info("openfga: found existing store store_id=%s", _store_id)
            return

    resp = await _http.post(f"{OPENFGA_URL}/stores", json={"name": STORE_NAME})
    resp.raise_for_status()
    _store_id = resp.json()["id"]
    log.info("openfga: created store store_id=%s", _store_id)

    resp = await _http.post(
        f"{OPENFGA_URL}/stores/{_store_id}/authorization-models",
        json=AUTH_MODEL,
    )
    resp.raise_for_status()
    log.info(
        "openfga: created model model_id=%s",
        resp.json()["authorization_model_id"],
    )

    tuples = [
        {
            "user": f"agent:{AGENT_ID}",
            "relation": "can_be_invoked_by",
            "object": f"tool:{tool}",
        }
        for tool in READ_ONLY_TOOLS
    ]
    resp = await _http.post(
        f"{OPENFGA_URL}/stores/{_store_id}/write",
        json={"writes": {"tuple_keys": tuples}},
    )
    resp.raise_for_status()
    log.info("openfga: seeded %d read-only tuples for agent:%s", len(tuples), AGENT_ID)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http
    _http = httpx.AsyncClient(timeout=30.0)
    await _init_openfga()
    yield
    await _http.aclose()


app = FastAPI(lifespan=lifespan)


async def _openfga_check(tool_name: str) -> bool:
    try:
        resp = await _http.post(
            f"{OPENFGA_URL}/stores/{_store_id}/check",
            json={
                "tuple_key": {
                    "user": f"agent:{AGENT_ID}",
                    "relation": "can_be_invoked_by",
                    "object": f"tool:{tool_name}",
                }
            },
        )
        return bool(resp.json().get("allowed", False))
    except Exception as exc:
        # Fail closed: if OpenFGA is unreachable, deny the call.
        log.error("openfga: check failed tool=%s err=%s — denying", tool_name, exc)
        return False


def _parse_upstream(resp: httpx.Response) -> tuple[dict | None, int]:
    """Parse upstream response body handling empty and SSE-wrapped JSON."""
    body = resp.content.strip()
    if not body:
        return None, resp.status_code
    ct = resp.headers.get("content-type", "")
    if "event-stream" in ct:
        for line in resp.text.splitlines():
            if line.startswith("data:") and "{" in line:
                return json.loads(line[5:].strip()), resp.status_code
        return None, resp.status_code
    return resp.json(), resp.status_code


@app.post("/mcp")
async def proxy(request: Request) -> Response:
    our_sid = request.headers.get("Mcp-Session-Id", "")
    body = await request.json()
    method = body.get("method", "")

    if method == "tools/call":
        tool_name = body.get("params", {}).get("name", "")
        allowed = await _openfga_check(tool_name)
        log.info(
            '{"event":"authz","agent":"%s","tool":"%s","allowed":%s}',
            AGENT_ID,
            tool_name,
            str(allowed).lower(),
        )
        if not allowed:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {
                        "code": -32603,
                        "message": (
                            f"tool '{tool_name}' denied by OpenFGA policy"
                            f" for agent '{AGENT_ID}'"
                        ),
                    },
                }
            )

    fwd_headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    upstream_sid = _sessions.get(our_sid)
    if upstream_sid:
        fwd_headers["Mcp-Session-Id"] = upstream_sid

    upstream_resp = await _http.post(UPSTREAM_MCP_URL, json=body, headers=fwd_headers)
    new_upstream_sid = upstream_resp.headers.get("Mcp-Session-Id", "")

    resp_headers: dict[str, str] = {}
    if method == "initialize":
        new_our_sid = f"proxy-{uuid.uuid4()}"
        _sessions[new_our_sid] = new_upstream_sid
        resp_headers["Mcp-Session-Id"] = new_our_sid

    payload, status = _parse_upstream(upstream_resp)
    if payload is None:
        return Response(status_code=status, headers=resp_headers)
    return JSONResponse(payload, status_code=status, headers=resp_headers)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "agent_id": AGENT_ID, "store_id": _store_id}
