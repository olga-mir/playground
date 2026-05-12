"""
Crossplane provider and composite resource health.

Checks:
  - All providers in Installed+Healthy state on kind and control-plane
  - GKECluster XR for control-plane is Ready (on kind)
  - GKECluster XR for apps-dev is Ready (on control-plane)
  - No Crossplane composites exist on apps-dev (architecture constraint)
"""

import logging
import pytest
from kubernetes import client
from conftest import custom_objects, wait_for_condition, wait_for_cluster_condition

logger = logging.getLogger(__name__)

XRD_GROUP = "platform.tornado-demo.io"
XRD_VERSION = "v1alpha1"
XRD_PLURAL = "gkeclusters"


def _providers_healthy(ctx: str, cluster_label: str) -> None:
    co = custom_objects(ctx)
    providers = co.list_cluster_custom_object("pkg.crossplane.io", "v1", "providers")
    assert providers["items"], f"[{cluster_label}] no Crossplane providers found"
    
    for p in providers["items"]:
        name = p["metadata"]["name"]
        # Wait for both Installed and Healthy conditions
        wait_for_cluster_condition(
            ctx, "pkg.crossplane.io", "v1", "providers", name,
            condition_type="Installed", timeout=60
        )
        wait_for_cluster_condition(
            ctx, "pkg.crossplane.io", "v1", "providers", name,
            condition_type="Healthy", timeout=60
        )


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
    # We expect exactly one XR in this namespace
    wait_for_condition(
        ctx_kind, XRD_GROUP, XRD_VERSION, XRD_PLURAL,
        "control-plane", "control-plane", condition_type="Ready"
    )
    wait_for_condition(
        ctx_kind, XRD_GROUP, XRD_VERSION, XRD_PLURAL,
        "control-plane", "control-plane", condition_type="Synced"
    )


@pytest.mark.control_plane
@pytest.mark.crossplane
def test_gkecluster_apps_dev_ready(ctx_control_plane):
    """apps-dev GKECluster XR must be Synced+Ready on control-plane."""
    wait_for_condition(
        ctx_control_plane, XRD_GROUP, XRD_VERSION, XRD_PLURAL,
        "apps-dev", "apps-dev", condition_type="Ready"
    )
    wait_for_condition(
        ctx_control_plane, XRD_GROUP, XRD_VERSION, XRD_PLURAL,
        "apps-dev", "apps-dev", condition_type="Synced"
    )


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
