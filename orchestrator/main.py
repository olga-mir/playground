#!/usr/bin/env python3
"""
AI Agent orchestrator for cluster provisioning.
Drives: kind (bootstrap) → GKE control-plane → GKE apps-dev

Assessment: dspy.ChainOfThought(AssessPhaseHealth) — analyzes pre-collected cluster state.
Diagnosis:  dspy.ReAct(DiagnoseFailure) — live kubectl investigation + git-based fixes.
Fallback:   LiteLLM model chain (Local Spark → OpenRouter → Vertex AI).

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

import dspy

import orchestrator.telemetry as telemetry
from orchestrator.llm_router import get_lm
from orchestrator.signatures import AssessPhaseHealth, DiagnoseFailure

# ── paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT            = Path(__file__).resolve().parent.parent
PHASES_DIR           = Path(__file__).resolve().parent / "phases"
INSTALL_SCRIPT       = REPO_ROOT / "bootstrap" / "bootstrap-control-plane-cluster.sh"
CLEANUP_SCRIPT       = REPO_ROOT / "scripts" / "cleanup.sh"
COLLECT_STATE_SCRIPT = REPO_ROOT / "scripts" / "collect-cluster-state.sh"
RUNS_DIR             = Path(__file__).resolve().parent / "runs"
STATE_FILE           = RUNS_DIR / "state.json"
DEFAULT_MISSION      = Path(__file__).resolve().parent / "mission.md"

PHASES           = ["bootstrap", "control", "workload"]
MAX_FIX_ATTEMPTS = 3
KIND_CTX         = "kind-kind-test-cluster"

PHASE_TIMING: dict[str, dict] = {
    "bootstrap": {"check_interval_minutes": 3,  "max_wait_minutes": 20},
    "control":   {"check_interval_minutes": 10, "max_wait_minutes": 70},
    "workload":  {"check_interval_minutes": 10, "max_wait_minutes": 70},
}

# ── module-level state ────────────────────────────────────────────────────────
_interrupt_state: dict                  = {}
_interrupt_phase: str                   = "unknown"
_mission_context: str                   = ""
_install_proc: subprocess.Popen | None  = None
_install_log_path: Path | None          = None
_install_log_fh                         = None

def _on_sigint(signum, frame):  # noqa: ARG001
    log("\nInterrupted — writing run summary...")
    if _install_proc and _install_proc.poll() is None:
        log(f"  Terminating install script (PID {_install_proc.pid})...")
        _install_proc.terminate()
    if _install_log_fh:
        _install_log_fh.close()
    write_summary(_interrupt_state, "INTERRUPTED", _interrupt_phase)
    try:
        telemetry.shutdown()
    except Exception:
        pass
    sys.exit(0)

# ── known-error patterns (fast-path Python remedies) ─────────────────────────
# source-controller rejects GitRepository when provider:github is absent but
# the secret contains GitHub App fields. Git has the fix but can't fetch to
# apply it — classic Catch-22. Patch the live object directly.
PROVIDER_GITHUB_PATTERN = re.compile(
    r"provider is not set to github|has github app data",
    re.IGNORECASE,
)

# When a Composition changes namespace/API group, the XR retains stale
# resourceRefs to old objects. Crossplane v2 requires a namespace on every
# ref; stale refs without one cause a hard reconcile error.
STALE_RESOURCE_REFS_PATTERN = re.compile(
    r"an empty namespace may not be set when a resource name is provided|"
    r"cannot get composed resource",
    re.IGNORECASE,
)

# Flux kustomizations can get stuck reporting "dependency not ready" even
# after the dependency is Ready=True. Force-reconcile to clear.
DEPENDENCY_NOT_READY_PATTERN = re.compile(r"dependency.*not ready", re.IGNORECASE)

# ── cluster context helpers ───────────────────────────────────────────────────
def get_gke_context(cluster_suffix: str) -> str | None:
    result = subprocess.run(
        ["kubectl", "config", "get-contexts", "-o", "name"],
        capture_output=True, text=True,
    )
    for line in result.stdout.strip().splitlines():
        if line.strip().endswith(f"_{cluster_suffix}"):
            return line.strip()
    return None

# ── tool implementations for DiagnoseFailure ReAct ───────────────────────────
# Output is capped to avoid context overflow on large cluster state dumps.
_MAX_TOOL_OUTPUT = 8000

def _shell(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = r.stdout.strip()
        if r.returncode != 0 and r.stderr.strip():
            out += f"\n[stderr] {r.stderr.strip()}"
        return (out or "(no output)")[:_MAX_TOOL_OUTPUT]
    except subprocess.TimeoutExpired:
        return f"[timed out after {timeout}s]"
    except Exception as e:
        return f"[error: {e}]"


def kubectl_get(args: str) -> str:
    """Run kubectl get. Include resource type, --namespace/-n, --context, and output flags in args.
    Example: 'pods -n crossplane-system --context kind-kind-test-cluster -o wide'"""
    return _shell(f"kubectl get {args}")


def kubectl_describe(args: str) -> str:
    """Run kubectl describe. Include resource type, name, --namespace/-n, and --context in args.
    Example: 'provider upbound-provider-family-gcp --context kind-kind-test-cluster'"""
    return _shell(f"kubectl describe {args}", timeout=30)


def kubectl_logs(args: str) -> str:
    """Get pod/container logs. Include pod name, --namespace/-n, --context, and --tail in args.
    Example: 'crossplane-7d9f6b -n crossplane-system --context kind-kind-test-cluster --tail=50'"""
    return _shell(f"kubectl logs {args}", timeout=30)


def kubectl_patch(args: str) -> str:
    """Run kubectl patch to apply a live fix. Include resource type, name, --namespace/-n,
    --context, --type (merge/json/strategic), and -p with the patch JSON in args.
    Example: 'gitrepository flux-system -n flux-system --context kind-kind-test-cluster
              --type=merge -p {\"spec\":{\"provider\":\"github\"}}'"""
    return _shell(f"kubectl patch {args}", timeout=30)


def kubectl_annotate(args: str) -> str:
    """Run kubectl annotate. Useful for force-reconciling Flux kustomizations.
    Example: 'kustomization infra -n flux-system --context kind-kind-test-cluster
              reconcile.fluxcd.io/requestedAt=2024-01-01T00:00:00Z --overwrite'"""
    return _shell(f"kubectl annotate {args}", timeout=30)


def read_file(relative_path: str) -> str:
    """Read a file from the repository root. Path is relative to the repo root.
    Example: 'clusters/control-plane/flux-system/kustomization.yaml'"""
    path = REPO_ROOT / relative_path
    if not path.exists():
        return f"File not found: {relative_path}"
    try:
        content = path.read_text()
        return content[:_MAX_TOOL_OUTPUT]
    except Exception as e:
        return f"[error reading {relative_path}: {e}]"


def write_file(relative_path: str, content: str) -> str:
    """Write content to a file in the repository. Path is relative to the repo root.
    Creates parent directories if needed. Use git_commit_push after writing to apply the fix."""
    path = REPO_ROOT / relative_path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return f"Written {len(content)} bytes to {relative_path}"
    except Exception as e:
        return f"[error writing {relative_path}: {e}]"


def git_commit_push(files: str, message: str) -> str:
    """Stage files, commit, fetch+rebase from origin, then push.
    'files' is a space-separated list of relative paths from the repo root.
    Performs fetch+rebase before push to guard against concurrent changes.
    Example: files='clusters/control-plane/gitrepo.yaml', message='fix: add provider github'"""
    file_list = files.split()
    try:
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "add"] + file_list,
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "commit", "-m", message],
            check=True, capture_output=True, text=True,
        )
        # Fetch+rebase guard before push
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "fetch", "origin"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rebase", "origin/HEAD"],
            check=True, capture_output=True, text=True,
        )
        push = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "push"],
            check=True, capture_output=True, text=True, timeout=60,
        )
        return f"Committed and pushed: {message}\n{push.stdout.strip()}"
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()[:500]
        return f"[git operation failed: {e.cmd} — {stderr}]"
    except Exception as e:
        return f"[git operation failed: {e}]"


