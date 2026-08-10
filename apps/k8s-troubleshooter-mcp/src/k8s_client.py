"""Async Kubernetes API wrappers. All exceptions are caught and returned as dicts."""

import logging
from datetime import datetime, timezone

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiException

log = logging.getLogger(__name__)

_initialized = False


async def _ensure_init():
    global _initialized
    if not _initialized:
        await config.load_incluster_config()
        _initialized = True


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


async def list_pods(namespace: str) -> list[dict]:
    try:
        await _ensure_init()
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            result = await v1.list_namespaced_pod(namespace)
            return [
                {
                    "name": p.metadata.name,
                    "phase": p.status.phase,
                    "conditions": [
                        {"type": c.type, "status": c.status, "reason": c.reason}
                        for c in (p.status.conditions or [])
                    ],
                    "containers": [
                        {
                            "name": cs.name,
                            "ready": cs.ready,
                            "restart_count": cs.restart_count,
                            "state": _container_state(cs.state),
                        }
                        for cs in (p.status.container_statuses or [])
                    ],
                }
                for p in result.items
            ]
    except ApiException as exc:
        log.error("list_pods %s: %s %s", namespace, exc.status, exc.reason)
        return [{"error": f"{exc.status} {exc.reason}"}]
    except Exception as exc:
        log.error("list_pods %s: %s", namespace, exc)
        return [{"error": str(exc)}]


def _container_state(state) -> dict:
    if state is None:
        return {}
    if state.running:
        return {"running": True}
    if state.waiting:
        return {"waiting": {"reason": state.waiting.reason, "message": state.waiting.message}}
    if state.terminated:
        return {"terminated": {"reason": state.terminated.reason, "exit_code": state.terminated.exit_code}}
    return {}


async def list_warning_events(namespace: str, last_hours: int = 1) -> list[dict]:
    try:
        await _ensure_init()
        cutoff = _now_utc()
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            result = await v1.list_namespaced_event(
                namespace, field_selector="type=Warning"
            )
            events = []
            for e in result.items:
                t = e.last_timestamp or e.event_time
                if t is None:
                    events.append(_event_dict(e))
                    continue
                if hasattr(t, "replace"):
                    t = t.replace(tzinfo=timezone.utc)
                age_hours = (cutoff - t).total_seconds() / 3600
                if age_hours <= last_hours:
                    events.append(_event_dict(e))
            return events
    except ApiException as exc:
        log.error("list_warning_events %s: %s %s", namespace, exc.status, exc.reason)
        return [{"error": f"{exc.status} {exc.reason}"}]
    except Exception as exc:
        log.error("list_warning_events %s: %s", namespace, exc)
        return [{"error": str(exc)}]


def _event_dict(e) -> dict:
    return {
        "name": e.metadata.name,
        "reason": e.reason,
        "message": e.message,
        "involved_object": f"{e.involved_object.kind}/{e.involved_object.name}",
        "count": e.count,
        "last_timestamp": str(e.last_timestamp or e.event_time),
    }


async def list_resource_quotas(namespace: str) -> list[dict]:
    try:
        await _ensure_init()
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            result = await v1.list_namespaced_resource_quota(namespace)
            return [
                {
                    "name": rq.metadata.name,
                    "hard": dict(rq.status.hard or {}),
                    "used": dict(rq.status.used or {}),
                }
                for rq in result.items
            ]
    except ApiException as exc:
        log.error("list_resource_quotas %s: %s %s", namespace, exc.status, exc.reason)
        return [{"error": f"{exc.status} {exc.reason}"}]
    except Exception as exc:
        log.error("list_resource_quotas %s: %s", namespace, exc)
        return [{"error": str(exc)}]


