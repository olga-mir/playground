"""OpenFGA authorization check. Fails closed on any error."""

import logging
import os

import httpx

log = logging.getLogger(__name__)

OPENFGA_URL = os.environ["OPENFGA_URL"]
AGENT_ID = os.environ["AGENT_ID"]
_STORE_NAME = "kagent-authz"

_store_id: str | None = None


async def _resolve_store_id() -> str:
    global _store_id
    if _store_id:
        return _store_id
    async with httpx.AsyncClient(timeout=2.0) as client:
        resp = await client.get(f"{OPENFGA_URL}/stores")
        resp.raise_for_status()
        for store in resp.json().get("stores", []):
            if store["name"] == _STORE_NAME:
                _store_id = store["id"]
                return _store_id
    raise RuntimeError(f"OpenFGA store '{_STORE_NAME}' not found")


async def check(namespace: str) -> bool:
    """Return True iff AGENT_ID has can_diagnose on namespace. Fails closed."""
    try:
        store_id = await _resolve_store_id()
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(
                f"{OPENFGA_URL}/stores/{store_id}/check",
                json={
                    "tuple_key": {
                        "user": f"agent:{AGENT_ID}",
                        "relation": "can_diagnose",
                        "object": f"namespace:{namespace}",
                    }
                },
            )
            resp.raise_for_status()
            return resp.json().get("allowed", False)
    except Exception as exc:
        log.error("authz check failed (fail-closed): %s", exc)
        return False
