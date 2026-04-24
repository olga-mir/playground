# Observability Setup: GCP & Grafana Integration

This document summarizes the setup and findings from the session on April 21, 2026, regarding connecting this project's telemetry and the Gemini CLI to a Grafana monitoring stack via Google Cloud.

## Achievements

1.  **Direct GCP-Grafana Connection**: Established a secure connection using a GCP Service Account with specific "Viewer" roles for Monitoring, Logging, and Trace.
2.  **Telemetry Mapping**: Mapped the two primary sources of telemetry in the project:
    *   **Orchestrator Metrics**: Python-based telemetry (phases, shell calls) appears under the **Workload** resource type.
    *   **Gemini CLI Metrics**: OTLP-based telemetry (tokens, model latency) appears under the **Custom** or **Global** resource types.
3.  **Metrics Discovery Tool**: Created `scripts/dump-metrics.sh`, a robust utility to fetch all available metric descriptors and their associated labels directly from the Cloud Monitoring API.
4.  **Data Verification**: Confirmed active data flow for critical signals including token usage, API latency, and tool execution counts.

## Key Technical Findings

### Resource Type Context
Telemetry sent from a local machine via OpenTelemetry (OTLP) does not automatically inherit a "Compute Engine" or "GKE" resource type. In Grafana's Google Cloud Data Source:
*   Switch the **Service** dropdown to **Global** or **Custom** to see Gemini CLI metrics.
*   Use the **Workload** service type to see Orchestrator/Claude metrics.

### gcloud vs. REST API
The `gcloud monitoring` command group is inconsistent across CLI versions (often requiring `alpha` or `beta` components). For programmatic discovery of metrics and labels, calling the Monitoring REST API directly with a `gcloud auth print-access-token` is more reliable.

## Operational Guide

### Useful Metrics for Dashboards
| Metric Name | Primary Labels | Use Case |
| :--- | :--- | :--- |
| `gemini_cli.token.usage` | `model`, `type`, `session_id` | Cost and usage tracking |
| `gemini_cli.api.request.latency` | `model`, `session_id` | Performance monitoring |
| `orchestrator.shell.calls` | `kind`, `status` | Troubleshooting bootstrap failures |
| `gemini_cli.tool.call.count` | `function_name`, `success` | Agent reliability analysis |

### Common Gotchas & Errors to Avoid

*   **Interactive Prompts**: Never run `gcloud` commands that require `(Y/n)` confirmations in an agent session. Always use `--quiet` or automated scripts.
*   **Trace Data Sources**: In Grafana Cloud, the "Traces" tab is often hard-coded to Tempo. Use the **Explore** view to manually select the **Google Cloud Trace** data source.
*   **API Prerequisites**: Ensure the following APIs are enabled in GCP:
    *   `monitoring.googleapis.com`
    *   `logging.googleapis.com`
    *   `cloudtrace.googleapis.com`
    *   `cloudresourcemanager.googleapis.com` (Required for Grafana to list projects)
*   **IAM Propagation**: IAM role changes (like `Service Account Token Creator`) can take up to 90 seconds to propagate. Wait before re-testing a failed connection.

## Artifacts Created
*   `scripts/dump-metrics.sh`: Tool to dump GCP metric descriptors.
*   `metrics_dump.json`: Raw data containing all labels and metric types for the project.
