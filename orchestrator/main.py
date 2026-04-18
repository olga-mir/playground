#!/usr/bin/env python3
"""
AI Agent orchestrator which is used to monitor and troubleshoot project provisioning.

Drives: kind (bootstrap) → GKE control-plane → GKE apps-dev
Delegates phase assessment and diagnostics to Claude agents via Anthropic SDK (or `claude -p` directly to use subscription instead of API key))

Usage:
    uv run python main.py
    uv run python main.py --skip-install
    uv run python main.py --start-phase control
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT              = Path(__file__).resolve().parent.parent
AGENTS_DIR             = REPO_ROOT / ".claude" / "agents"
INSTALL_SCRIPT         = REPO_ROOT / "bootstrap" / "bootstrap-control-plane-cluster.sh"
CLEANUP_SCRIPT         = REPO_ROOT / "scripts" / "cleanup.sh"
COLLECT_STATE_SCRIPT   = REPO_ROOT / "scripts" / "collect-cluster-state.sh"
RUNS_DIR   = REPO_ROOT / "orchestrator" / "runs"
STATE_FILE = RUNS_DIR / "state.json"

PHASES = ["bootstrap", "control", "workload"]
MAX_FIX_ATTEMPTS  = 3   # same error signature → escalate instead of looping
DEFAULT_MISSION   = REPO_ROOT / "orchestrator" / "mission.md"

# ── module-level state (signal handler + mission) ─────────────────────────────
_interrupt_state: dict              = {}
_interrupt_phase: str               = "unknown"
_mission_context: str               = ""
_install_proc: subprocess.Popen | None = None
_install_log_path: Path | None      = None
_install_log_fh                     = None   # kept open while proc writes

def _on_sigint(signum, frame):  # noqa: ARG001
    log("\nInterrupted — writing run summary...")
    if _install_proc and _install_proc.poll() is None:
        log(f"  Terminating install script (PID {_install_proc.pid})...")
        _install_proc.terminate()
    if _install_log_fh:
        _install_log_fh.close()
    write_summary(_interrupt_state, "INTERRUPTED", _interrupt_phase)
    sys.exit(0)

# ── phase definitions ─────────────────────────────────────────────────────────
PHASE_DEFINITIONS: dict[str, dict] = {
    "bootstrap": {
        "description": "kind cluster with Crossplane + Flux installed and reconciling",
        "check_interval_minutes": 3,
        "max_wait_minutes": 20,
        "healthy_criteria": """
- All pods in crossplane-system: Running, no CrashLoopBackOff, no Pending
- upbound-provider-family-gcp: INSTALLED=True, HEALTHY=True
- provider-gcp-gke: INSTALLED=True, HEALTHY=True
- Note: crossplane-contrib-provider-family-gcp may be present with HEALTHY=False — this is an auto-installed
  dependency of crossplane-contrib providers (cloudrun, iam) and does NOT affect functionality; ignore it
- No ProviderRevision in Failed or Unhealthy state (excluding crossplane-contrib-provider-family-gcp which is
  auto-managed by Crossplane package dependency resolution and may not have a running pod)
- All Flux Kustomizations: Ready=True, not suspended
- GitRepository: Ready=True, synced to latest remote commit
- No HelmRelease in Failed state
""",
    },
    "control": {
        "description": "GKE control-plane cluster provisioned by Crossplane; Flux bootstrapped on it",
        "check_interval_minutes": 10,
        "max_wait_minutes": 70,
        "healthy_criteria": """
- GKECluster XR for control-plane: READY=True, SYNCED=True
- All managed resources (NodePool, etc.): READY=True, no Err state
- control-plane GKE kubeconfig context reachable (cluster-info returns ok)
- Flux Kustomizations on control-plane cluster: Ready=True, not suspended
- GitRepository on control-plane: Ready=True
""",
    },
    "workload": {
        "description": "GKE apps-dev cluster provisioned by Crossplane on control-plane; Flux bootstrapped",
        "check_interval_minutes": 10,
        "max_wait_minutes": 70,
        "healthy_criteria": """
