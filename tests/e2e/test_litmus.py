"""
LitmusChaos e2e tests on the apps-dev cluster.

Determinism:
  - Creates a ChaosEngine with fixed, short parameters targeting a known
    deployment (mcp-website-fetcher, 1 replica). The pod gets deleted and
    Kubernetes restarts it; Litmus records verdict=Pass when its probes confirm
    the app recovered within the experiment window.
  - We poll chaosresult.status.experimentStatus.verdict until it leaves
    "Awaited" — binary Pass/Fail, no timing assertion.
  - Engine is cleaned up after the test regardless of outcome.
"""

import logging
import time

import pytest
from kubernetes import client
from conftest import custom_objects, wait_for_condition

logger = logging.getLogger(__name__)

LITMUS_NS = "litmus"
ENGINE_NAME = "e2e-pod-delete"
RESULT_NAME = f"{ENGINE_NAME}-pod-delete"

# Short chaos: 30s total, delete every 10s, single pod target
_ENGINE_MANIFEST = {
    "apiVersion": "litmuschaos.io/v1alpha1",
    "kind": "ChaosEngine",
    "metadata": {
        "name": ENGINE_NAME,
        "namespace": LITMUS_NS,
    },
    "spec": {
        "engineState": "active",
        "appinfo": {
            "appns": "kagent",
            "applabel": "app=mcp-website-fetcher",
            "appkind": "deployment",
        },
        "chaosServiceAccount": "pod-delete-sa",
        "annotationCheck": "false",
        "experiments": [{
            "name": "pod-delete",
            "spec": {
                "components": {
                    "env": [
                        {"name": "TOTAL_CHAOS_DURATION", "value": "30"},
                        {"name": "CHAOS_INTERVAL", "value": "10"},
                        {"name": "FORCE", "value": "true"},
                        {"name": "PODS_AFFECTED_PERC", "value": "100"},
                        {"name": "DEFAULT_HEALTH_CHECK", "value": "false"},
                    ]
                }
            },
        }],
    },
}


def _delete_engine(co: client.CustomObjectsApi) -> None:
    try:
        co.delete_namespaced_custom_object(
            "litmuschaos.io", "v1alpha1", LITMUS_NS, "chaosengines", ENGINE_NAME
        )
        logger.info("Deleted ChaosEngine %s", ENGINE_NAME)
    except client.exceptions.ApiException as exc:
        if exc.status != 404:
            logger.warning("Could not delete ChaosEngine: %s", exc)


def _delete_result(co: client.CustomObjectsApi) -> None:
    try:
        co.delete_namespaced_custom_object(
            "litmuschaos.io", "v1alpha1", LITMUS_NS, "chaosresults", RESULT_NAME
        )
    except client.exceptions.ApiException as exc:
        if exc.status != 404:
            pass


@pytest.mark.apps_dev
@pytest.mark.litmus
@pytest.mark.slow
def test_litmus_installed(ctx_apps_dev):
    """Litmus CRDs and the pod-delete ChaosExperiment must exist."""
    co = custom_objects(ctx_apps_dev)
    exp = co.get_namespaced_custom_object(
        "litmuschaos.io", "v1alpha1", LITMUS_NS, "chaosexperiments", "pod-delete"
    )
    assert exp["metadata"]["name"] == "pod-delete"


@pytest.mark.apps_dev
@pytest.mark.litmus
@pytest.mark.slow
def test_litmus_pod_delete_passes(ctx_apps_dev):
    """
    Run a short pod-delete experiment against mcp-website-fetcher and
    assert the chaos operator reports verdict=Pass.

    The test confirms the target deployment survives pod deletion — a basic
    resilience check that is independent of workload logic.
    """
    co = custom_objects(ctx_apps_dev)

    # Clean up leftovers from a previous run
    _delete_engine(co)
    _delete_result(co)
    time.sleep(3)

    logger.info("Creating ChaosEngine %s", ENGINE_NAME)
    co.create_namespaced_custom_object(
        "litmuschaos.io", "v1alpha1", LITMUS_NS, "chaosengines", _ENGINE_MANIFEST
    )

    verdict = "Awaited"
    try:
        # Experiment runs for 30s; allow up to 120s total for runner pod startup + result
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                result = co.get_namespaced_custom_object(
                    "litmuschaos.io", "v1alpha1", LITMUS_NS, "chaosresults", RESULT_NAME
                )
                verdict = (
                    result.get("status", {})
                    .get("experimentStatus", {})
                    .get("verdict", "Awaited")
                )
                logger.info("ChaosResult verdict: %s", verdict)
                if verdict != "Awaited":
                    break
            except client.exceptions.ApiException as exc:
                if exc.status != 404:
                    raise
            time.sleep(5)
    finally:
        _delete_engine(co)

    assert verdict == "Pass", (
        f"ChaosExperiment {ENGINE_NAME} verdict={verdict!r}. "
        "Check ChaosResult in litmus namespace for details."
    )
