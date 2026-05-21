"""
Fleet-level health: cluster reachability and node readiness.

All assertions use k8s node conditions — deterministic, no timing dependency.
"""

import pytest
from kubernetes import client
from conftest import core_v1, wait_for_nodes_ready, wait_for_namespace


@pytest.mark.kind
def test_kind_nodes_ready(ctx_kind):
    wait_for_nodes_ready(ctx_kind)


@pytest.mark.control_plane
def test_control_plane_nodes_ready(ctx_control_plane):
    wait_for_nodes_ready(ctx_control_plane)


@pytest.mark.apps_dev
def test_apps_dev_nodes_ready(ctx_apps_dev):
    wait_for_nodes_ready(ctx_apps_dev)


@pytest.mark.apps_dev
def test_crossplane_not_in_apps_dev(ctx_apps_dev):
    """Architectural constraint: workload cluster must not run Crossplane."""
    v1 = core_v1(ctx_apps_dev)
    namespaces = [ns.metadata.name for ns in v1.list_namespace().items]
    assert "crossplane-system" not in namespaces, \
        "crossplane-system namespace found in apps-dev — violates architecture"


@pytest.mark.kind
def test_kind_has_crossplane(ctx_kind):
    """Bootstrap cluster must have crossplane-system."""
    wait_for_namespace(ctx_kind, "crossplane-system")


@pytest.mark.control_plane
def test_control_plane_has_crossplane(ctx_control_plane):
    """Control-plane must have crossplane-system."""
    wait_for_namespace(ctx_control_plane, "crossplane-system")
