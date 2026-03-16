#!/usr/bin/env python3
"""
Cluster provisioning orchestrator.

Drives: kind (bootstrap) → GKE control-plane → GKE apps-dev
Delegates phase assessment and diagnostics to Claude agents via Anthropic SDK.

Usage:
    uv run python main.py
    uv run python main.py --skip-install
    uv run python main.py --start-phase control
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT      = Path(__file__).resolve().parent.parent
AGENTS_DIR     = REPO_ROOT / ".claude" / "agents"
INSTALL_SCRIPT = REPO_ROOT / "bootstrap" / "bootstrap-control-plane-cluster.sh"
CLEANUP_SCRIPT = REPO_ROOT / "bootstrap" / "scripts" / "00-cleanup.sh"
RUNS_DIR   = REPO_ROOT / "orchestrator" / "runs"
STATE_FILE = RUNS_DIR / "state.json"

PHASES = ["bootstrap", "control", "workload"]
MAX_FIX_ATTEMPTS = 3   # same error signature → escalate instead of looping

# ── phase definitions ─────────────────────────────────────────────────────────
PHASE_DEFINITIONS: dict[str, dict] = {
    "bootstrap": {
        "description": "kind cluster with Crossplane + Flux installed and reconciling",
        "check_interval_minutes": 3,
        "max_wait_minutes": 20,
        "healthy_criteria": """
- All pods in crossplane-system: Running, no CrashLoopBackOff, no Pending
- provider-family-gcp: INSTALLED=True, HEALTHY=True
- provider-gcp-container: INSTALLED=True, HEALTHY=True
- No ProviderRevision in Failed or Unhealthy state
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

