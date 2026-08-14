"""k8s-troubleshooter MCP server.

Exposes three semantic diagnostic tools, each enforcing namespace-scoped
OpenFGA authorization before touching the Kubernetes API.

Agent identity is fixed at deploy time via AGENT_ID env var — a POC
simplification. Production would use SPIFFE/SVID or a signed JWT injected
per request so identity is verified rather than trusted from config.
"""

import logging

from mcp.server.fastmcp import FastMCP

from src.tools import diagnose_namespace, get_pod_failure_context, get_namespace_resource_pressure

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

mcp = FastMCP("k8s-troubleshooter", host="0.0.0.0", port=8080)


@mcp.tool()
async def diagnose_namespace_tool(namespace: str) -> dict:
    """Aggregate pod status, warning events, resource pressure, and failing containers for a namespace."""
    return await diagnose_namespace.run(namespace)


@mcp.tool()
async def get_pod_failure_context_tool(namespace: str, pod: str) -> dict:
    """Correlate logs (all containers), describe output, and events for a specific pod."""
    return await get_pod_failure_context.run(namespace, pod)


@mcp.tool()
async def get_namespace_resource_pressure_tool(namespace: str) -> dict:
    """Collect ResourceQuota usage, LimitRange defaults, and node pressure for a namespace."""
    return await get_namespace_resource_pressure.run(namespace)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
