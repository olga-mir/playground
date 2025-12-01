# Running Chaos Experiments with Litmus

This guide explains how to run chaos engineering experiments using LitmusChaos in the apps-dev cluster.

## Prerequisites

- LitmusChaos installed (via `litmus-core` Helm chart)
- ChaosEngine CRD available
- Access to the apps-dev GKE cluster

## Available Chaos Experiments

The cluster currently has the following pre-configured chaos experiment:

### Aggressive Pod Delete

**Location**: `kubernetes/namespaces/base/litmus/experiments/aggressive-pod-delete-experiment.yaml`

**What it does**: Aggressively kills pods to test application resilience, auto-scaling, and recovery capabilities.

**Current Configuration**:
- **Duration**: 5 minutes (300 seconds)
- **Interval**: Kill pods every 10 seconds
- **Percentage**: Kill 50% of matching pods each interval
- **Force**: True (immediate kill, no grace period)
- **Sequence**: Parallel (kill all selected pods at once)

## Running a Chaos Experiment

### Step 1: Choose Your Target Application

List available deployments to choose a chaos target:

```bash
kubectl --context $CONTEXT get deployments -A
```

Good targets for testing:
- `team-alpha/whereami` - Demo application (safe for testing)
- `team-bravo/fortio-echo` - Echo server (safe for testing)
- `kagent-system/*-agent` - AI agent deployments (test agent resilience)

### Step 2: Configure the Chaos Experiment

You have two options:

#### Option A: Edit Directly

```bash
kubectl --context $CONTEXT edit chaosengine aggressive-pod-delete -n litmus
```

Change these fields:
```yaml
spec:
  engineState: "active"  # Change from "stop" to "active"

  appinfo:
    appns: "team-alpha"           # Target namespace
    applabel: "app=whereami"      # Target label selector
    appkind: "deployment"         # Resource type
```

#### Option B: Patch with kubectl (Recommended)

**Target whereami application:**
```bash
kubectl --context $CONTEXT patch chaosengine aggressive-pod-delete -n litmus --type=merge -p '
{
  "spec": {
    "engineState": "active",
    "appinfo": {
      "appns": "team-alpha",
      "applabel": "app=whereami",
      "appkind": "deployment"
    }
  }
}'
```

**Target kagent helm-agent:**
```bash
kubectl --context $CONTEXT patch chaosengine aggressive-pod-delete -n litmus --type=merge -p '
{
  "spec": {
    "engineState": "active",
    "appinfo": {
      "appns": "kagent-system",
      "applabel": "app.kubernetes.io/name=helm-agent",
      "appkind": "deployment"
    }
  }
}'
```

### Step 3: Monitor the Chaos Experiment

#### Watch Target Pods Being Deleted and Recreated

```bash
# Replace "team-alpha" with your target namespace
kubectl --context $CONTEXT get pods -n team-alpha -w
```

#### Check Chaos Engine Status

```bash
kubectl --context $CONTEXT get chaosengine -n litmus
```

Expected output when active:
```
NAME                    AGE
aggressive-pod-delete   30m
```

#### View Chaos Results

```bash
kubectl --context $CONTEXT get chaosresult -n litmus
```

Results show:
- Verdict: Pass/Fail
- Probe success percentage
- Experiment phase

#### Check Chaos Experiment Pods

```bash
kubectl --context $CONTEXT get pods -n litmus
```

You should see experiment runner pods created.

#### View Experiment Logs

```bash
kubectl --context $CONTEXT logs -n litmus -l app.kubernetes.io/component=experiment-job -f
```

#### Describe ChaosEngine for Detailed Status

```bash
kubectl --context $CONTEXT describe chaosengine aggressive-pod-delete -n litmus
```

### Step 4: Stop the Chaos Experiment

When finished testing:

```bash
kubectl --context $CONTEXT patch chaosengine aggressive-pod-delete -n litmus --type=merge -p '{"spec":{"engineState":"stop"}}'
```

Verify it stopped:
```bash
kubectl --context $CONTEXT get chaosengine aggressive-pod-delete -n litmus -o jsonpath='{.spec.engineState}'
```

Should output: `stop`

## Customizing Chaos Parameters

### Making the Experiment Less Aggressive

To create a gentler chaos experiment, you can adjust these parameters:

```yaml
experiments:
  - name: pod-delete
    spec:
      components:
        env:
          # Graceful deletion (respect termination grace period)
          - name: FORCE
            value: "false"

          # Shorter duration (2 minutes)
          - name: TOTAL_CHAOS_DURATION
            value: "120"

          # Kill pods every 30 seconds (less frequent)
          - name: CHAOS_INTERVAL
            value: "30"

          # Affect only 25% of matching pods
          - name: PODS_AFFECTED_PERC
            value: "25"
```

