"""
Flux GitOps health across all clusters.

Determinism: asserts on .status.conditions[Ready].status which is a stable
k8s API contract. Suspended resources are explicitly skipped, not failed.
"""

import pytest
from conftest import wait_for_flux_ready


@pytest.mark.kind
@pytest.mark.flux
def test_flux_healthy_kind(ctx_kind):
    wait_for_flux_ready(ctx_kind, "kind")


@pytest.mark.control_plane
@pytest.mark.flux
def test_flux_healthy_control_plane(ctx_control_plane):
    wait_for_flux_ready(ctx_control_plane, "control-plane")


@pytest.mark.apps_dev
@pytest.mark.flux
def test_flux_healthy_apps_dev(ctx_apps_dev):
    wait_for_flux_ready(ctx_apps_dev, "apps-dev")
