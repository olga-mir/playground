"""
Crossplane provider and composite resource health.

Checks:
  - All providers in Installed+Healthy state on kind and control-plane
  - GKECluster XR for control-plane is Ready (on kind)
  - GKECluster XR for apps-dev is Ready (on control-plane)
  - No Crossplane composites exist on apps-dev (architecture constraint)
"""

import pytest
from kubernetes import client
from conftest import custom_objects


XRD_GROUP = "platform.tornado-demo.io"
XRD_VERSION = "v1alpha1"
XRD_PLURAL = "gkeclusters"


def _providers_healthy(ctx: str, cluster_label: str) -> None:
    co = custom_objects(ctx)
    providers = co.list_cluster_custom_object("pkg.crossplane.io", "v1", "providers")
    assert providers["items"], f"[{cluster_label}] no Crossplane providers found"
    failures = []
    for p in providers["items"]:
        name = p["metadata"]["name"]
        conditions = p.get("status", {}).get("conditions", [])
        installed = next((c for c in conditions if c.get("type") == "Installed"), None)
        healthy = next((c for c in conditions if c.get("type") == "Healthy"), None)
        if not installed or installed.get("status") != "True":
            failures.append(f"{name}: not Installed ({installed})")
        elif not healthy or healthy.get("status") != "True":
            failures.append(f"{name}: not Healthy ({healthy})")
    assert not failures, f"[{cluster_label}] provider issues:\n" + "\n".join(failures)


@pytest.mark.kind
@pytest.mark.crossplane
def test_crossplane_providers_healthy_kind(ctx_kind):
    _providers_healthy(ctx_kind, "kind")


@pytest.mark.control_plane
@pytest.mark.crossplane
def test_crossplane_providers_healthy_control_plane(ctx_control_plane):
    _providers_healthy(ctx_control_plane, "control-plane")


@pytest.mark.kind
@pytest.mark.crossplane
def test_gkecluster_control_plane_ready(ctx_kind):
    """control-plane GKECluster XR must be Synced+Ready on kind."""
    co = custom_objects(ctx_kind)
    clusters = co.list_namespaced_custom_object(
        XRD_GROUP, XRD_VERSION, "control-plane", XRD_PLURAL
    )
    items = clusters.get("items", [])
    assert items, "No GKECluster XR in namespace 'control-plane' on kind"
    failures = []
    for xr in items:
        name = xr["metadata"]["name"]
        conditions = xr.get("status", {}).get("conditions", [])
        ready = next((c for c in conditions if c.get("type") == "Ready"), None)
        synced = next((c for c in conditions if c.get("type") == "Synced"), None)
        if not ready or ready.get("status") != "True":
            failures.append(f"{name}: Ready={ready}")
        if not synced or synced.get("status") != "True":
            failures.append(f"{name}: Synced={synced}")
    assert not failures, "GKECluster XR(s) not ready on kind:\n" + "\n".join(failures)


@pytest.mark.control_plane
@pytest.mark.crossplane
def test_gkecluster_apps_dev_ready(ctx_control_plane):
    """apps-dev GKECluster XR must be Synced+Ready on control-plane."""
    co = custom_objects(ctx_control_plane)
    clusters = co.list_namespaced_custom_object(
        XRD_GROUP, XRD_VERSION, "apps-dev", XRD_PLURAL
    )
    items = clusters.get("items", [])
    assert items, "No GKECluster XR in namespace 'apps-dev' on control-plane"
    failures = []
    for xr in items:
        name = xr["metadata"]["name"]
        conditions = xr.get("status", {}).get("conditions", [])
        ready = next((c for c in conditions if c.get("type") == "Ready"), None)
        synced = next((c for c in conditions if c.get("type") == "Synced"), None)
        if not ready or ready.get("status") != "True":
            failures.append(f"{name}: Ready={ready}")
        if not synced or synced.get("status") != "True":
            failures.append(f"{name}: Synced={synced}")
    assert not failures, "GKECluster XR(s) not ready on control-plane:\n" + "\n".join(failures)


@pytest.mark.apps_dev
@pytest.mark.crossplane
def test_no_composites_on_apps_dev(ctx_apps_dev):
    """Workload cluster must not manage infrastructure composites."""
    co = custom_objects(ctx_apps_dev)
    try:
        xrs = co.list_cluster_custom_object(XRD_GROUP, XRD_VERSION, XRD_PLURAL)
        assert not xrs.get("items"), \
            f"GKECluster XRs found in apps-dev — workload cluster must not manage infra"
    except client.exceptions.ApiException as exc:
        if exc.status == 404:
            pass  # XRD not installed — correct for workload cluster
        else:
            raise
