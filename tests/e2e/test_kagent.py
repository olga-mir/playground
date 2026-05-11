"""
kagent functional tests on the apps-dev cluster.

Determinism:
  - HelmRelease and pod checks assert on k8s conditions/phases, not timing.
  - API test asserts on HTTP status + JSON schema (list structure), NEVER on
    LLM response content — the same request always returns the same schema.
"""

import logging
import time

import pytest
import requests
from kubernetes import client
from conftest import (
    custom_objects,
    core_v1,
    apps_v1,
    wait_for_condition,
    port_forward,
)

logger = logging.getLogger(__name__)

KAGENT_NAMESPACE = "kagent-system"
KAGENT_SERVICE = "kagent"
KAGENT_API_PORT = 8083


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_kagent_crds_helmrelease_ready(ctx_apps_dev):
    """kagent-crds HelmRelease must be Ready before kagent itself."""
    wait_for_condition(
        ctx_apps_dev,
        "helm.toolkit.fluxcd.io", "v2", "helmreleases",
        KAGENT_NAMESPACE, "kagent-crds",
        timeout=300,
    )


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_kagent_helmrelease_ready(ctx_apps_dev):
    wait_for_condition(
        ctx_apps_dev,
        "helm.toolkit.fluxcd.io", "v2", "helmreleases",
        KAGENT_NAMESPACE, "kagent",
        timeout=300,
    )


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_kagent_pods_running(ctx_apps_dev):
    """At least one kagent controller pod must be Running."""
    v1 = core_v1(ctx_apps_dev)
    pods = v1.list_namespaced_pod(
        KAGENT_NAMESPACE,
        label_selector="app.kubernetes.io/name=kagent",
    )
    running = [p for p in pods.items if p.status.phase == "Running"]
    assert running, (
        f"No Running kagent pods in {KAGENT_NAMESPACE}. "
        f"Found: {[(p.metadata.name, p.status.phase) for p in pods.items]}"
    )


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_kagent_model_config_exists(ctx_apps_dev):
    """ModelConfig for Claude must exist in kagent-system."""
    co = custom_objects(ctx_apps_dev)
    obj = co.get_namespaced_custom_object(
        "kagent.dev", "v1alpha2",
        KAGENT_NAMESPACE, "modelconfigs",
        "claude-model-config",
    )
    assert obj["spec"]["provider"] == "Anthropic"
    assert obj["spec"]["apiKeySecret"] == "kagent-anthropic"


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_mcp_website_fetcher_pod_running(ctx_apps_dev):
    """Tutorial MCP tool server must be Running."""
    v1 = core_v1(ctx_apps_dev)
    pods = v1.list_namespaced_pod(
        "kagent",
        label_selector="app=mcp-website-fetcher",
    )
    running = [p for p in pods.items if p.status.phase == "Running"]
    assert running, "mcp-website-fetcher pod not Running in kagent namespace"


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_mcp_toolserver_resource_exists(ctx_apps_dev):
    """ToolServer CRD object for mcp-toolserver must exist."""
    co = custom_objects(ctx_apps_dev)
    obj = co.get_namespaced_custom_object(
        "kagent.dev", "v1alpha1",
        "kagent", "toolservers",
        "mcp-toolserver",
    )
    assert obj["spec"]["config"]["sse"]["url"], "ToolServer has no SSE URL"


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_kagent_api_agents_endpoint(ctx_apps_dev):
    """
    kagent REST API must respond with a valid list at GET /api/v1/agents.

    Determinism: we assert HTTP 200 + JSON list schema.
    We do NOT assert on list contents — agents can be added/removed.
    """
    with port_forward(ctx_apps_dev, KAGENT_NAMESPACE, f"svc/{KAGENT_SERVICE}", KAGENT_API_PORT) as base_url:
        resp = requests.get(f"{base_url}/api/v1/agents", timeout=15)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert isinstance(body, list), f"Expected JSON list, got {type(body)}: {str(body)[:200]}"
    logger.info("kagent /api/v1/agents returned %d agent(s)", len(body))
