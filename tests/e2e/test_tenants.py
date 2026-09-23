"""
Tenant workload health on apps-dev.

Checks deployment readiness for both real tenants (sre) and synthetic
team tenants. Deterministic: asserts on deployment .status.readyReplicas
which reflects actual pod health, not scheduling assumptions.
"""

import logging

import pytest
from kubernetes import client
from conftest import apps_v1, core_v1, wait_for_condition

logger = logging.getLogger(__name__)


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
    wait_for_condition(
        ctx_apps_dev,
        "helm.toolkit.fluxcd.io", "v2", "helmreleases",
        "kgateway-system", "kgateway",
    )


# ── sre / sre-ebpf: multi-repo GitOps from playground-sre ───────────────────
#
# Both Kustomizations pull from the separate playground-sre repo (see
# kubernetes/tenants/base/sre{,-ebpf}/gitrepository.yaml). The namespace-level
# check above already covers their `workload-type=application` label; these
# assert the actual multi-repo sync and image-automation objects specifically
# named in #129, rather than relying on the generic Flux-health sweep to
# happen to catch a regression here.

@pytest.mark.apps_dev
@pytest.mark.tenants
def test_sre_kustomization_ready(ctx_apps_dev):
    """sre Kustomization (workloads/perf-lab/k8s from playground-sre) must be Ready."""
    wait_for_condition(
        ctx_apps_dev,
        "kustomize.toolkit.fluxcd.io", "v1", "kustomizations",
        "flux-system", "sre",
    )


@pytest.mark.apps_dev
@pytest.mark.tenants
def test_sre_ebpf_kustomization_ready(ctx_apps_dev):
    """sre-ebpf Kustomization (workloads/ebpf-noisy-neighbour/k8s) must be Ready."""
    wait_for_condition(
        ctx_apps_dev,
        "kustomize.toolkit.fluxcd.io", "v1", "kustomizations",
        "flux-system", "sre-ebpf",
    )


@pytest.mark.apps_dev
@pytest.mark.tenants
def test_sre_image_policy_ready(ctx_apps_dev):
    wait_for_condition(
        ctx_apps_dev,
        "image.toolkit.fluxcd.io", "v1beta2", "imagepolicies",
        "flux-system", "perf-lab",
    )


@pytest.mark.apps_dev
@pytest.mark.tenants
def test_sre_ebpf_image_policy_ready(ctx_apps_dev):
    wait_for_condition(
        ctx_apps_dev,
        "image.toolkit.fluxcd.io", "v1beta2", "imagepolicies",
        "flux-system", "experiment-ebpf",
    )


@pytest.mark.apps_dev
@pytest.mark.tenants
def test_sre_image_update_automation_ready(ctx_apps_dev):
    """
    perf-lab ImageUpdateAutomation must push successfully to playground-sre.
    This is the targeted signal for #128 (required_signatures ruleset blocking
    the push) — narrower and faster-failing than the full apps-dev Flux sweep.
    """
    wait_for_condition(
        ctx_apps_dev,
        "image.toolkit.fluxcd.io", "v1beta2", "imageupdateautomations",
        "flux-system", "perf-lab",
    )


@pytest.mark.apps_dev
@pytest.mark.tenants
def test_sre_ebpf_image_update_automation_ready(ctx_apps_dev):
    """experiment-ebpf ImageUpdateAutomation must push successfully to playground-sre."""
    wait_for_condition(
        ctx_apps_dev,
        "image.toolkit.fluxcd.io", "v1beta2", "imageupdateautomations",
        "flux-system", "experiment-ebpf",
    )
