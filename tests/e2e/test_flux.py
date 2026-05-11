"""
Flux GitOps health across all clusters.

Determinism: asserts on .status.conditions[Ready].status which is a stable
k8s API contract. Suspended resources are explicitly skipped, not failed.
"""

import pytest
from conftest import all_flux_resources_ready


@pytest.mark.kind
@pytest.mark.flux
def test_flux_healthy_kind(ctx_kind):
    failures = all_flux_resources_ready(ctx_kind, "kind")
    assert not failures, "Flux resources unhealthy on kind:\n" + "\n".join(failures)


@pytest.mark.control_plane
@pytest.mark.flux
def test_flux_healthy_control_plane(ctx_control_plane):
    failures = all_flux_resources_ready(ctx_control_plane, "control-plane")
    assert not failures, "Flux resources unhealthy on control-plane:\n" + "\n".join(failures)


@pytest.mark.apps_dev
@pytest.mark.flux
def test_flux_healthy_apps_dev(ctx_apps_dev):
    failures = all_flux_resources_ready(ctx_apps_dev, "apps-dev")
    assert not failures, "Flux resources unhealthy on apps-dev:\n" + "\n".join(failures)