async def list_limit_ranges(namespace: str) -> list[dict]:
    try:
        await _ensure_init()
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            result = await v1.list_namespaced_limit_range(namespace)
            return [
                {
                    "name": lr.metadata.name,
                    "limits": [
                        {
                            "type": lri.type,
                            "default": dict(lri.default or {}),
                            "default_request": dict(lri.default_request or {}),
                            "max": dict(lri.max or {}),
                        }
                        for lri in (lr.spec.limits or [])
                    ],
                }
                for lr in result.items
            ]
    except ApiException as exc:
        log.error("list_limit_ranges %s: %s %s", namespace, exc.status, exc.reason)
        return [{"error": f"{exc.status} {exc.reason}"}]
    except Exception as exc:
        log.error("list_limit_ranges %s: %s", namespace, exc)
        return [{"error": str(exc)}]


async def list_node_pressure(namespace: str) -> list[dict]:
    """Return pressure conditions for nodes running pods in namespace."""
    try:
        await _ensure_init()
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            pods = await v1.list_namespaced_pod(namespace)
            node_names = {p.spec.node_name for p in pods.items if p.spec.node_name}
            if not node_names:
                return []
            nodes = await v1.list_node()
            result = []
            for node in nodes.items:
                if node.metadata.name not in node_names:
                    continue
                pressures = [
                    {"type": c.type, "status": c.status}
                    for c in (node.status.conditions or [])
                    if c.type in ("DiskPressure", "MemoryPressure", "PIDPressure")
                ]
                result.append({"node": node.metadata.name, "pressure": pressures})
            return result
    except ApiException as exc:
        log.error("list_node_pressure %s: %s %s", namespace, exc.status, exc.reason)
        return [{"error": f"{exc.status} {exc.reason}"}]
    except Exception as exc:
        log.error("list_node_pressure %s: %s", namespace, exc)
        return [{"error": str(exc)}]


async def get_pod_logs(namespace: str, pod: str, container: str | None = None, tail: int = 100) -> str:
    try:
        await _ensure_init()
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            kwargs = {"tail_lines": tail}
            if container:
                kwargs["container"] = container
            return await v1.read_namespaced_pod_log(pod, namespace, **kwargs)
    except ApiException as exc:
        return f"ERROR {exc.status} {exc.reason}"
    except Exception as exc:
        return f"ERROR {exc}"


async def describe_pod(namespace: str, pod: str) -> dict:
    try:
        await _ensure_init()
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            p = await v1.read_namespaced_pod(pod, namespace)
            return {
                "name": p.metadata.name,
                "namespace": p.metadata.namespace,
                "node": p.spec.node_name,
                "phase": p.status.phase,
                "conditions": [
                    {"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
                    for c in (p.status.conditions or [])
                ],
                "container_statuses": [
                    {
                        "name": cs.name,
                        "ready": cs.ready,
                        "restart_count": cs.restart_count,
                        "state": _container_state(cs.state),
                        "last_state": _container_state(cs.last_state),
                    }
                    for cs in (p.status.container_statuses or [])
                ],
                "init_container_statuses": [
                    {
                        "name": cs.name,
                        "ready": cs.ready,
                        "restart_count": cs.restart_count,
                        "state": _container_state(cs.state),
                    }
                    for cs in (p.status.init_container_statuses or [])
                ],
            }
    except ApiException as exc:
        return {"error": f"{exc.status} {exc.reason}"}
    except Exception as exc:
        return {"error": str(exc)}


async def list_pod_events(namespace: str, pod: str) -> list[dict]:
    try:
        await _ensure_init()
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            result = await v1.list_namespaced_event(
                namespace,
                field_selector=f"involvedObject.name={pod},involvedObject.kind=Pod",
            )
            return [_event_dict(e) for e in result.items]
    except ApiException as exc:
        log.error("list_pod_events %s/%s: %s %s", namespace, pod, exc.status, exc.reason)
        return [{"error": f"{exc.status} {exc.reason}"}]
    except Exception as exc:
        log.error("list_pod_events %s/%s: %s", namespace, pod, exc)
        return [{"error": str(exc)}]


async def list_pod_containers(namespace: str, pod: str) -> list[str]:
    try:
        await _ensure_init()
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            p = await v1.read_namespaced_pod(pod, namespace)
            return [c.name for c in (p.spec.containers or [])]
    except Exception:
        return []
