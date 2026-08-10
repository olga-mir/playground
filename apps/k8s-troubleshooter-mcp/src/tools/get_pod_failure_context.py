import asyncio

from src import authz, k8s_client


async def run(namespace: str, pod: str) -> dict:
    if not await authz.check(namespace):
        return {"error": "403 Forbidden", "detail": f"agent not authorized to diagnose namespace '{namespace}'"}

    containers = await k8s_client.list_pod_containers(namespace, pod)

    describe, events, *log_results = await asyncio.gather(
        k8s_client.describe_pod(namespace, pod),
        k8s_client.list_pod_events(namespace, pod),
        *[k8s_client.get_pod_logs(namespace, pod, container=c, tail=100) for c in containers],
    )

    logs = {containers[i]: log_results[i] for i in range(len(containers))} if containers else {}

    return {
        "namespace": namespace,
        "pod": pod,
        "describe": describe,
        "events": events,
        "logs": logs,
    }
