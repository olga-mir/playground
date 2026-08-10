import asyncio

from src import authz, k8s_client


async def run(namespace: str) -> dict:
    if not await authz.check(namespace):
        return {"error": "403 Forbidden", "detail": f"agent not authorized to diagnose namespace '{namespace}'"}

    quotas, limit_ranges, node_pressure = await asyncio.gather(
        k8s_client.list_resource_quotas(namespace),
        k8s_client.list_limit_ranges(namespace),
        k8s_client.list_node_pressure(namespace),
    )

    return {
        "namespace": namespace,
        "resource_quotas": quotas,
        "limit_ranges": limit_ranges,
        "node_pressure": node_pressure,
    }