- GKECluster XR for apps-dev: READY=True, SYNCED=True
- All managed resources for apps-dev: READY=True, no Err state
- apps-dev GKE kubeconfig context reachable
- Flux Kustomizations on apps-dev cluster: Ready=True, not suspended
- GitRepository on apps-dev: Ready=True
""",
    },
}

# ── known-error patterns (handled directly without calling the diagnostics agent) ─
# source-controller rejects GitRepository when secret has GitHub App fields but
# provider:github is absent.  git already contains the fix (committed by the
# bootstrap step), but the controller can't fetch from git to apply it —
# the classic Catch-22.  The orchestrator patches the live object directly;
# the agent can't because guardrails block kubectl writes.
PROVIDER_GITHUB_PATTERN = re.compile(
    r"provider is not set to github|has github app data",
    re.IGNORECASE,
)

# When a Composition changes the namespace (or API group) of composed resources,
# the XR retains stale resourceRefs pointing to the old objects.  Crossplane v2
# namespace-scoped managed resources require a namespace on every ref; stale refs
# without one cause a hard reconcile error.  The fix is to clear spec.resourceRefs
# so Crossplane recreates composed resources from the current Composition.
STALE_RESOURCE_REFS_PATTERN = re.compile(
    r"an empty namespace may not be set when a resource name is provided|"
    r"cannot get composed resource",
    re.IGNORECASE,
)

# A Flux kustomization can get stuck reporting "dependency not ready" even after
# the dependency becomes Ready=True.  The phase-checker only escalates to diagnose
# when it confirms the dependency IS ready, so if we reach handle_failure with this
# error it is a genuine stale condition.  Force-reconcile to clear it.
DEPENDENCY_NOT_READY_PATTERN = re.compile(r"dependency.*not ready", re.IGNORECASE)

# ── cluster context helpers ───────────────────────────────────────────────────
KIND_CTX = "kind-kind-test-cluster"

def get_gke_context(cluster_suffix: str) -> str | None:
    """Discover GKE kubeconfig context by cluster name suffix (project-ID-agnostic)."""
    result = subprocess.run(
        ["kubectl", "config", "get-contexts", "-o", "name"],
        capture_output=True, text=True,
    )
    for line in result.stdout.strip().splitlines():
        if line.strip().endswith(f"_{cluster_suffix}"):
            return line.strip()
    return None

def is_provider_github_error(errors: list) -> bool:
    return any(PROVIDER_GITHUB_PATTERN.search(e.get("message", "")) for e in errors)


def patch_provider_github(phase: str) -> bool:
    """Patch live GitRepository objects that reference flux-system but lack provider:github.

    Returns True if at least one object was patched.
    Runs against every cluster context relevant to the current phase.
    """
    contexts = [KIND_CTX]
    if phase in ("control", "workload"):
        ctx = get_gke_context("control-plane")
        if ctx:
            contexts.append(ctx)
    if phase == "workload":
        ctx = get_gke_context("apps-dev")
        if ctx:
            contexts.append(ctx)

    patched = False
    for ctx in contexts:
        raw = run_command(f"kubectl get gitrepository -A --context {ctx} -o json")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in data.get("items", []):
            secret   = item.get("spec", {}).get("secretRef", {}).get("name", "")
            provider = item.get("spec", {}).get("provider", "")
            if secret == "flux-system" and provider != "github":
                name = item["metadata"]["name"]
                ns   = item["metadata"]["namespace"]
                log(f"   Patching gitrepository/{name} -n {ns} on {ctx}")
                run_command(
                    f"kubectl patch gitrepository {name} -n {ns} --context {ctx} "
                    f"--type=merge -p '{{\"spec\":{{\"provider\":\"github\"}}}}'"
                )
                patched = True
    return patched


def is_stale_resource_refs_error(errors: list) -> bool:
    return any(STALE_RESOURCE_REFS_PATTERN.search(e.get("message", "")) for e in errors)


def clear_stale_resource_refs(phase: str) -> bool:
    """Clear spec.resourceRefs from GKECluster XRs stuck with namespace errors.

    When a Composition is updated (new namespace, new API group), the XR keeps
    stale refs to the old composed objects.  Clearing them lets Crossplane
    recreate composed resources using the current Composition.

    Also ensures the target namespace exists before Crossplane tries to create
    objects in it, to avoid an immediate recreation failure.
    """
    # GKECluster XRs live on the kind cluster (bootstrap/control) or
    # control-plane cluster (workload phase).
    ctx = KIND_CTX if phase in ("bootstrap", "control") else get_gke_context("control-plane")
    if not ctx:
        return False

    raw = run_command(f"kubectl get gkecluster -A --context {ctx} -o json")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False

    cleared = False
    for item in data.get("items", []):
        conditions   = item.get("status", {}).get("conditions", [])
        resource_refs = item.get("spec", {}).get("resourceRefs", [])
        synced_false = any(
            c.get("type") == "Synced" and c.get("status") == "False"
            for c in conditions
        )
        if not (synced_false and resource_refs):
            continue

        xr_name      = item["metadata"]["name"]
        xr_ns        = item["metadata"].get("namespace", "")  # empty for cluster-scoped XRs
        cluster_name = item.get("spec", {}).get("parameters", {}).get("clusterName", "")

        # Ensure composed-resources namespace exists first
        if cluster_name:
            log(f"   Ensuring namespace/{cluster_name} exists on {ctx}")
            run_command(
                f"kubectl create namespace {cluster_name} --context {ctx} "
                f"--dry-run=client -o yaml | kubectl apply --context {ctx} -f -"
            )

        # GKECluster XRs may be cluster-scoped (LegacyCluster) — omit -n when no namespace
        ns_flag = f"-n {xr_ns}" if xr_ns else ""
        log(f"   Clearing stale resourceRefs on gkecluster/{xr_name} {ns_flag} on {ctx}")
        run_command(
            f"kubectl patch gkecluster {xr_name} {ns_flag} --context {ctx} "
            f"--type=merge -p '{{\"spec\":{{\"resourceRefs\":null}}}}'"
        )
        cleared = True
    return cleared


def is_stuck_dependency_error(errors: list) -> bool:
    return any(DEPENDENCY_NOT_READY_PATTERN.search(e.get("message", "")) for e in errors)


def reconcile_stuck_kustomizations(phase: str) -> bool:
    """Force-reconcile kustomizations stuck on a stale 'dependency not ready' condition.

    Uses kubectl to annotate the kustomization (equivalent to flux reconcile),
    which triggers an immediate reconciliation cycle without waiting for the
    normal polling interval.
    """
    ctx = KIND_CTX if phase in ("bootstrap", "control") else get_gke_context("control-plane")
    if not ctx:
        return False

    raw = run_command(f"kubectl get kustomization -A --context {ctx} -o json")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False

    reconciled = False
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    for item in data.get("items", []):
        conditions = item.get("status", {}).get("conditions", [])
        ready_cond = next((c for c in conditions if c.get("type") == "Ready"), {})
        msg = ready_cond.get("message", "")
        if ready_cond.get("status") == "False" and DEPENDENCY_NOT_READY_PATTERN.search(msg):
            name = item["metadata"]["name"]
            ns   = item["metadata"].get("namespace", "flux-system")
            log(f"   Force-reconciling stuck kustomization/{name} -n {ns} on {ctx}")
            run_command(
                f"kubectl annotate kustomization {name} -n {ns} --context {ctx} "
                f"reconcile.fluxcd.io/requestedAt={ts} --overwrite"
            )
            reconciled = True
    return reconciled


# ── command execution ─────────────────────────────────────────────────────────
def run_command(cmd: str, timeout: int = 60) -> str:
    """Run a shell command, return combined stdout+stderr."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        out = result.stdout.strip()
        if result.returncode != 0 and result.stderr.strip():
            out += f"\n[stderr] {result.stderr.strip()}"
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[timed out after {timeout}s]"
    except Exception as e:
        return f"[error: {e}]"

