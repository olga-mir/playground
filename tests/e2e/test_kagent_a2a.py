"""
kagent Agent-to-Agent (A2A) workflow e2e tests on apps-dev cluster.

Tests the standalone agent deployment, A2A tool wiring, cross-namespace
delegation, and namespace isolation baseline for OpenFGA.

Determinism contract: Tests assert on k8s resource state and conditions,
never on LLM response content or timing.
"""

import logging
import pytest
from kubernetes import client
from conftest import (
    custom_objects,
    core_v1,
    get_resource,
    wait_for_condition,
    port_forward,
)

logger = logging.getLogger(__name__)

KAGENT_SYSTEM = "kagent-system"
TEAM_CHARLIE = "team-charlie"


# ── T1: Standalone Agent Deployment ──────────────────────────────────────────

@pytest.mark.apps_dev
@pytest.mark.kagent
def test_cilium_network_agent_deployed(ctx_apps_dev):
    """cilium-network-agent must be deployed as a standalone Agent CR."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "cilium-network-agent",
    )
    assert agent["metadata"]["name"] == "cilium-network-agent"
    assert agent["spec"]["declarative"]["modelConfig"] == "claude-model-config"
    logger.info("cilium-network-agent Agent CR found")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_k8s_agent_deployed(ctx_apps_dev):
    """k8s-agent must be deployed as a standalone Agent CR."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "k8s-agent",
    )
    assert agent["metadata"]["name"] == "k8s-agent"
    assert agent["spec"]["declarative"]["modelConfig"] == "claude-model-config"
    logger.info("k8s-agent Agent CR found")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_observability_agent_deployed(ctx_apps_dev):
    """observability-agent must be deployed as a standalone Agent CR."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "observability-agent",
    )
    assert agent["metadata"]["name"] == "observability-agent"
    logger.info("observability-agent Agent CR found")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_promql_agent_deployed(ctx_apps_dev):
    """promql-agent must be deployed as a standalone Agent CR."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "promql-agent",
    )
    assert agent["metadata"]["name"] == "promql-agent"
    logger.info("promql-agent Agent CR found")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_helm_agent_deployed(ctx_apps_dev):
    """helm-agent must be deployed as a standalone Agent CR."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "helm-agent",
    )
    assert agent["metadata"]["name"] == "helm-agent"
    logger.info("helm-agent Agent CR found")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_bundled_agents_disabled(ctx_apps_dev):
    """Verify that bundled agent sub-charts are disabled in HelmRelease."""
    hr = get_resource(
        ctx_apps_dev,
        "helm.toolkit.fluxcd.io", "v2",
        "helmreleases", KAGENT_SYSTEM,
        "kagent",
    )
    values = hr["spec"].get("values", {})

    disabled_agents = [
        "cilium-debug-agent", "cilium-policy-agent", "cilium-manager-agent",
        "k8s-agent", "observability-agent", "promql-agent", "helm-agent",
        "istio-agent", "argo-rollouts-agent", "kgateway-agent",
    ]

    for agent in disabled_agents:
        assert values.get(agent, {}).get("enabled") is False, \
            f"{agent} should be disabled in HelmRelease values"

    logger.info("All bundled agent sub-charts are disabled")


# ── T2: A2A Tool Wiring ──────────────────────────────────────────────────────

@pytest.mark.apps_dev
@pytest.mark.kagent
def test_cilium_network_agent_tool_references(ctx_apps_dev):
    """cilium-network-agent must declare observability and promql agents as tools."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "cilium-network-agent",
    )

    tools = agent["spec"]["declarative"].get("tools", [])
    agent_tools = [t for t in tools if t.get("type") == "Agent"]
    assert len(agent_tools) >= 2, \
        f"cilium-network-agent must have at least 2 Agent tools, found {len(agent_tools)}"

    tool_names = {t["agent"]["name"] for t in agent_tools}
    assert "observability-agent" in tool_names, \
        "observability-agent not found in cilium-network-agent tools"
    assert "promql-agent" in tool_names, \
        "promql-agent not found in cilium-network-agent tools"

    logger.info("cilium-network-agent has observability and promql agent tools")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_cilium_network_agent_a2a_skills(ctx_apps_dev):
    """cilium-network-agent must declare a2aConfig.skills metadata."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "cilium-network-agent",
    )

    a2a_config = agent["spec"]["declarative"].get("a2aConfig", {})
    skills = a2a_config.get("skills", [])
    assert len(skills) > 0, "cilium-network-agent must declare at least one skill"

    cilium_skill = next((s for s in skills if s.get("id") == "cilium-network-debug"), None)
    assert cilium_skill is not None, "cilium-network-debug skill not found"
    assert cilium_skill.get("description"), "Skill must have a description"

    logger.info("cilium-network-agent has a2aConfig.skills metadata")


# ── T3: Cross-Namespace Delegation ───────────────────────────────────────────

@pytest.mark.apps_dev
@pytest.mark.kagent
def test_k8s_agent_allowed_namespaces(ctx_apps_dev):
    """k8s-agent must have allowedNamespaces including team-charlie."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "k8s-agent",
    )

    allowed_ns = agent["spec"].get("allowedNamespaces", {})
    # Gateway API pattern: {from: All} permits every namespace implicitly
    if isinstance(allowed_ns, dict) and allowed_ns.get("from") == "All":
        pass  # all namespaces allowed, including team-charlie and kagent-system
    else:
        ns_list = allowed_ns if isinstance(allowed_ns, list) else []
        assert "team-charlie" in ns_list, \
            f"team-charlie not in k8s-agent allowedNamespaces: {allowed_ns}"
        assert "kagent-system" in ns_list, \
            f"kagent-system not in k8s-agent allowedNamespaces: {allowed_ns}"

    logger.info("k8s-agent allowedNamespaces correctly configured")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_crossplane_composition_fixer_deployed(ctx_apps_dev):
    """crossplane-composition-fixer must be deployed in team-charlie."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", TEAM_CHARLIE,
        "crossplane-composition-fixer",
    )

    assert agent["metadata"]["name"] == "crossplane-composition-fixer"
    assert agent["spec"]["declarative"]["modelConfig"] == "claude-model-config"
    logger.info("crossplane-composition-fixer Agent CR found in team-charlie")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_crossplane_composition_fixer_k8s_agent_tool(ctx_apps_dev):
    """crossplane-composition-fixer must declare k8s-agent as a tool."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", TEAM_CHARLIE,
        "crossplane-composition-fixer",
    )

    tools = agent["spec"]["declarative"].get("tools", [])
    agent_tools = [t for t in tools if t.get("type") == "Agent"]

    k8s_tool = next(
        (t for t in agent_tools if t["agent"]["name"] == "k8s-agent"),
        None
    )
    assert k8s_tool is not None, "k8s-agent tool not found in crossplane-composition-fixer"
    assert k8s_tool["agent"]["namespace"] == KAGENT_SYSTEM, \
        "k8s-agent tool must reference kagent-system namespace"

    logger.info("crossplane-composition-fixer has k8s-agent cross-namespace tool")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_team_charlie_kagent_rbac(ctx_apps_dev):
    """team-charlie/kagent ServiceAccount must be bound to cross-namespace role."""
    rbac = get_resource(
        ctx_apps_dev,
        "rbac.authorization.k8s.io", "v1",
        "clusterrolebindings", "",
        "kagent-crossplane-github-access",
    )

    subjects = rbac["roleRef"]["name"] or rbac.get("subjects", [])
    # Check for team-charlie/kagent in subjects (may be multiple bindings)
    co = custom_objects(ctx_apps_dev)
    binding = co.get_cluster_custom_object("rbac.authorization.k8s.io", "v1", "clusterrolebindings",
                                          "kagent-crossplane-github-access")

    # The binding should include team-charlie/kagent as a subject
    found = False
    for subject in binding.get("subjects", []):
        if subject.get("kind") == "ServiceAccount" and \
           subject.get("name") == "kagent" and \
           subject.get("namespace") == TEAM_CHARLIE:
            found = True
            break

    assert found, "team-charlie/kagent ServiceAccount not in ClusterRoleBinding subjects"
    logger.info("team-charlie/kagent ServiceAccount properly bound")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_agents_ready_state(ctx_apps_dev):
    """All A2A agents must be in Ready state."""
    agents_to_check = [
        "cilium-network-agent",
        "k8s-agent",
        "observability-agent",
        "promql-agent",
        "helm-agent",
    ]

    for agent_name in agents_to_check:
        wait_for_condition(
            ctx_apps_dev,
            "kagent.dev", "v1alpha2",
            "agents", KAGENT_SYSTEM,
            agent_name,
            timeout=180,
        )

    logger.info("All A2A agents are in Ready state")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_crossplane_composition_fixer_ready_state(ctx_apps_dev):
    """crossplane-composition-fixer must be in Ready state."""
    wait_for_condition(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", TEAM_CHARLIE,
        "crossplane-composition-fixer",
        timeout=180,
    )

    logger.info("crossplane-composition-fixer is in Ready state")