_REACT_TOOLS = [
    kubectl_get, kubectl_describe, kubectl_logs,
    kubectl_patch, kubectl_annotate,
    read_file, write_file, git_commit_push,
]

# ── command execution (for orchestrator-internal shell calls) ─────────────────
def run_command(cmd: str, timeout: int = 60) -> str:
    verb = cmd.strip().split(None, 1)[0] if cmd.strip() else "shell"
    with telemetry.span("shell", **{"shell.verb": verb}) as s:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout,
            )
            out = result.stdout.strip()
            if result.returncode != 0 and result.stderr.strip():
                out += f"\n[stderr] {result.stderr.strip()}"
            status = "ok" if result.returncode == 0 else "error"
            if s is not None:
                s.set_attribute("shell.exit_code", result.returncode)
            telemetry.record_shell(verb, status)
            return out or "(no output)"
        except subprocess.TimeoutExpired:
            telemetry.record_shell(verb, "timeout")
            return f"[timed out after {timeout}s]"
        except Exception as e:
            telemetry.record_shell(verb, "error")
            return f"[error: {e}]"

# ── cluster state collection ──────────────────────────────────────────────────
def collect_cluster_state(phase: str) -> str:
    """Run collect-cluster-state.sh and return its output for phase assessment."""
    try:
        result = subprocess.run(
            [str(COLLECT_STATE_SCRIPT), phase],
            capture_output=True, text=True, timeout=120,
        )
        state = result.stdout or "(no output)"
        if _mission_context:
            state = f"## Current Mission\n\n{_mission_context}\n\n---\n\n{state}"
        return state
    except subprocess.TimeoutExpired:
        return "[collect-cluster-state.sh timed out]"
    except Exception as e:
        return f"[error collecting state: {e}]"


