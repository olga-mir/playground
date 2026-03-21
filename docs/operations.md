# Operations

Operational reference for a running fleet — diagnostics, load testing, and performance experiments.

## Fleet health

```bash
# Check all clusters
bootstrap/scripts/check-fleet-health.sh

# Check a single cluster by short name
bootstrap/scripts/check-fleet-health.sh apps-dev
```

## Key task commands

```bash
# Full deploy: install + all phases
task orchestrate:run

# Check current state without install
task orchestrate:check

# Resume from a specific phase
task orchestrate:resume PHASE=control

# Validate all
task validate:all

# Tear everything down (clusters only — not project, WIF, IAM)
task setup:cleanup
```

All available commands: `task --list`

## Diagnostics

```bash
# Test whereami (team-alpha)
kubectl exec -n team-platform deploy/fortio-diagnostic -- \
  fortio load -c 10 -qps 100 -t 30s http://whereami.team-alpha/

# Test fortio-echo (team-bravo)
kubectl exec -n team-platform deploy/fortio-diagnostic -- \
  fortio load -c 10 -qps 100 -t 30s http://fortio-echo.team-bravo/

# High load test
kubectl exec -n team-platform deploy/fortio-diagnostic -- \
  fortio load -c 50 -qps 1000 -t 60s http://whereami.team-alpha/
```

## Performance experimentation

Tenant application source: <https://github.com/olga-mir/playground-sre>

```bash
# Baseline — sleep 50ms, 10 concurrent connections, 30s
kubectl exec -n team-bravo deploy/fortio-echo -- \
  fortio load -c 10 -qps 100 -t 30s \
  'http://perf-lab.sre.svc.cluster.local/v1/scenarios/sleep?duration=50ms'

# CPU — 2 goroutines, 1s per request, 4 concurrent
kubectl exec -n team-bravo deploy/fortio-echo -- \
  fortio load -c 4 -qps 0 -t 30s \
  'http://perf-lab.sre.svc.cluster.local/v1/scenarios/cpu?duration=1s&goroutines=2'

# Fanout — 50 workers, watch goroutine scheduling overhead
kubectl exec -n team-bravo deploy/fortio-echo -- \
  fortio load -c 5 -qps 2 -t 30s \
  'http://perf-lab.sre.svc.cluster.local/v1/scenarios/fanout?workers=50&task_duration=200ms'
```
