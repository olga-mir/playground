"""
Fleet-level health: cluster reachability and node readiness.

All assertions use k8s node conditions — deterministic, no timing dependency.
"""

import pytest
from kubernetes import client
from conftest import core_v1


def _nodes_ready(ctx: str, cluster_label: str) -> None:
    v1 = core_v1(ctx)
    nodes = v1.list_node()
    assert nodes.items, f"[{cluster_label}] no nodes found"
    failures = []
    for node in nodes.items:
        ready = next((c for c in node.status.conditions if c.type == "Ready"), None)
        if not ready or ready.status != "True":
            msg = ready.message if ready else "no Ready condition"
            failures.append(f"{node.metadata.name}: {msg}")
    assert not failures, f"[{cluster_label}] nodes not Ready:\n" + "\n".join(failures)


@pytest.mark.kind
def test_kind_nodes_ready(ctx_kind):
    _nodes_ready(ctx_kind, "kind")


@pytest.mark.control_plane
def test_control_plane_nodes_ready(ctx_control_plane):
    _nodes_ready(ctx_control_plane, "control-plane")


@pytest.mark.apps_dev
def test_apps_dev_nodes_ready(ctx_apps_dev):
    _nodes_ready(ctx_apps_dev, "apps-dev")


@pytest.mark.control_plane
def test_crossplane_not_in_apps_dev(ctx_apps_dev):
    """Architectural constraint: workload cluster must not run Crossplane."""
    v1 = core_v1(ctx_apps_dev)
    namespaces = [ns.metadata.name for ns in v1.list_namespace().items]
    assert "crossplane-system" not in namespaces, \
        "crossplane-system namespace found in apps-dev — violates architecture"


@pytest.mark.kind
def test_kind_has_crossplane(ctx_kind):
    """Bootstrap cluster must have crossplane-system."""
    v1 = core_v1(ctx_kind)
    namespaces = [ns.metadata.name for ns in v1.list_namespace().items]
    assert "crossplane-system" in namespaces, \
        "crossplane-system not found on kind — Crossplane not installed"


@pytest.mark.control_plane
def test_control_plane_has_crossplane(ctx_control_plane):
    """Control-plane must have crossplane-system."""
    v1 = core_v1(ctx_control_plane)
    namespaces = [ns.metadata.name for ns in v1.list_namespace().items]
    assert "crossplane-system" in namespaces, \
        "crossplane-system not found on control-plane — Crossplane not installed"
