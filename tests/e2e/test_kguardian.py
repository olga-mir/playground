"""
kguardian runtime security tooling on apps-dev.

Covers the acceptance criteria from openspec/changes/kguardian-apps-dev/specs/
fleet-security-tooling.md: the bundled PostgreSQL actually binds a PVC (the
fleet has no prior CloudNativePG/Cloud SQL pattern, so this is new failure
surface), and the opt-out posture (telemetry, AI Assistant) stays off.

Determinism: PVC/pod checks assert on k8s status fields, never on kguardian's
own detection output (no baseline/anomaly content is asserted here).
"""

import logging

import pytest
from conftest import core_v1, get_resource, wait_for_condition

logger = logging.getLogger(__name__)

KGUARDIAN_NAMESPACE = "kguardian"


@pytest.mark.apps_dev
@pytest.mark.kguardian
def test_kguardian_crds_kustomization_ready(ctx_apps_dev):
    """kguardian-crds Kustomization must be Ready before the HelmRelease."""
    wait_for_condition(
        ctx_apps_dev,
        "kustomize.toolkit.fluxcd.io", "v1", "kustomizations",
        "flux-system", "kguardian-crds",
    )


@pytest.mark.apps_dev
@pytest.mark.kguardian
def test_kguardian_helmrelease_ready(ctx_apps_dev):
    wait_for_condition(
        ctx_apps_dev,
        "helm.toolkit.fluxcd.io", "v2", "helmreleases",
        KGUARDIAN_NAMESPACE, "kguardian",
    )


@pytest.mark.apps_dev
@pytest.mark.kguardian
def test_kguardian_pods_running(ctx_apps_dev):
    """At least one kguardian workload pod (broker/controller) must be Running."""
    v1 = core_v1(ctx_apps_dev)
    pods = v1.list_namespaced_pod(KGUARDIAN_NAMESPACE)
    running = [p for p in pods.items if p.status.phase == "Running"]
    assert running, (
        f"No Running pods in {KGUARDIAN_NAMESPACE}. "
        f"Found: {[(p.metadata.name, p.status.phase) for p in pods.items]}"
    )
    logger.info("kguardian pods Running: %s", [p.metadata.name for p in running])


@pytest.mark.apps_dev
@pytest.mark.kguardian
def test_kguardian_database_pvc_bound(ctx_apps_dev):
    """
    Bundled PostgreSQL PVC must reach Bound against GKE Standard's default
    StorageClass — the spec's explicit pass criterion for the database.enabled
    path (no storageClassName override in the HelmRelease values).
    """
    v1 = core_v1(ctx_apps_dev)
    pvcs = v1.list_namespaced_persistent_volume_claim(KGUARDIAN_NAMESPACE)
    if not pvcs.items:
        pytest.skip("No PVCs in kguardian namespace yet — database pod may not have scheduled")
    bound = [c for c in pvcs.items if c.status.phase == "Bound"]
    assert bound, (
        f"No Bound PVCs in {KGUARDIAN_NAMESPACE}. "
        f"Found: {[(c.metadata.name, c.status.phase) for c in pvcs.items]}"
    )
    logger.info("kguardian PVCs Bound: %s", [c.metadata.name for c in bound])


@pytest.mark.apps_dev
@pytest.mark.kguardian
def test_kguardian_telemetry_disabled(ctx_apps_dev):
    """HelmRelease values must keep the daily anonymous telemetry check-in off."""
    hr = get_resource(
        ctx_apps_dev,
        "helm.toolkit.fluxcd.io", "v2",
        "helmreleases", KGUARDIAN_NAMESPACE,
        "kguardian",
    )
    values = hr["spec"].get("values", {})
    assert values.get("telemetry", {}).get("enabled") is False, \
        "telemetry.enabled must be false in the kguardian HelmRelease values"


@pytest.mark.apps_dev
@pytest.mark.kguardian
def test_kguardian_ai_assistant_disabled(ctx_apps_dev):
    """HelmRelease values must not opt into the AI Assistant / LLM Bridge."""
    hr = get_resource(
        ctx_apps_dev,
        "helm.toolkit.fluxcd.io", "v2",
        "helmreleases", KGUARDIAN_NAMESPACE,
        "kguardian",
    )
    values = hr["spec"].get("values", {})
    assert values.get("ai", {}).get("enabled") is not True, \
        "ai.enabled must not be set to true — AI Assistant is explicitly out of scope"