def get_install_status() -> str:
    """Return a one-line install script status for inclusion in agent context."""
    if _install_proc is None:
        return "install script: not started (--skip-install mode)"
    rc = _install_proc.poll()
    if rc is None:
        return f"install script: STILL RUNNING (PID {_install_proc.pid}) — log: {_install_log_path}"
    if rc == 0:
        return f"install script: completed successfully — log: {_install_log_path}"
    return f"install script: FAILED (exit {rc}) — log: {_install_log_path}"

def snapshot_cluster_state(phase: str) -> None:
    """Run collect-cluster-state.sh for a timestamped snapshot (reference/evidence only).

    The snapshot is NOT passed to agents — agents use kubectl tools directly.
    Output is suppressed; the script writes to orchestrator/runs/ itself.
    """
    try:
        result = subprocess.run(
            [str(COLLECT_STATE_SCRIPT), phase],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log(f"   collect-cluster-state.sh exited {result.returncode} — snapshot may be incomplete")
    except subprocess.TimeoutExpired:
        log("   collect-cluster-state.sh timed out — snapshot skipped")

# ── agent helpers ─────────────────────────────────────────────────────────────
def load_mission(path: Path | None) -> str:
    """Load mission context file. Falls back to orchestrator/mission.md if present."""
    candidates = [path, DEFAULT_MISSION]
    for p in candidates:
        if p and p.exists():
            log(f"Mission context: {p}")
            return p.read_text()
    log("No mission.md found — agents will have no task context (consider creating orchestrator/mission.md)")
    return ""

def read_agent_prompt(name: str) -> str:
    """Load agent system prompt, stripping YAML frontmatter if present."""
    path = AGENTS_DIR / f"{name}.md"
    text = path.read_text()
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:].lstrip()
    return text