def get_assessment_commands(phase: str) -> list[str]:
    """Return kubectl commands appropriate for the current phase."""
    control_ctx = get_gke_context("control-plane")
    apps_ctx    = get_gke_context("apps-dev")

    if phase == "bootstrap":
        return [
            f"kubectl get pods -n crossplane-system --context {KIND_CTX} -o wide",
            f"kubectl get providers --context {KIND_CTX} -o wide",
            f"kubectl get providerrevisions --context {KIND_CTX} -o wide",
            f"kubectl get kustomizations -A --context {KIND_CTX}",
            f"kubectl get gitrepositories -A --context {KIND_CTX}",
            f"kubectl get helmreleases -A --context {KIND_CTX}",
        ]

    elif phase == "control":
        cmds = [
            f"kubectl get gkecluster -A --context {KIND_CTX} -o wide",
            f"kubectl get clusters.container.gcp.crossplane.io -A --context {KIND_CTX} -o wide",
            f"kubectl get nodepools.container.gcp.crossplane.io -A --context {KIND_CTX} -o wide",
            f"kubectl get managed --context {KIND_CTX} -o wide",
            f"kubectl get kustomizations -A --context {KIND_CTX}",
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
            f"kubectl get managed --context {control_ctx} -o wide",
            f"kubectl get kustomizations -A --context {control_ctx}",
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

def collect_cluster_state(phase: str) -> str:
    """Run all assessment commands and format output for the agent."""
    commands = get_assessment_commands(phase)
    parts = []
    for cmd in commands:
        parts.append(f"$ {cmd}")
        parts.append(run_command(cmd))
        parts.append("")
    return "\n".join(parts)

# ── agent helpers ─────────────────────────────────────────────────────────────
def read_agent_prompt(name: str) -> str:
    """Load agent system prompt, stripping YAML frontmatter if present."""
    path = AGENTS_DIR / f"{name}.md"
    text = path.read_text()
    if text.startswith("---"):
        end = text.index("---", 3)
        text = text[end + 3:].lstrip()
    return text

def call_claude(system: str, user: str) -> str:
    """Call Claude via the claude CLI (uses Claude Code subscription, no API billing)."""
    result = subprocess.run(
        ["claude", "-p", user, "--system-prompt", system, "--output-format", "json"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[:300]}")
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
    """
    defn     = PHASE_DEFINITIONS[phase]
    deadline = datetime.now() + timedelta(minutes=defn["max_wait_minutes"])
    system   = read_agent_prompt("phase-checker")

    log(f"── Phase: {phase} ({defn['description']})")
    log(f"   Deadline: {deadline.strftime('%H:%M:%S')} ({defn['max_wait_minutes']}min window)")

    last_errors: list = []

    while datetime.now() < deadline:
        log("   Collecting cluster state...")
        cluster_state = collect_cluster_state(phase)

        user_msg = (
            f"Phase: {phase}\n"
            f"Description: {defn['description']}\n\n"
            f"Healthy criteria:\n{defn['healthy_criteria']}\n\n"
            f"Current cluster state:\n{cluster_state}"
        )

        log("   Calling phase-checker agent...")
        raw = call_claude(system, user_msg)

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
            return "healthy", []

        if recommendation == "teardown":
            log("   Agent recommends immediate teardown.")
            return "teardown", last_errors

        if recommendation == "diagnose":
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
    # Stable key for this error set (order-independent)
    error_key      = json.dumps(sorted(e.get("message", "") for e in errors))
    phase_attempts = state["fix_attempts"].setdefault(phase, {})
    attempt_count  = phase_attempts.get(error_key, 0)

    if attempt_count >= MAX_FIX_ATTEMPTS:
        log(f"   Same error seen {MAX_FIX_ATTEMPTS}× — escalating instead of looping.")
        return "escalate"

    system = read_agent_prompt("diagnostics")
    user_msg = (
        f"Phase: {phase}\n\n"
        f"Errors:\n{json.dumps(errors, indent=2)}\n\n"
        f"Fix attempts so far for this error: {attempt_count}/{MAX_FIX_ATTEMPTS}\n\n"
        f"Current cluster state:\n{collect_cluster_state(phase)}"
    )

    log("   Calling diagnostics agent...")
    raw = call_claude(system, user_msg)

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
        fix_commands = decision.get("fix_commands", [])
        log(f"   Applying {len(fix_commands)} fix command(s)...")
        for cmd in fix_commands:
            log(f"     $ {cmd}")
            out = run_command(cmd, timeout=120)
            log(f"     → {out[:300]}")
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
def run_install() -> bool:
    log(f"Running install: {INSTALL_SCRIPT.name}")
    result = subprocess.run([str(INSTALL_SCRIPT)])
    return result.returncode == 0

def run_cleanup() -> None:
    log(f"Running cleanup: {CLEANUP_SCRIPT.name}")
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
    args = parser.parse_args()

    state = load_state()

    log("══════════════════════════════════════════════")
    log("  Cluster Provisioning Orchestrator")
    log(f"  Start phase : {args.start_phase}")
    log(f"  Skip install: {args.skip_install}")
    log("══════════════════════════════════════════════")

    if not args.skip_install:
        if not run_install():
            log("Install script failed — check output above.")
            sys.exit(1)

    phase_index = PHASES.index(args.start_phase)

    while phase_index < len(PHASES):
        phase          = PHASES[phase_index]
        outcome, errors = run_phase(phase)

        if outcome == "healthy":
            log(f"✓ Phase '{phase}' healthy.")
            phase_index += 1
            continue

        # ── unhealthy path ────────────────────────────────────────────────────
        if outcome == "teardown":
            run_cleanup()
            write_summary(state, "TEARDOWN", phase)
            sys.exit(1)

        # outcome is degraded or timeout — run diagnostics
        if not errors:
            errors = [{"resource": "unknown", "kind": "unknown",
                       "message": f"phase '{phase}' result: {outcome}"}]

        action = handle_failure(phase, errors, state)

        if action == "retry":
            log(f"Fix applied — retrying phase '{phase}'...")
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
