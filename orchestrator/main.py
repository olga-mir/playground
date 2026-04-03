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
REPO_ROOT           = Path(__file__).resolve().parent.parent
AGENTS_DIR          = REPO_ROOT / ".claude" / "agents"
INSTALL_SCRIPT      = REPO_ROOT / "bootstrap" / "bootstrap-control-plane-cluster.sh"
CLEANUP_SCRIPT      = REPO_ROOT / "scripts" / "cleanup.sh"
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


def get_assessment_commands(phase: str) -> list[str]:
    """Return kubectl commands appropriate for the current phase."""
    control_ctx = get_gke_context("control-plane")
    apps_ctx    = get_gke_context("apps-dev")

    if phase == "bootstrap":
        return [
            f"kubectl get pods -n crossplane-system --context {KIND_CTX} -o wide",
            f"kubectl get providers.pkg.crossplane.io --context {KIND_CTX} -o wide",
            f"kubectl get providerrevisions.pkg.crossplane.io --context {KIND_CTX} -o wide",
            f"kubectl get functions.pkg.crossplane.io --context {KIND_CTX} -o wide",
            f"kubectl get kustomizations -A --context {KIND_CTX}",
            f"kubectl describe kustomizations -A --context {KIND_CTX}",
            f"kubectl get gitrepositories -A --context {KIND_CTX}",
            f"kubectl get helmreleases -A --context {KIND_CTX}",
            f"kubectl describe providers.pkg.crossplane.io --context {KIND_CTX}",
        ]

    elif phase == "control":
        cmds = [
            f"kubectl get gkecluster -A --context {KIND_CTX} -o wide",
            f"kubectl describe gkecluster -A --context {KIND_CTX}",
            f"kubectl get managed --context {KIND_CTX} -o wide",
            f"kubectl get providers.pkg.crossplane.io --context {KIND_CTX} -o wide",
            f"kubectl get compositions --context {KIND_CTX} -o wide",
            # CRD inventory: critical for provider migrations — shows which API groups are registered
            f"kubectl get crds --context {KIND_CTX} --no-headers | grep -E 'gke\\.gcp|container\\.gcp' | awk '{{print $1}}' | sort",
            f"kubectl get events -A --context {KIND_CTX} --sort-by=.lastTimestamp --field-selector type=Warning",
            f"kubectl get kustomizations -A --context {KIND_CTX}",
            f"kubectl logs -n crossplane-system --context {KIND_CTX} -l pkg.crossplane.io/revision --tail=40 --prefix",
        ]
        if control_ctx:
            cmds += [
                f"kubectl cluster-info --context {control_ctx}",
                f"kubectl get kustomizations -A --context {control_ctx}",
                f"kubectl get gitrepositories -A --context {control_ctx}",
                f"kubectl get pods -n flux-system --context {control_ctx}",
            ]
        else:
            cmds.append("# control-plane GKE context not yet in kubeconfig — cluster still provisioning")
        return cmds

    elif phase == "workload":
        if not control_ctx:
            return ["# control-plane context not available — cannot assess workload phase yet"]
        cmds = [
            f"kubectl get gkecluster -A --context {control_ctx} -o wide",
            f"kubectl describe gkecluster -A --context {control_ctx}",
            f"kubectl get managed --context {control_ctx} -o wide",
            f"kubectl get events -A --context {control_ctx} --sort-by=.lastTimestamp --field-selector type=Warning",
            f"kubectl get kustomizations -A --context {control_ctx}",
            f"kubectl logs -n crossplane-system --context {control_ctx} -l pkg.crossplane.io/revision --tail=40 --prefix",
        ]
        if apps_ctx:
            cmds += [
                f"kubectl cluster-info --context {apps_ctx}",
                f"kubectl get kustomizations -A --context {apps_ctx}",
                f"kubectl get gitrepositories -A --context {apps_ctx}",
                f"kubectl get pods -n flux-system --context {apps_ctx}",
            ]
        else:
            cmds.append("# apps-dev GKE context not yet in kubeconfig — cluster still provisioning")
        return cmds

    return []

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