def call_claude(system: str, user: str, agent_name: str = "agent") -> str:
    """Call Claude via the claude CLI (uses Claude Code subscription, no API billing).

    --system-prompt forces direct API mode (requires ANTHROPIC_API_KEY), so we fold
    the agent instructions into the message instead. Claude Code then also loads
    CLAUDE.md / AGENTS.md automatically, which gives agents useful project context.

    Runs with cwd=REPO_ROOT so tool-using agents resolve file paths correctly.
    User message is piped via stdin to avoid OS arg-length limits.

    Debug logs (tool calls, hook output, API traffic) are written to
    orchestrator/runs/agent-<name>-<ts>.log — tail -f to follow in real time.
    """
    if _mission_context:
        user = f"## Current Mission\n\n{_mission_context}\n\n---\n\n{user}"
    message = f"{system}\n\n---\n\n{user}"
    # Strip ANTHROPIC_API_KEY so Claude Code uses subscription auth, not the API key
    # (the key may be set for other tools like kagent but breaks claude -p)
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts        = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    debug_log = RUNS_DIR / f"agent-{agent_name}-{ts}.log"
    log(f"   Agent debug log → tail -f {debug_log}")
    try:
        result = subprocess.run(
            ["claude", "-p", "--output-format", "json", "--debug-file", str(debug_log)],
            input=message,
            capture_output=True, text=True,
            timeout=900,        # tool-using agents need time: file reads, git ops, kubectl
            cwd=str(REPO_ROOT), # agents resolve paths relative to repo root
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"claude agent '{agent_name}' timed out after {e.timeout}s") from e
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "(no output)")[:500]
        raise RuntimeError(f"claude exited {result.returncode}:\n{detail}")
    return json.loads(result.stdout)["result"]

def parse_json_response(text: str) -> dict:
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON in response: {text[:300]}")
    return json.loads(text[start:end])

