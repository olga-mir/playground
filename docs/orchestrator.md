# Orchestrator

Automated provisioning pipeline for the three-cluster fleet. Runs the install script then drives the provisioning through three phases, using Claude agents via the Anthropic SDK to assess cluster health and diagnose failures.

## How it works

```
task orchestrate:run
        │
        ├─ bootstrap/bootstrap-control-plane-cluster.sh  (background)
        │
        └─ phase loop:
             ├─ collect kubectl state (subprocess)
             ├─ Claude API → phase-checker agent → JSON verdict
             │    • healthy  → save snapshot → advance to next phase
             │    • wait     → sleep, re-check
             │    • diagnose → save snapshot → call diagnostics agent
             │    • teardown → save snapshot → cleanup, exit
             └─ Claude API → diagnostics agent → JSON decision
                  • fix_forward → agent: git add/commit/push (hook: rebase before push) → wait for Flux → retry phase
                  • teardown    → cleanup + restart from scratch (max 2×)
                  • escalate    → write summary, exit
```

Phases run in order:

| Phase | What it checks | Window |
|---|---|---|
| `bootstrap` | kind cluster: Crossplane providers + Flux Kustomizations healthy | 20 min, check every 3 min |
| `control` | GKE control-plane: Crossplane XR ready + Flux bootstrapped | 70 min, check every 10 min |
| `workload` | GKE apps-dev: Crossplane XR ready + Flux bootstrapped | 70 min, check every 10 min |

## Prerequisites

- `uv` installed (`brew install uv`)
- Claude Code (`claude` CLI) installed and authenticated — agent calls run via `claude -p`, which uses your Claude subscription (no separate API billing)
- All other env vars from `.setup-env` sourced (same as `setup:deploy`)

## Usage

```bash
# Full run: install + all phases
task orchestrate:run

# Skip install, check current state from bootstrap
task orchestrate:check

# Resume from a specific phase (install already done, cluster exists)
task orchestrate:resume PHASE=control

# Sync Python dependencies only
task orchestrate:sync
```

Or run directly from the `orchestrator/` directory:

```bash
cd orchestrator
uv run python main.py --start-phase control --skip-install
```

## State and run output

State, snapshots, and run summaries are written to `orchestrator/runs/` (gitignored):

```
orchestrator/runs/
├── state.json                                    # persisted fix attempt counts and restart count
├── run-success-2026-03-16_143021.md              # summary written at end of each run
├── snapshot-bootstrap-healthy-<ts>.txt           # fleet state at phase transition
├── snapshot-control-pre-diagnostics-<ts>.txt     # fleet state captured before diagnostics agent runs
└── install-<ts>.log                              # bootstrap-control-plane-cluster.sh output
```

Snapshots are captured at three points in the loop:
- **`<phase>-healthy`** — immediately after a phase passes; records the good state before advancing
- **`<phase>-pre-diagnostics`** — before handing off to the diagnostics agent; gives it concrete Flux resource state to reason from
- **`<phase>-teardown`** — before cleanup runs; useful for post-mortem

Snapshot content comes from `bootstrap/scripts/check-fleet-health.sh` (ANSI colours stripped).

State tracks:
- `fix_attempts` — per-phase, per-error-signature count (drives the 3× escalation limit)
- `restart_count` — how many full teardown+reinstall cycles have run

Reset state between runs: `rm orchestrator/runs/state.json`

## Escalation and the 3× limit

Each error is fingerprinted by its message strings. If the diagnostics agent recommends `fix_forward` and the same error returns after the fix, the attempt counter increments. At 3 identical errors the orchestrator stops retrying and writes an escalation summary to the repo root (`orchestrator-escalated-<timestamp>.md`).

Similarly, if teardown is recommended the orchestrator runs cleanup and re-installs from scratch. After 2 full restart cycles without resolution, it escalates rather than looping.

## Agent prompts

The two agents used by the orchestrator are defined in `.claude/agents/` and double as Claude Code sub-agents for interactive use:

- `.claude/agents/phase-checker.md` — evaluates cluster state against healthy criteria; returns a structured verdict
- `.claude/agents/diagnostics.md` — investigates failures, decides fix-forward or teardown, produces exact fix commands

## GitOps safety guardrails

The orchestrator enforces GitOps discipline via `.claude/hooks/guardrails.sh` (a Claude Code `PreToolUse` hook):

- **No direct kubectl writes** — `apply`, `delete`, `patch`, etc. are blocked; all cluster changes must go through git → Flux
- **Develop-only pushes** — `git push` is only allowed to `develop` or `chore/*` branches
- **Rebase before push** — any `git push` attempt automatically fetches and rebases onto `origin/develop` first, ensuring a linear history without requiring the agent to manage pull/rebase itself

The diagnostics agent handles its own git operations (add, commit, push). The Python orchestrator contains no git code — that complexity lives in the hook and the agent.

## File layout

```
orchestrator/
├── main.py          # Orchestrator script
├── mission.md       # Current mission context (loaded into every agent call)
└── pyproject.toml   # Python dependencies

.claude/agents/
├── phase-checker.md  # Phase assessment agent prompt
└── diagnostics.md    # Failure diagnostics agent prompt

.claude/hooks/
└── guardrails.sh     # PreToolUse hook: blocks kubectl writes, enforces git discipline

tasks/
└── orchestrate.yaml  # Task definitions
```