def collect_cluster_state(phase: str) -> str:
    """Run all assessment commands and format output for the agent."""
    commands = get_assessment_commands(phase)
    parts = [f"## Install status\n{get_install_status()}\n"]
    for cmd in commands:
        parts.append(f"$ {cmd}")
        parts.append(run_command(cmd))
        parts.append("")
    return "\n".join(parts)

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
    result = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--debug-file", str(debug_log)],
        input=message,
        capture_output=True, text=True,
        timeout=600,        # tool-using agents need time: file reads, git ops, kubectl
        cwd=str(REPO_ROOT), # agents resolve paths relative to repo root
        env=env,
    )
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
def run_phase(phase: str) -> tuple[str, list, str]:
    """
    Poll a phase until healthy, timeout, or hard failure.

    Returns (outcome, errors, last_cluster_state) where outcome is one of:
        healthy | timeout | degraded | teardown
    errors is the list from the last verdict (empty if healthy).
    last_cluster_state is the kubectl output from the final check cycle.
    """
    defn     = PHASE_DEFINITIONS[phase]
    deadline = datetime.now() + timedelta(minutes=defn["max_wait_minutes"])
    system   = read_agent_prompt("phase-checker")

    log(f"── Phase: {phase} ({defn['description']})")
    log(f"   Deadline: {deadline.strftime('%H:%M:%S')} ({defn['max_wait_minutes']}min window)")

    last_errors: list       = []
    last_cluster_state: str = ""
    check_number   = 0
    phase_start    = datetime.now()

    while datetime.now() < deadline:
        check_number += 1
        elapsed_min   = int((datetime.now() - phase_start).total_seconds() / 60)

        log("   Collecting cluster state...")
        cluster_state      = collect_cluster_state(phase)
        last_cluster_state = cluster_state

        user_msg = (
            f"Phase: {phase}\n"
            f"Description: {defn['description']}\n"
            f"Check number: {check_number} (elapsed: {elapsed_min}min into a {defn['max_wait_minutes']}min window)\n\n"
            f"Healthy criteria:\n{defn['healthy_criteria']}\n\n"
            f"Current cluster state:\n{cluster_state}"
        )

        log("   Calling phase-checker agent...")
        raw = call_claude(system, user_msg, agent_name="phase-checker")

        try:
            verdict = parse_json_response(raw)
        except (ValueError, json.JSONDecodeError) as e:
            log(f"   Parse error: {e} — waiting 60s and retrying")
            time.sleep(60)
            continue

        status         = verdict.get("status", "unknown")
        recommendation = verdict.get("recommendation", "wait")
        last_errors    = verdict.get("errors", [])

        log(f"   status={status}  recommendation={recommendation}")
        if verdict.get("analysis"):
            log(f"   {verdict['analysis']}")

        if status == "healthy":
            return "healthy", [], last_cluster_state

        if recommendation == "teardown":
            log("   Agent recommends immediate teardown.")
            return "teardown", last_errors, last_cluster_state

        if recommendation == "diagnose":
            return "degraded", last_errors, last_cluster_state

        # recommendation == "wait" — sleep and loop
        remaining = (deadline - datetime.now()).total_seconds()
        wait_s    = min(defn["check_interval_minutes"] * 60, remaining)
        if wait_s <= 0:
            break
        log(f"   Waiting {int(wait_s / 60)}min before next check...")
        time.sleep(wait_s)

    return "timeout", last_errors, last_cluster_state

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
            return "retry"
        log("   No GitRepositories needed patching — falling through to diagnostics agent")

    system = read_agent_prompt("diagnostics")
    user_msg = (
        f"Phase: {phase}\n\n"
        f"Errors:\n{json.dumps(errors, indent=2)}\n\n"
        f"Fix attempts so far for this error: {attempt_count}/{MAX_FIX_ATTEMPTS}\n\n"
        f"Current cluster state:\n{collect_cluster_state(phase)}"
    )

    log("   Calling diagnostics agent...")
    raw = call_claude(system, user_msg, agent_name="diagnostics")

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


def save_state_snapshot(label: str, phase: str, cluster_state: str) -> None:
    """Save cluster state snapshot to runs/snapshot-<label>-<ts>.txt.

    Uses the already-collected cluster_state (same data the phase-checker agent saw).
    check-fleet-health.sh is not used here: it relies on grep pipelines that fail with
    set -eou pipefail when GKE contexts are absent (e.g. during bootstrap phase).
    """
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = RUNS_DIR / f"snapshot-{label}-{ts}.txt"
    log(f"   Saving fleet state snapshot → {path.name}")
    path.write_text(
        f"# Fleet State Snapshot — {label}\n"
        f"# Phase: {phase}  |  {ts}\n\n"
        f"{cluster_state}\n"
    )


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

        outcome, errors, cluster_state = run_phase(phase)

        if outcome == "healthy":
            log(f"✓ Phase '{phase}' healthy.")
            save_state_snapshot(f"{phase}-healthy", phase, cluster_state)
            phase_index += 1
            continue

        # ── unhealthy path ────────────────────────────────────────────────────
        if outcome == "teardown":
            save_state_snapshot(f"{phase}-teardown", phase, cluster_state)
            run_cleanup()
            write_summary(state, "TEARDOWN", phase)
            sys.exit(1)

        # outcome is degraded or timeout — run diagnostics
        if not errors:
            errors = [{"resource": "unknown", "kind": "unknown",
                       "message": f"phase '{phase}' result: {outcome}"}]

        save_state_snapshot(f"{phase}-pre-diagnostics", phase, cluster_state)
        action = handle_failure(phase, errors, state)

        if action == "retry":
            log("Fix pushed to develop — waiting 2min for Flux to reconcile...")
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