# ── state ─────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"fix_attempts": {}, "restart_count": 0}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ── logging ───────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ── phase runner ──────────────────────────────────────────────────────────────
def run_phase(phase: str) -> tuple[str, list]:
    """
    Poll a phase until healthy, timeout, or hard failure.

    Returns (outcome, errors) where outcome is one of:
        healthy | timeout | degraded | teardown
    errors is the list from the last verdict (empty if healthy).

    The phase-checker agent uses kubectl tools directly rather than receiving
    pre-collected state — this gives it the freedom to drill into exactly what
    it needs without processing unrelated output.
    """
    defn     = PHASE_DEFINITIONS[phase]
    deadline = datetime.now() + timedelta(minutes=defn["max_wait_minutes"])
    system   = read_agent_prompt("phase-checker")

    log(f"── Phase: {phase} ({defn['description']})")
    log(f"   Deadline: {deadline.strftime('%H:%M:%S')} ({defn['max_wait_minutes']}min window)")

    last_errors: list = []
    check_number      = 0
    phase_start       = datetime.now()

    while datetime.now() < deadline:
        check_number += 1
        elapsed_min   = int((datetime.now() - phase_start).total_seconds() / 60)

        user_msg = (
            f"Phase: {phase}\n"
            f"Description: {defn['description']}\n"
            f"Check number: {check_number} (elapsed: {elapsed_min}min into a {defn['max_wait_minutes']}min window)\n"
            f"Install status: {get_install_status()}\n\n"
            f"Healthy criteria:\n{defn['healthy_criteria']}\n\n"
            f"Use kubectl to inspect the cluster(s) for this phase and assess their health."
        )

        log("   Calling phase-checker agent...")
        try:
            raw = call_claude(system, user_msg, agent_name="phase-checker")
        except RuntimeError as e:
            log(f"   Phase-checker failed: {e} — waiting 60s and retrying")
            time.sleep(60)
            continue

        try:
            verdict = parse_json_response(raw)
        except (ValueError, json.JSONDecodeError) as e:
            log(f"   Parse error: {e} — waiting 60s and retrying")
            time.sleep(60)
            continue

        status         = verdict.get("status", "unknown")
        recommendation = verdict.get("recommendation", "wait")
        last_errors    = verdict.get("errors", [])
        problem_domain = verdict.get("problem_domain", "unknown")

        log(f"   status={status}  recommendation={recommendation}  domain={problem_domain}")
        if verdict.get("analysis"):
            log(f"   {verdict['analysis']}")

        if status == "healthy":
            return "healthy", []

        if recommendation == "teardown":
            log("   Agent recommends immediate teardown.")
            return "teardown", last_errors

        if recommendation == "diagnose":
            # Attach domain for routing in handle_failure
            for e in last_errors:
                e.setdefault("_domain", problem_domain)
            return "degraded", last_errors

        # recommendation == "wait" — sleep and loop
        remaining = (deadline - datetime.now()).total_seconds()
        wait_s    = min(defn["check_interval_minutes"] * 60, remaining)
        if wait_s <= 0:
            break
        log(f"   Waiting {int(wait_s / 60)}min before next check...")
        time.sleep(wait_s)

    return "timeout", last_errors