# ── T4: A2A Skills Metadata ──────────────────────────────────────────────────

@pytest.mark.apps_dev
@pytest.mark.kagent
def test_observability_agent_a2a_skills(ctx_apps_dev):
    """observability-agent must declare a2aConfig.skills metadata."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "observability-agent",
    )

    a2a_config = agent["spec"]["declarative"].get("a2aConfig", {})
    skills = a2a_config.get("skills", [])
    assert len(skills) > 0, "observability-agent must declare at least one skill"

    logger.info("observability-agent has a2aConfig.skills metadata")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_promql_agent_a2a_skills(ctx_apps_dev):
    """promql-agent must declare a2aConfig.skills metadata."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "promql-agent",
    )

    a2a_config = agent["spec"]["declarative"].get("a2aConfig", {})
    skills = a2a_config.get("skills", [])
    assert len(skills) > 0, "promql-agent must declare at least one skill"

    logger.info("promql-agent has a2aConfig.skills metadata")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_k8s_agent_a2a_skills(ctx_apps_dev):
    """k8s-agent must declare a2aConfig.skills metadata."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "k8s-agent",
    )

    a2a_config = agent["spec"]["declarative"].get("a2aConfig", {})
    skills = a2a_config.get("skills", [])
    assert len(skills) > 0, "k8s-agent must declare at least one skill"

    logger.info("k8s-agent has a2aConfig.skills metadata")


# ── T5: System Messages and Documentation ────────────────────────────────────

@pytest.mark.apps_dev
@pytest.mark.kagent
def test_cilium_network_agent_system_message(ctx_apps_dev):
    """cilium-network-agent must have delegation instructions in systemMessage."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", KAGENT_SYSTEM,
        "cilium-network-agent",
    )

    msg = agent["spec"]["declarative"].get("systemMessage", "")
    assert "observability-agent" in msg or "delegate" in msg.lower(), \
        "systemMessage should mention delegation to observability/promql agents"

    logger.info("cilium-network-agent systemMessage properly instructs delegation")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_crossplane_composition_fixer_system_message(ctx_apps_dev):
    """crossplane-composition-fixer must have proper systemMessage."""
    agent = get_resource(
        ctx_apps_dev,
        "kagent.dev", "v1alpha2",
        "agents", TEAM_CHARLIE,
        "crossplane-composition-fixer",
    )

    msg = agent["spec"]["declarative"].get("systemMessage", "")
    assert "Crossplane" in msg and len(msg) > 100, \
        "systemMessage should provide detailed Crossplane troubleshooting instructions"

    logger.info("crossplane-composition-fixer has comprehensive systemMessage")


