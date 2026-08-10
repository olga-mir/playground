import asyncio

from src import authz, k8s_client

_FAILING_STATES = {"CrashLoopBackOff", "OOMKilled", "Error", "ImagePullBackOff", "ErrImagePull"}


async def run(namespace: str) -> dict:
    if not await authz.check(namespace):
        return {"error": "403 Forbidden", "detail": f"agent not authorized to diagnose namespace '{namespace}'"}

    pods, events, quotas, pressure = await asyncio.gather(
        k8s_client.list_pods(namespace),
        k8s_client.list_warning_events(namespace, last_hours=1),
        k8s_client.list_resource_quotas(namespace),
        k8s_client.list_node_pressure(namespace),
    )

    failing = [
        {"pod": p["name"], "container": c["name"], "state": c["state"]}
        for p in pods
        if "error" not in p
        for c in p.get("containers", [])
        if _is_failing(c)
    ]

    return {
        "namespace": namespace,
        "pod_summary": {
            "total": len([p for p in pods if "error" not in p]),
            "running": len([p for p in pods if p.get("phase") == "Running"]),
            "failing_containers": failing,
        },
        "recent_warning_events": events,
        "resource_quotas": quotas,
        "node_pressure": pressure,
    }


def _is_failing(container_status: dict) -> bool:
    state = container_status.get("state", {})
    waiting = state.get("waiting", {})
    terminated = state.get("terminated", {})
    return waiting.get("reason") in _FAILING_STATES or terminated.get("reason") in _FAILING_STATES