# ── diagnostics runner ────────────────────────────────────────────────────────
def handle_failure(
    phase: str,
    errors: list,
    state: dict,
) -> str:
    """
    Run diagnostics agent. Returns: retry | teardown | escalate
    Tracks fix attempts per error signature to enforce the escalation limit.
    """
    # Stable key for this error set (order-independent).
    # Normalise out numeric values (elapsed times, counts) so that "after 90 minutes"
    # and "after 91 minutes" hash to the same signature and don't bypass the attempt limit.
    def _normalise(msg: str) -> str:
        return re.sub(r"\d+", "N", msg)

    error_key      = json.dumps(sorted(_normalise(e.get("message", "")) for e in errors))
    phase_attempts = state["fix_attempts"].setdefault(phase, {})
    attempt_count  = phase_attempts.get(error_key, 0)

    if attempt_count >= MAX_FIX_ATTEMPTS:
        log(f"   Same error seen {MAX_FIX_ATTEMPTS}× — escalating instead of looping.")
        return "escalate"

    # ── known Catch-22: provider:github missing on live GitRepository ─────────
    # git already has the fix; source-controller can't fetch to apply it because
    # it considers the GitRepository broken.  Apply the live patch directly from
    # the orchestrator — no agent needed, and guardrails don't block Python subprocesses.
    if is_provider_github_error(errors):
        log("   Detected provider:github Catch-22 — patching live GitRepositories directly")
        if patch_provider_github(phase):
            phase_attempts[error_key] = attempt_count + 1
            save_state(state)
            log("   Live patch applied — waiting 30s for GitRepository to recover...")
            time.sleep(30)
            return "retry_live"
        log("   No GitRepositories needed patching — falling through to diagnostics agent")

    # ── known: stale resourceRefs after Composition API group / namespace change ─
    # When the Composition changes namespace or API group, the XR retains refs to
    # old composed objects.  Crossplane v2 namespace-scoped resources require a
    # namespace on every ref; stale refs without one cause a hard reconcile error.
    if is_stale_resource_refs_error(errors):
        log("   Detected stale resourceRefs — clearing and ensuring namespace exists")
        if clear_stale_resource_refs(phase):
            phase_attempts[error_key] = attempt_count + 1
            save_state(state)
            log("   resourceRefs cleared — waiting 30s for Crossplane to re-reconcile...")
            time.sleep(30)
            return "retry_live"
        log("   No XRs needed clearing — falling through to diagnostics agent")

    # ── known: kustomization stuck with stale 'dependency not ready' condition ─
    # Flux can get stuck reporting a dependency as not ready even after the
    # dependency becomes Ready=True.  The phase-checker only escalates when it
    # has confirmed the dependency IS ready, so we can safely force-reconcile.
    if is_stuck_dependency_error(errors):
        log("   Detected stuck 'dependency not ready' — force-reconciling kustomizations")
        if reconcile_stuck_kustomizations(phase):
            phase_attempts[error_key] = attempt_count + 1
            save_state(state)
            log("   Reconciliation triggered — waiting 60s for kustomizations to settle...")
            time.sleep(60)
            return "retry_live"
        log("   No stuck kustomizations found — falling through to diagnostics agent")

    # ── route to specialist based on problem_domain ───────────────────────────
    # domain is attached to each error entry by run_phase
    domain = next((e.get("_domain", "unknown") for e in errors), "unknown")
    domain_to_agent = {
        "crossplane":     "crossplane-diagnostics",
        "flux":           "diagnostics",        # flux-diagnostics agent is a future specialisation
        "github-actions": "diagnostics",        # github-actions-flux-debugger wiring deferred
        "unknown":        "diagnostics",
    }
    agent_name = domain_to_agent.get(domain, "diagnostics")
    log(f"   Routing to agent '{agent_name}' (domain={domain})")

    system = read_agent_prompt(agent_name)
    user_msg = (
        f"Phase: {phase}\n\n"
        f"Errors:\n{json.dumps(errors, indent=2)}\n\n"
        f"Fix attempts so far for this error: {attempt_count}/{MAX_FIX_ATTEMPTS}\n\n"
        f"Use kubectl to investigate the cluster state for this phase."
    )

    log(f"   Calling {agent_name} agent...")
    try:
        raw = call_claude(system, user_msg, agent_name=agent_name)
    except RuntimeError as e:
        log(f"   Diagnostics agent failed: {e} — escalating")
        return "escalate"

    try:
        decision = parse_json_response(raw)
    except (ValueError, json.JSONDecodeError) as e:
        log(f"   Diagnostics parse error: {e} — escalating")
        return "escalate"

    action     = decision.get("decision", "escalate")
    rationale  = decision.get("rationale", "")
    confidence = decision.get("confidence", "unknown")
    log(f"   diagnostics: decision={action}  confidence={confidence}")
    log(f"   {rationale}")

    if action == "fix_forward":
        # Agent handles git add/commit/push directly.
        # The guardrails PreToolUse hook does fetch+rebase before each push.
        phase_attempts[error_key] = attempt_count + 1
        save_state(state)
        return "retry"

    if action == "teardown":
        return "teardown"

    return "escalate"

