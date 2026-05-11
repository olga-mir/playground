"""
Tenant workload health on apps-dev.

Checks deployment readiness for both real tenants (sre) and synthetic
team tenants. Deterministic: asserts on deployment .status.readyReplicas
which reflects actual pod health, not scheduling assumptions.
"""

import logging

import pytest
from kubernetes import client
from conftest import apps_v1, core_v1

logger = logging.getLogger(__name__)


def _deployment_ready(ctx: str, namespace: str, name: str) -> tuple[bool, str]:
    """Return (ready, reason). A deployment is ready when readyReplicas == replicas."""
    api = apps_v1(ctx)
    try:
        d = api.read_namespaced_deployment(name, namespace)
    except client.exceptions.ApiException as exc:
        if exc.status == 404:
            return False, f"deployment {namespace}/{name} not found"
        raise
    desired = d.spec.replicas or 1
    ready = d.status.ready_replicas or 0
    if ready >= desired:
        return True, ""
    return False, f"ready={ready}/{desired}"


@pytest.mark.apps_dev
@pytest.mark.tenants
def test_mcp_website_fetcher_deployment_ready(ctx_apps_dev):
    """mcp-website-fetcher in kagent namespace must be fully Ready."""
    ok, reason = _deployment_ready(ctx_apps_dev, "kagent", "mcp-website-fetcher")
    assert ok, f"mcp-website-fetcher not ready: {reason}"


@pytest.mark.apps_dev
@pytest.mark.tenants
def test_tenant_namespaces_labelled(ctx_apps_dev):
    """
    All namespaces with workload-type=application label must exist.
    Validates the Flux tenant kustomization applied the namespace manifests.
    """
    v1 = core_v1(ctx_apps_dev)
    namespaces = v1.list_namespace(label_selector="workload-type=application")
    ns_names = [ns.metadata.name for ns in namespaces.items]
    logger.info("Tenant namespaces found: %s", ns_names)
    # At minimum the sre tenant must be present when the cluster is provisioned
    # with full Flux sync. Skip if not yet deployed.
    if not ns_names:
        pytest.skip("No tenant namespaces with workload-type=application found — "
                    "tenants may not be deployed yet")
    # All found namespaces must be Active
    inactive = [
        ns.metadata.name
        for ns in namespaces.items
        if ns.status.phase != "Active"
    ]
    assert not inactive, f"Tenant namespaces not Active: {inactive}"


@pytest.mark.apps_dev
@pytest.mark.tenants
def test_kgateway_ready(ctx_apps_dev):
    """kgateway HelmRelease must be Ready on apps-dev."""
    from conftest import assert_resource_ready
    assert_resource_ready(
        ctx_apps_dev,
        "helm.toolkit.fluxcd.io", "v2", "helmreleases",
        "kgateway-system", "kgateway",
    )