### Common Environment Variables

| Variable | Description | Default | Example Values |
|----------|-------------|---------|----------------|
| `FORCE` | Force kill without grace period | `"true"` | `"true"`, `"false"` |
| `TOTAL_CHAOS_DURATION` | Total experiment duration (seconds) | `"300"` | `"60"`, `"120"`, `"300"` |
| `CHAOS_INTERVAL` | Time between pod kills (seconds) | `"10"` | `"5"`, `"10"`, `"30"` |
| `PODS_AFFECTED_PERC` | Percentage of pods to kill | `"50"` | `"25"`, `"50"`, `"100"` |
| `RANDOMNESS` | Randomize pod selection | `"true"` | `"true"`, `"false"` |
| `SEQUENCE` | Kill sequence | `"parallel"` | `"parallel"`, `"serial"` |
| `TARGET_PODS` | Specific pod names (comma-separated) | `""` | `"pod-1,pod-2"` |

## Example Scenarios

### Scenario 1: Test Application Recovery

**Goal**: Verify applications restart correctly after pod deletion

```bash
# Start the experiment
kubectl --context $CONTEXT patch chaosengine aggressive-pod-delete -n litmus --type=merge -p '
{
  "spec": {
    "engineState": "active",
    "appinfo": {
      "appns": "team-alpha",
      "applabel": "app=whereami",
      "appkind": "deployment"
    }
  }
}'

# Watch pods recover
kubectl --context $CONTEXT get pods -n team-alpha -w

# Check application is still serving traffic
# (Add your application health check here)
```

### Scenario 2: Test Agent Resilience

**Goal**: Verify kagent agents can handle pod disruptions

```bash
# Target specific agent
kubectl --context $CONTEXT patch chaosengine aggressive-pod-delete -n litmus --type=merge -p '
{
  "spec": {
    "engineState": "active",
    "appinfo": {
      "appns": "kagent-system",
      "applabel": "app.kubernetes.io/name=k8s-agent",
      "appkind": "deployment"
    }
  }
}'

# Monitor agent behavior
kubectl --context $CONTEXT get pods -n kagent-system -l app.kubernetes.io/name=k8s-agent -w
```

## Troubleshooting

### Chaos Experiment Not Starting

Check ChaosEngine status:
```bash
kubectl --context $CONTEXT describe chaosengine aggressive-pod-delete -n litmus
```

Common issues:
- ServiceAccount `pod-delete-sa` doesn't exist or lacks permissions
- Target application label selector doesn't match any pods
- Namespace doesn't exist

### No Pods Being Deleted

Verify label selector matches target pods:
```bash
kubectl --context $CONTEXT get pods -n <target-namespace> -l <your-label-selector>
```

### Checking ServiceAccount Permissions

```bash
kubectl --context $CONTEXT get serviceaccount pod-delete-sa -n litmus
kubectl --context $CONTEXT get clusterrole,clusterrolebinding -l name=pod-delete-sa
```

## Safety Best Practices

1. **Start Small**: Begin with non-critical applications (demo apps like whereami)
2. **Test in Non-Production**: Always test chaos experiments in dev/staging first
3. **Monitor Closely**: Watch experiment execution in real-time
4. **Set Alerts**: Configure alerts for pod deletion events
5. **Document Results**: Record observations and application behavior
6. **Gradual Increase**: Start with gentle parameters, increase aggressiveness gradually
7. **Business Hours**: Run experiments during working hours when teams can respond
8. **Communication**: Notify team members before running experiments

## Cleaning Up

### Delete Chaos Results

```bash
kubectl --context $CONTEXT delete chaosresult --all -n litmus
```

### Reset Chaos Engine to Stopped State

```bash
kubectl --context $CONTEXT patch chaosengine aggressive-pod-delete -n litmus --type=merge -p '{"spec":{"engineState":"stop"}}'
```

## Next Steps

- **Create Custom Experiments**: Define new ChaosEngine resources for different scenarios
- **Add Probes**: Configure health probes to automatically determine experiment success/failure
- **Automate**: Integrate chaos experiments into CI/CD pipelines
- **Advanced Scenarios**: Explore network chaos, CPU/memory stress, disk fill experiments

## References

- [LitmusChaos Documentation](https://docs.litmuschaos.io/)
- [Pod Delete Experiment Documentation](https://litmuschaos.github.io/litmus/experiments/categories/pods/pod-delete/)
- [ChaosEngine Specification](https://docs.litmuschaos.io/docs/concepts/chaos-workflow)