def snapshot_cluster_state(phase: str) -> None:
    """Run collect-cluster-state.sh for a timestamped reference snapshot (not passed to LLM)."""
    try:
        result = subprocess.run(
            [str(COLLECT_STATE_SCRIPT), phase],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log(f"   collect-cluster-state.sh exited {result.returncode} — snapshot may be incomplete")
    except subprocess.TimeoutExpired:
        log("   collect-cluster-state.sh timed out — snapshot skipped")

# ── phase definition loading ──────────────────────────────────────────────────
def load_phase_definition(phase: str) -> dict:
    phase_file = PHASES_DIR / f"{phase}.md"
    description = phase_file.read_text() if phase_file.exists() else f"Phase: {phase}"
    return {"description": description, **PHASE_TIMING[phase]}

# ── install helpers ───────────────────────────────────────────────────────────
def get_install_status() -> str:
    if _install_proc is None:
        return "install script: not started (--skip-install mode)"
    rc = _install_proc.poll()
    if rc is None:
        return f"install script: STILL RUNNING (PID {_install_proc.pid}) — log: {_install_log_path}"
    if rc == 0:
        return f"install script: completed successfully — log: {_install_log_path}"
    return f"install script: FAILED (exit {rc}) — log: {_install_log_path}"

def run_install_background() -> bool:
    global _install_proc, _install_log_path, _install_log_fh
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    _install_log_path = RUNS_DIR / f"install-{ts}.log"
    _install_log_fh = open(_install_log_path, "w")
    with telemetry.span("install.launch", script=INSTALL_SCRIPT.name) as s:
        try:
            _install_proc = subprocess.Popen(
                [str(INSTALL_SCRIPT)],
                stdout=_install_log_fh,
                stderr=subprocess.STDOUT,
            )
        except OSError as e:
            log(f"Failed to start install script: {e}")
            _install_log_fh.close()
            telemetry.record_shell("install", "start_failed")
            return False
        if s is not None:
            try:
                s.set_attribute("install.pid", _install_proc.pid)
            except Exception:
                pass
    telemetry.record_shell("install", "started")
    log(f"Install script running in background  PID={_install_proc.pid}")
    log(f"Log: {_install_log_path}   (tail -f to follow)")
    return True

def wait_before_first_check(seconds: int) -> bool:
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

# ── known-pattern remedies ────────────────────────────────────────────────────
def is_provider_github_error(errors: list) -> bool:
    return any(PROVIDER_GITHUB_PATTERN.search(e.get("message", "")) for e in errors)

def is_stale_resource_refs_error(errors: list) -> bool:
    return any(STALE_RESOURCE_REFS_PATTERN.search(e.get("message", "")) for e in errors)

def is_stuck_dependency_error(errors: list) -> bool:
    return any(DEPENDENCY_NOT_READY_PATTERN.search(e.get("message", "")) for e in errors)


def patch_provider_github(phase: str) -> bool:
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


def clear_stale_resource_refs(phase: str) -> bool:
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
        conditions    = item.get("status", {}).get("conditions", [])
        resource_refs = item.get("spec", {}).get("resourceRefs", [])
        synced_false = any(
            c.get("type") == "Synced" and c.get("status") == "False"
            for c in conditions
        )
        if not (synced_false and resource_refs):
            continue

        xr_name      = item["metadata"]["name"]
        xr_ns        = item["metadata"].get("namespace", "")
        cluster_name = item.get("spec", {}).get("parameters", {}).get("clusterName", "")

        if cluster_name:
            log(f"   Ensuring namespace/{cluster_name} exists on {ctx}")
            run_command(
                f"kubectl create namespace {cluster_name} --context {ctx} "
                f"--dry-run=client -o yaml | kubectl apply --context {ctx} -f -"
            )

        ns_flag = f"-n {xr_ns}" if xr_ns else ""
        log(f"   Clearing stale resourceRefs on gkecluster/{xr_name} {ns_flag} on {ctx}")
        run_command(
            f"kubectl patch gkecluster {xr_name} {ns_flag} --context {ctx} "
            f"--type=merge -p '{{\"spec\":{{\"resourceRefs\":null}}}}'"
        )
        cleared = True
    return cleared


def reconcile_stuck_kustomizations(phase: str) -> bool:
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
        conditions  = item.get("status", {}).get("conditions", [])
        ready_cond  = next((c for c in conditions if c.get("type") == "Ready"), {})
        msg         = ready_cond.get("message", "")
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

# ── state ─────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"fix_attempts": {}, "restart_count": 0}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))

def _error_key(errors: list) -> str:
    def _normalise(msg: str) -> str:
        return re.sub(r"\d+", "N", msg)
    return json.dumps(sorted(_normalise(e.get("message", "")) for e in errors))

# ── logging ───────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ── mission loading ───────────────────────────────────────────────────────────
def load_mission(path: Path | None) -> str:
    for p in [path, DEFAULT_MISSION]:
        if p and p.exists():
            log(f"Mission context: {p}")
            return p.read_text()
    log("No mission.md found — agents will have no task context")
    return ""

# ── summary ───────────────────────────────────────────────────────────────────
def write_summary(state: dict, outcome: str, phase: str) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
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

# ── cleanup ───────────────────────────────────────────────────────────────────
def run_cleanup() -> None:
    log(f"Running cleanup: {CLEANUP_SCRIPT.name}")
    if _install_proc and _install_proc.poll() is None:
        log(f"  Terminating running install script (PID {_install_proc.pid}) first...")
        _install_proc.terminate()
        _install_proc.wait(timeout=10)
    subprocess.run([str(CLEANUP_SCRIPT)])

# ── phase runner ──────────────────────────────────────────────────────────────
def run_phase(phase: str) -> tuple[str, list]:
    """
    Poll a phase until healthy, timeout, or degraded.
    Returns (outcome, errors): outcome is healthy | timeout | degraded | teardown.
    Uses dspy.ChainOfThought(AssessPhaseHealth) with pre-collected cluster state.
    """
    defn     = load_phase_definition(phase)
    deadline = datetime.now() + timedelta(minutes=defn["max_wait_minutes"])
    assessor = dspy.ChainOfThought(AssessPhaseHealth)

    log(f"── Phase: {phase}")
    log(f"   Deadline: {deadline.strftime('%H:%M:%S')} ({defn['max_wait_minutes']}min window)")

    last_errors: list = []
    check_number      = 0
    phase_start       = datetime.now()

    with telemetry.span(f"phase.{phase}", phase=phase, max_wait_min=defn["max_wait_minutes"]) as phase_span:
        while datetime.now() < deadline:
            check_number += 1
            elapsed_min = int((datetime.now() - phase_start).total_seconds() / 60)

            log(f"   Collecting cluster state (check #{check_number}, {elapsed_min}min elapsed)...")
            cluster_state = collect_cluster_state(phase)

            log("   Assessing phase health...")
            started = time.monotonic()
            try:
                with telemetry.span(f"assess.{phase}", check=check_number):
                    result = assessor(
                        phase_description=defn["description"],
                        cluster_state=cluster_state,
                    )
                    verdict = result.verdict
            except Exception as e:
                log(f"   Assessment failed: {e} — waiting 60s and retrying")
                telemetry.record_llm("assess", time.monotonic() - started, "error")
                time.sleep(60)
                continue

            telemetry.record_llm("assess", time.monotonic() - started, "ok")
            log(f"   healthy={verdict.is_healthy}  recommendation={verdict.recommendation}  domain={verdict.problem_domain}")
            if verdict.analysis:
                log(f"   {verdict.analysis[:300]}")

            if phase_span is not None:
                try:
                    phase_span.set_attribute("phase.check_count", check_number)
                    phase_span.set_attribute("phase.last_recommendation", verdict.recommendation)
                    phase_span.set_attribute("phase.last_domain", verdict.problem_domain)
                except Exception:
                    pass

            if verdict.is_healthy:
                if phase_span is not None:
                    try:
                        phase_span.set_attribute("phase.outcome", "healthy")
                    except Exception:
                        pass
                return "healthy", []

            if verdict.recommendation == "teardown":
                if phase_span is not None:
                    try:
                        phase_span.set_attribute("phase.outcome", "teardown")
                    except Exception:
                        pass
                return "teardown", [{"message": r.get("error", ""), "_domain": verdict.problem_domain, **r}
                                    for r in verdict.failing_resources]

            if verdict.recommendation == "diagnose":
                errors = [{"kind": r.get("kind", ""), "name": r.get("name", ""),
                           "namespace": r.get("namespace", ""), "message": r.get("error", ""),
                           "_domain": verdict.problem_domain}
                          for r in verdict.failing_resources]
                if phase_span is not None:
                    try:
                        phase_span.set_attribute("phase.outcome", "degraded")
                    except Exception:
                        pass
                return "degraded", errors

            # recommendation == "wait"
            remaining = (deadline - datetime.now()).total_seconds()
            wait_s    = min(defn["check_interval_minutes"] * 60, remaining)
            if wait_s <= 0:
                break
            log(f"   Waiting {int(wait_s / 60)}min before next check...")
            time.sleep(wait_s)

        if phase_span is not None:
            try:
                phase_span.set_attribute("phase.outcome", "timeout")
            except Exception:
                pass
        return "timeout", last_errors

# ── diagnostics runner ────────────────────────────────────────────────────────
def handle_failure(phase: str, errors: list, state: dict) -> str:
    """
    Attempt to fix a phase failure. Returns: retry | retry_live | teardown | escalate.
    Fast-paths known patterns in Python; routes novel failures to dspy.ReAct(DiagnoseFailure).
    """
    with telemetry.span(f"diagnose.{phase}", phase=phase, error_count=len(errors)) as diag_span:
        return _handle_failure_impl(phase, errors, state, diag_span)


def _handle_failure_impl(phase: str, errors: list, state: dict, diag_span) -> str:
    error_key      = _error_key(errors)
    phase_attempts = state["fix_attempts"].setdefault(phase, {})
    attempt_count  = phase_attempts.get(error_key, 0)

    if diag_span is not None:
        try:
            diag_span.set_attribute("diagnose.attempt_count", attempt_count)
        except Exception:
            pass

    if attempt_count >= MAX_FIX_ATTEMPTS:
        log(f"   Same error seen {MAX_FIX_ATTEMPTS}× — escalating instead of looping.")
        return "escalate"

    # ── known fast-path: provider:github missing ──────────────────────────────
    if is_provider_github_error(errors):
        log("   Detected provider:github Catch-22 — patching live GitRepositories directly")
        if patch_provider_github(phase):
            phase_attempts[error_key] = attempt_count + 1
            save_state(state)
            log("   Live patch applied — waiting 30s for GitRepository to recover...")
            time.sleep(30)
            if diag_span is not None:
                try:
                    diag_span.set_attribute("diagnose.outcome", "retry_live")
                    diag_span.set_attribute("diagnose.known_pattern", "provider_github")
                except Exception:
                    pass
            return "retry_live"
        log("   No GitRepositories needed patching — falling through to ReAct agent")

    # ── known fast-path: stale resourceRefs ──────────────────────────────────
    if is_stale_resource_refs_error(errors):
        log("   Detected stale resourceRefs — clearing and ensuring namespace exists")
        if clear_stale_resource_refs(phase):
            phase_attempts[error_key] = attempt_count + 1
            save_state(state)
            log("   resourceRefs cleared — waiting 30s for Crossplane to re-reconcile...")
            time.sleep(30)
            if diag_span is not None:
                try:
                    diag_span.set_attribute("diagnose.outcome", "retry_live")
                    diag_span.set_attribute("diagnose.known_pattern", "stale_resource_refs")
                except Exception:
                    pass
            return "retry_live"
        log("   No XRs needed clearing — falling through to ReAct agent")

    # ── known fast-path: stuck dependency not ready ───────────────────────────
    if is_stuck_dependency_error(errors):
        log("   Detected stuck dependency — force-reconciling kustomizations")
        if reconcile_stuck_kustomizations(phase):
            phase_attempts[error_key] = attempt_count + 1
            save_state(state)
            log("   Reconciliation triggered — waiting 60s for kustomizations to settle...")
            time.sleep(60)
            if diag_span is not None:
                try:
                    diag_span.set_attribute("diagnose.outcome", "retry_live")
                    diag_span.set_attribute("diagnose.known_pattern", "stuck_dependency")
                except Exception:
                    pass
            return "retry_live"
        log("   No stuck kustomizations found — falling through to ReAct agent")

    # ── novel failure: route to ReAct agent ───────────────────────────────────
    domain = next((e.get("_domain", "unknown") for e in errors), "unknown")
    log(f"   Routing to DiagnoseFailure ReAct agent (domain={domain}, attempt {attempt_count + 1}/{MAX_FIX_ATTEMPTS})...")

    if diag_span is not None:
        try:
            diag_span.set_attribute("diagnose.domain", domain)
        except Exception:
            pass

    diagnoser = dspy.ReAct(DiagnoseFailure, tools=_REACT_TOOLS, max_iters=20)

    initial_context = (
        f"Phase: {phase}\n"
        f"Domain: {domain}\n"
        f"Fix attempts so far: {attempt_count}/{MAX_FIX_ATTEMPTS}\n"
        f"Repo root: {REPO_ROOT}\n\n"
        f"Available cluster contexts:\n"
        f"  kind:          kind-kind-test-cluster\n"
        f"  control-plane: run kubectl_get('config get-contexts -o name') to find it\n"
        f"  apps-dev:      run kubectl_get('config get-contexts -o name') to find it\n"
    )
    if _mission_context:
        initial_context = f"## Current Mission\n\n{_mission_context}\n\n---\n\n{initial_context}"

    started = time.monotonic()
    try:
        with telemetry.span(f"diagnose.react.{phase}", phase=phase, domain=domain):
            result = diagnoser(
                phase_name=phase,
                errors=json.dumps(errors, indent=2),
                cluster_state=initial_context,
            )
            decision = result.decision
    except Exception as e:
        log(f"   DiagnoseFailure agent failed: {e} — escalating")
        telemetry.record_llm("diagnose", time.monotonic() - started, "error")
        return "escalate"

    telemetry.record_llm("diagnose", time.monotonic() - started, "ok")
    log(f"   decision={decision.action}  confidence={decision.confidence:.2f}")
    log(f"   {decision.rationale[:300]}")

    if diag_span is not None:
        try:
            diag_span.set_attribute("diagnose.action", decision.action)
            diag_span.set_attribute("diagnose.confidence", decision.confidence)
        except Exception:
            pass

    if decision.action == "retry":
        phase_attempts[error_key] = attempt_count + 1
        save_state(state)
        if diag_span is not None:
            try:
                diag_span.set_attribute("diagnose.outcome", "retry")
            except Exception:
                pass
        return "retry"

    if decision.action == "teardown":
        if diag_span is not None:
            try:
                diag_span.set_attribute("diagnose.outcome", "teardown")
            except Exception:
                pass
        return "teardown"

    if diag_span is not None:
        try:
            diag_span.set_attribute("diagnose.outcome", "escalate")
        except Exception:
            pass
    return "escalate"

# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster provisioning orchestrator")
    parser.add_argument("--skip-install", action="store_true",
                        help="Skip running the install script")
    parser.add_argument("--start-phase", choices=PHASES, default="bootstrap",
                        help="Start from a specific phase (default: bootstrap)")
    parser.add_argument("--mission", type=Path, default=None,
                        help="Path to mission context file (default: orchestrator/mission.md)")
    parser.add_argument("--initial-wait", type=int, default=300, metavar="SECONDS",
                        help="Seconds to wait after starting install before first check (default: 300)")
    args = parser.parse_args()

    state = load_state()

    global _interrupt_state, _interrupt_phase, _mission_context
    _mission_context = load_mission(args.mission)
    _interrupt_state = state
    _interrupt_phase = args.start_phase
    signal.signal(signal.SIGINT, _on_sigint)

    otel_ok, otel_reason = telemetry.setup_otel()
    if otel_ok:
        log(f"  OTEL         : enabled ({otel_reason})")
    else:
        log(f"  OTEL         : disabled ({otel_reason})")

    log("  Initializing LLM...")
    try:
        lm = get_lm()
        log(f"  LLM          : {lm.model}")
    except Exception as e:
        log(f"  LLM init failed: {e}")
        sys.exit(1)

    log("══════════════════════════════════════════════")
    log("  Cluster Provisioning Orchestrator")
    log(f"  Start phase  : {args.start_phase}")
    log(f"  Skip install : {args.skip_install}")
    log(f"  Initial wait : {args.initial_wait}s")
    log("══════════════════════════════════════════════")

    with telemetry.span("orchestrator.run",
                        start_phase=args.start_phase,
                        skip_install=args.skip_install) as root_span:
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
                snapshot_cluster_state(phase)
                phase_index += 1
                continue

            if outcome == "teardown":
                snapshot_cluster_state(phase)
                run_cleanup()
                write_summary(state, "TEARDOWN", phase)
                sys.exit(1)

            # degraded or timeout — run diagnostics
            if not errors:
                errors = [{"resource": "unknown", "kind": "unknown",
                           "message": f"phase '{phase}' result: {outcome}"}]

            snapshot_cluster_state(phase)
            action = handle_failure(phase, errors, state)

            if action in ("retry", "retry_live"):
                wait_s = 120 if action == "retry" else 120
                log(f"Fix applied — waiting {wait_s // 60}min for cluster to settle...")
                time.sleep(wait_s)
                continue

            if action == "teardown":
                log("Diagnostics recommends teardown. Running cleanup...")
                run_cleanup()
                state["restart_count"] = state.get("restart_count", 0) + 1
                state["fix_attempts"]  = {}
                save_state(state)

                if state["restart_count"] >= 2:
                    log("Already restarted twice — escalating.")
                    write_summary(state, "ESCALATED", phase)
                    sys.exit(1)

                if not run_install_background():
                    log("Re-install failed.")
                    write_summary(state, "FAILED", phase)
                    sys.exit(1)

                phase_index = 0
                continue

            # escalate
            write_summary(state, "ESCALATED", phase)
            log(f"Escalation at phase '{phase}'. Manual intervention required.")
            sys.exit(1)

        log("══════════════════════════════════════════════")
        log("  ALL PHASES HEALTHY")
        log("══════════════════════════════════════════════")
        write_summary(state, "SUCCESS", "all")
        if root_span is not None:
            try:
                root_span.set_attribute("orchestrator.outcome", "success")
            except Exception:
                pass

    try:
        telemetry.shutdown()
    except Exception:
        pass


if __name__ == "__main__":
    main()
