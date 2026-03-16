# Orchestrator

Automated provisioning pipeline for the three-cluster fleet. Runs the install script then drives the provisioning through three phases, using Claude agents via the Anthropic SDK to assess cluster health and diagnose failures.

## How it works

```
task orchestrate:run
        │
        ├─ bootstrap/bootstrap-control-plane-cluster.sh
        │
        └─ phase loop:
             ├─ collect kubectl state (subprocess)
             ├─ Claude API → phase-checker agent → JSON verdict
             │    • healthy  → advance to next phase
             │    • wait     → sleep, re-check
             │    • diagnose → call diagnostics agent
             │    • teardown → cleanup, exit
             └─ Claude API → diagnostics agent → JSON decision
                  • fix_forward → run fix commands, retry phase
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
- `ANTHROPIC_API_KEY` set in environment
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

State and run summaries are written to `orchestrator/runs/` (gitignored):

```
orchestrator/runs/
├── state.json                        # persisted fix attempt counts and restart count
└── run-success-2026-03-16_143021.md  # summary written at end of each run
```

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

## File layout

```
orchestrator/
├── main.py          # Orchestrator script
└── pyproject.toml   # Python dependencies (anthropic SDK)

.claude/agents/
├── phase-checker.md  # Phase assessment agent prompt
└── diagnostics.md    # Failure diagnostics agent prompt

tasks/
└── orchestrate.yaml  # Task definitions
```