# ── summary ───────────────────────────────────────────────────────────────────
def write_summary(state: dict, outcome: str, phase: str) -> None:
    ts   = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = RUNS_DIR / f"run-{outcome.lower()}-{ts}.md"
    path.write_text(
        f"# Orchestrator Run — {outcome}\n\n"
        f"Date: {ts}\n"
        f"Stopped at phase: {phase}\n"
        f"Restart count: {state.get('restart_count', 0)}\n\n"
        f"## Fix attempts\n\n"
        f"```json\n{json.dumps(state.get('fix_attempts', {}), indent=2)}\n```\n"
    )
    log(f"Summary → {path}")

# ── install / cleanup ─────────────────────────────────────────────────────────
def run_install_background() -> bool:
    """Launch install script in background. Logs to orchestrator/runs/install-<ts>.log.
    Returns False immediately if the script fails to start."""
    global _install_proc, _install_log_path, _install_log_fh
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    _install_log_path = RUNS_DIR / f"install-{ts}.log"
    _install_log_fh   = open(_install_log_path, "w")
    try:
        _install_proc = subprocess.Popen(
            [str(INSTALL_SCRIPT)],
            stdout=_install_log_fh,
            stderr=subprocess.STDOUT,
        )
    except OSError as e:
        log(f"Failed to start install script: {e}")
        _install_log_fh.close()
        return False
    log(f"Install script running in background  PID={_install_proc.pid}")
    log(f"Log: {_install_log_path}   (tail -f to follow)")
    return True

def wait_before_first_check(seconds: int) -> bool:
    """Wait before the first phase check. Polls every 30s for early install failure.
    Returns False if install failed during the wait."""
    log(f"Waiting {seconds // 60}min before first phase check...")
    poll_interval = 30
    elapsed = 0
    while elapsed < seconds:
        time.sleep(poll_interval)
        elapsed += poll_interval
        if _install_proc:
            rc = _install_proc.poll()
            if rc is not None and rc != 0:
                log(f"Install script failed early (exit {rc}) — check {_install_log_path}")
                return False
            if rc == 0:
                log("Install script finished — starting phase checks immediately")
                return True
        remaining = seconds - elapsed
        if remaining > 0:
            log(f"  {remaining // 60}m{remaining % 60:02d}s until first phase check  ({get_install_status()})")
    return True


def save_state_snapshot(label: str, phase: str) -> None:
    """Run collect-cluster-state.sh and save a timestamped snapshot.

    Snapshot is for reference and release evidence only — not passed to agents.
    collect-cluster-state.sh writes the file itself; we just invoke it here with
    a label-specific env hint via the filename convention.
    """
    log(f"   Saving fleet state snapshot ({label})...")
    snapshot_cluster_state(phase)


def run_cleanup() -> None:
    log(f"Running cleanup: {CLEANUP_SCRIPT.name}")
    if _install_proc and _install_proc.poll() is None:
        log(f"  Terminating running install script (PID {_install_proc.pid}) first...")
        _install_proc.terminate()
        _install_proc.wait(timeout=10)
    subprocess.run([str(CLEANUP_SCRIPT)])

# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster provisioning orchestrator")
    parser.add_argument(
        "--skip-install", action="store_true",
        help="Skip running the install script (jump straight to phase checks)",
    )
    parser.add_argument(
        "--start-phase", choices=PHASES, default="bootstrap",
        help="Start from a specific phase (default: bootstrap)",
    )
    parser.add_argument(
        "--mission", type=Path, default=None,
        help="Path to mission context file (default: orchestrator/mission.md if present)",
    )
    parser.add_argument(
        "--initial-wait", type=int, default=300, metavar="SECONDS",
        help="Seconds to wait after starting install before the first phase check (default: 300 = 5min)",
    )
    args = parser.parse_args()

    state = load_state()

    global _interrupt_state, _interrupt_phase, _mission_context
    _mission_context = load_mission(args.mission)
    _interrupt_state = state
    _interrupt_phase = args.start_phase
    signal.signal(signal.SIGINT, _on_sigint)

    log("══════════════════════════════════════════════")
    log("  Cluster Provisioning Orchestrator")
    log(f"  Start phase  : {args.start_phase}")
    log(f"  Skip install : {args.skip_install}")
    log(f"  Initial wait : {args.initial_wait}s")
    log("══════════════════════════════════════════════")

    if not args.skip_install:
        if not run_install_background():
            log("Failed to launch install script.")
            sys.exit(1)
        if not wait_before_first_check(args.initial_wait):
            log("Install script failed during initial wait — aborting.")
            write_summary(state, "FAILED", args.start_phase)
            sys.exit(1)

    phase_index = PHASES.index(args.start_phase)

    while phase_index < len(PHASES):
        phase            = PHASES[phase_index]
        _interrupt_phase = phase

        # If install is still running and has now exited, close log handle and check result
        if _install_proc and _install_proc.poll() is not None:
            if _install_log_fh and not _install_log_fh.closed:
                _install_log_fh.close()
            if _install_proc.returncode != 0:
                log(f"Install script exited with error (code {_install_proc.returncode}) — check {_install_log_path}")
                write_summary(state, "FAILED", phase)
                sys.exit(1)

        outcome, errors = run_phase(phase)

        if outcome == "healthy":
            log(f"✓ Phase '{phase}' healthy.")
            save_state_snapshot(f"{phase}-healthy", phase)
            phase_index += 1
            continue

        # ── unhealthy path ────────────────────────────────────────────────────
        if outcome == "teardown":
            save_state_snapshot(f"{phase}-teardown", phase)
            run_cleanup()
            write_summary(state, "TEARDOWN", phase)
            sys.exit(1)

        # outcome is degraded or timeout — run diagnostics
        if not errors:
            errors = [{"resource": "unknown", "kind": "unknown",
                       "message": f"phase '{phase}' result: {outcome}"}]

        save_state_snapshot(f"{phase}-pre-diagnostics", phase)
        action = handle_failure(phase, errors, state)

        if action == "retry":
            log("Fix committed to develop — waiting 2min for Flux to reconcile...")
            time.sleep(120)
            continue

        if action == "retry_live":
            log("Live fix applied — waiting 2min for cluster state to settle...")
            time.sleep(120)
            continue

        if action == "teardown":
            log("Diagnostics recommends teardown. Running cleanup and restarting...")
            run_cleanup()
            state["restart_count"] = state.get("restart_count", 0) + 1
            state["fix_attempts"]  = {}
            save_state(state)

            if state["restart_count"] >= 2:
                log("Already restarted twice — escalating.")
                write_summary(state, "ESCALATED", phase)
                sys.exit(1)

            if not run_install():
                log("Re-install failed.")
                write_summary(state, "FAILED", phase)
                sys.exit(1)

            phase_index = 0  # restart from bootstrap
            continue

        # action == escalate
        write_summary(state, "ESCALATED", phase)
        log(f"Escalation at phase '{phase}'. Manual intervention required.")
        sys.exit(1)

    log("══════════════════════════════════════════════")
    log("  ALL PHASES HEALTHY")
    log("══════════════════════════════════════════════")
    write_summary(state, "SUCCESS", "all")


if __name__ == "__main__":
    main()