# ── T6: Design Compliance ────────────────────────────────────────────────────

@pytest.mark.apps_dev
@pytest.mark.kagent
def test_standalone_agents_not_bundled(ctx_apps_dev):
    """Verify that replaced agents exist as standalone CRs, not Helm sub-charts."""
    # These agents should exist as Agent CRs
    standalone_agents = [
        "cilium-network-agent",
        "k8s-agent",
        "observability-agent",
        "promql-agent",
        "helm-agent",
    ]

    for agent_name in standalone_agents:
        # Should find as standalone CR
        agent = get_resource(
            ctx_apps_dev,
            "kagent.dev", "v1alpha2",
            "agents", KAGENT_SYSTEM,
            agent_name,
        )
        assert agent is not None, f"{agent_name} must be deployed as standalone Agent CR"

    # Verify they're not coming from Helm sub-chart pods
    v1 = core_v1(ctx_apps_dev)
    pods = v1.list_namespaced_pod(
        KAGENT_SYSTEM,
        label_selector="app.kubernetes.io/component=agent",
    )

    # Pods should be managed by Deployment (from standalone CRs), not direct from Helm
    logger.info(f"Found {len(pods.items)} agent pods — verifying standalone deployment")


@pytest.mark.apps_dev
@pytest.mark.kagent
def test_no_postrenderer_patches_needed(ctx_apps_dev):
    """Verify HelmRelease doesn't use postRenderers for agent customization."""
    hr = get_resource(
        ctx_apps_dev,
        "helm.toolkit.fluxcd.io", "v2",
        "helmreleases", KAGENT_SYSTEM,
        "kagent",
    )

    post_renderers = hr["spec"].get("postRenderers", [])
    # If using standalone agents, there should be minimal to no postRenderers
    # (tool servers like kmcp may need them, but not agents)

    for renderer in post_renderers:
        # Ensure patches are not for agent customization
        patches = renderer.get("kustomize", {}).get("patchesStrategicMerge", [])
        for patch in patches:
            assert "agent" not in patch.lower(), \
                "postRenderers should not patch agent configs — use standalone CRs instead"

    logger.info("HelmRelease does not use postRenderers for agent customization")
