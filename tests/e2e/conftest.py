"""
Shared fixtures and helpers for e2e tests.

Determinism contract:
  - All resource assertions use wait_for_condition() — polling until a k8s
    condition becomes True, never asserting on timing or LLM output content.
  - Tests skip (not fail) when a cluster context is absent, so a partial fleet
    doesn't break unrelated suites.
"""

import logging
import subprocess
import time
import contextlib
import socket

import pytest
from kubernetes import client, config as k8s_config

logger = logging.getLogger(__name__)

# ── context discovery ─────────────────────────────────────────────────────────

def _all_contexts() -> list[str]:
    result = subprocess.run(
        ["kubectl", "config", "get-contexts", "-o", "name"],
        capture_output=True, text=True,
    )
    return result.stdout.strip().splitlines() if result.returncode == 0 else []


def _find_context(suffix: str) -> str | None:
    """Return the first kubeconfig context ending with _{suffix}."""
    for ctx in _all_contexts():
        if ctx.endswith(f"_{suffix}"):
            return ctx
    return None


def _fetch_credentials(cluster_name: str) -> bool:
    """Try to fetch credentials for a GKE cluster using gcloud."""
    if subprocess.run(["which", "gcloud"], capture_output=True).returncode != 0:
        return False

    logger.info(f"Context for {cluster_name} not found. Attempting to fetch...")
    try:
        cmd = [
            "gcloud", "container", "clusters", "list",
            "--filter", f"name~{cluster_name}",
            "--format", "value(name,zone,project)"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    name, zone, project = parts[0], parts[1], parts[2]
                    if name == cluster_name or name.endswith(f"-{cluster_name}"):
                        logger.info(f"Found cluster {name} in {zone} ({project}). Fetching credentials...")
                        subprocess.run([
                            "gcloud", "container", "clusters", "get-credentials",
                            name, "--zone", zone, "--project", project
                        ], check=True)
                        return True
    except Exception as e:
        logger.error(f"Failed to fetch credentials for {cluster_name}: {e}")
    return False


def _ensure_context(name: str) -> str | None:
    ctx = _find_context(name)
    if ctx and _context_reachable(ctx):
        return ctx

    if _fetch_credentials(name):
        ctx = _find_context(name)
        if ctx and _context_reachable(ctx):
            return ctx

    return None


def _context_reachable(ctx: str) -> bool:
    """Return True if the API server responds within a short timeout."""
    result = subprocess.run(
        ["kubectl", "--context", ctx, "cluster-info", "--request-timeout=5s"],
        capture_output=True,
    )
    return result.returncode == 0


# ── session-scoped context fixtures ──────────────────────────────────────────

@pytest.fixture(scope="session")
def ctx_kind() -> str:
    ctx = "kind-kind-test-cluster"
    if ctx not in _all_contexts() or not _context_reachable(ctx):
        pytest.skip(f"kind cluster not available ({ctx})")
    return ctx


@pytest.fixture(scope="session")
def ctx_control_plane() -> str:
    ctx = _ensure_context("control-plane")
    if not ctx:
        pytest.skip("control-plane cluster not available")
    return ctx


@pytest.fixture(scope="session")
def ctx_apps_dev() -> str:
    ctx = _ensure_context("apps-dev")
    if not ctx:
        pytest.skip("apps-dev cluster not available")
    return ctx


# ── k8s client helpers ────────────────────────────────────────────────────────

def k8s_api(ctx: str) -> client.ApiClient:
    return k8s_config.new_client_from_config(context=ctx)


def core_v1(ctx: str) -> client.CoreV1Api:
    return client.CoreV1Api(api_client=k8s_api(ctx))


def custom_objects(ctx: str) -> client.CustomObjectsApi:
    return client.CustomObjectsApi(api_client=k8s_api(ctx))


def apps_v1(ctx: str) -> client.AppsV1Api:
    return client.AppsV1Api(api_client=k8s_api(ctx))


# ── resource helpers ──────────────────────────────────────────────────────────

def get_resource(
    ctx: str,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    name: str,
) -> dict:
    """Get a custom resource or fail with a clear message on 404."""
    co = custom_objects(ctx)
    try:
        return co.get_namespaced_custom_object(group, version, namespace, plural, name)
    except client.exceptions.ApiException as exc:
        if exc.status == 404:
            pytest.fail(f"{plural}/{namespace}/{name} not found")
        raise


def assert_resource_ready(
    ctx: str,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    name: str,
    condition_type: str = "Ready",
) -> dict:
    """Read a custom resource once and assert condition_type == True."""
    obj = get_resource(ctx, group, version, namespace, plural, name)
    conditions = obj.get("status", {}).get("conditions", [])
    for cond in conditions:
        if cond.get("type") == condition_type:
            assert cond.get("status") == "True", \
                f"{plural}/{namespace}/{name} is {condition_type}={cond.get('status')} - {cond.get('message', '')}"
            return obj
    pytest.fail(f"{plural}/{namespace}/{name} has no {condition_type} condition")


# ── condition polling ─────────────────────────────────────────────────────────

def wait_for_condition(
    ctx: str,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    name: str,
    condition_type: str = "Ready",
    timeout: int = 180,
) -> dict:
    """
    Poll a namespaced custom resource until condition_type == True.

    Determinism: asserts on k8s condition status, not wall-clock time.
    Raises TimeoutError (caught by pytest as failure) if timeout expires.
    """
    co = custom_objects(ctx)
    deadline = time.monotonic() + timeout
    last_msg = ""
    while time.monotonic() < deadline:
        try:
            obj = co.get_namespaced_custom_object(group, version, namespace, plural, name)
            conditions = obj.get("status", {}).get("conditions", [])
            for cond in conditions:
                if cond.get("type") == condition_type:
                    if cond.get("status") == "True":
                        return obj
                    last_msg = cond.get("message", "")
        except client.exceptions.ApiException as exc:
            if exc.status != 404:
                raise
        time.sleep(5)
    raise TimeoutError(
        f"{plural}/{namespace}/{name} did not reach {condition_type}=True "
        f"within {timeout}s. Last message: {last_msg}"
    )


def wait_for_cluster_condition(
    ctx: str,
    group: str,
    version: str,
    plural: str,
    name: str,
    condition_type: str = "Ready",
    timeout: int = 180,
) -> dict:
    """Same as wait_for_condition but for cluster-scoped resources."""
    co = custom_objects(ctx)
    deadline = time.monotonic() + timeout
    last_msg = ""
    while time.monotonic() < deadline:
        try:
            obj = co.get_cluster_custom_object(group, version, plural, name)
            conditions = obj.get("status", {}).get("conditions", [])
            for cond in conditions:
                if cond.get("type") == condition_type:
                    if cond.get("status") == "True":
                        return obj
                    last_msg = cond.get("message", "")
        except client.exceptions.ApiException as exc:
            if exc.status != 404:
                raise
        time.sleep(5)
    raise TimeoutError(
        f"{plural}/{name} did not reach {condition_type}=True "
        f"within {timeout}s. Last message: {last_msg}"
    )


def all_flux_resources_ready(ctx: str, cluster_label: str) -> list[str]:
    """
    Check all Flux resource types across all namespaces.
    Returns list of failure messages; empty list means all healthy.
    """
    flux_types = [
        ("kustomize.toolkit.fluxcd.io", "v1", "kustomizations"),
        ("source.toolkit.fluxcd.io", "v1", "gitrepositories"),
        ("helm.toolkit.fluxcd.io", "v2", "helmreleases"),
        ("source.toolkit.fluxcd.io", "v1", "helmrepositories"),
        ("image.toolkit.fluxcd.io", "v1beta2", "imagerepositories"),
        ("image.toolkit.fluxcd.io", "v1beta2", "imagepolicies"),
        ("image.toolkit.fluxcd.io", "v1beta2", "imageupdateautomations"),
    ]
    co = custom_objects(ctx)
    failures = []
    for group, version, plural in flux_types:
        try:
            resources = co.list_cluster_custom_object(group, version, plural)
        except client.exceptions.ApiException as exc:
            if exc.status == 404:
                continue  # CRD not installed on this cluster — expected for some types
            raise
        for item in resources.get("items", []):
            meta = item["metadata"]
            suspended = item.get("spec", {}).get("suspend", False)
            if suspended:
                logger.info("[%s] %s/%s/%s SUSPENDED — skipping", cluster_label, plural, meta["namespace"], meta["name"])
                continue
            conditions = item.get("status", {}).get("conditions", [])
            ready = next((c for c in conditions if c.get("type") == "Ready"), None)
            if not ready:
                failures.append(f"[{cluster_label}] {plural}/{meta['namespace']}/{meta['name']}: no Ready condition")
            elif ready["status"] != "True":
                failures.append(
                    f"[{cluster_label}] {plural}/{meta['namespace']}/{meta['name']}: "
                    f"Ready={ready['status']} — {ready.get('message', '')}"
                )
    return failures


# ── port-forward context manager ──────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def port_forward(ctx: str, namespace: str, resource: str, remote_port: int):
    """
    Context manager that port-forwards to a service and yields the base URL.
    resource can be 'svc/name' or 'pod/name'.
    """
    local_port = _free_port()
    proc = subprocess.Popen(
        ["kubectl", f"--context={ctx}", "port-forward", resource,
         f"{local_port}:{remote_port}", "-n", namespace],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait until the port is actually listening
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", local_port), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    try:
        yield f"http://localhost:{local_port}"
    finally:
        proc.terminate()
        proc.wait()
