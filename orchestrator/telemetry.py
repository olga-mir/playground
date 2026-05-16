"""
telemetry.py — OTEL wiring for the orchestrator, direct to GCP (no collector).

Three surfaces are observed:

1. The orchestrator's own Python (phases, subprocess calls, agent invocations)
   → exported via opentelemetry-exporter-gcp-trace and -monitoring, authenticating
   through Application Default Credentials (ADC).

2. The install script + all kubectl/shell calls — wrapped as Python-side spans
   around `subprocess.run` / `subprocess.Popen`.

3. The Claude Code CLI (`claude -p`) — the CLI only speaks OTLP, so we hand it a
   short-lived gcloud access token and point it at the GCP OTLP endpoint
   (telemetry.googleapis.com). Token is fetched per-invocation.

Design principles:
- Never crash the orchestrator due to OTEL. If setup fails (missing deps,
  no ADC, no PROJECT_ID, quota errors), fall back to no-op tracers/meters.
- Small, readable surface: three counters/histograms + a `span()` context
  manager + `claude_cli_otel_env()` for subprocess env injection.
- One shared Resource: `service.name=playground-orchestrator`, `service.instance.id=<host>-<pid>`,
  `service.namespace=playground`. This triggers the generic_task monitored resource type in GCM
  (vs generic_node with empty node_id), which surfaces service.name correctly in Cloud Trace
  and isolates each run's metric time series to avoid "points written too frequently" errors.
"""
import logging
import os
import socket
import subprocess
from contextlib import contextmanager
from typing import Iterator

log = logging.getLogger("orchestrator.telemetry")

try:
    from opentelemetry import trace, metrics, propagate
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.metrics.view import View, DropAggregation
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    from opentelemetry.exporter.cloud_monitoring import CloudMonitoringMetricsExporter
    _OTEL_AVAILABLE = True
    _IMPORT_ERR: Exception | None = None
except Exception as e:  # pragma: no cover — missing deps path
    _OTEL_AVAILABLE = False
    _IMPORT_ERR = e

SERVICE_NAME = "playground-orchestrator"

# ── module-level state populated by setup_otel() ──────────────────────────────
_tracer = None
_meter = None
_m_claude_invocations = None
_m_claude_duration = None
_m_shell_calls = None
_enabled = False
_project_id: str | None = None


def setup_otel(project_id: str | None = None) -> tuple[bool, str]:
    """Configure tracer + meter providers with GCP exporters.

    Returns (ok, reason). On failure, the module stays in no-op mode and the
    caller can log the reason. Never raises.
    """
    global _tracer, _meter, _enabled, _project_id
    global _m_claude_invocations, _m_claude_duration, _m_shell_calls

    if not _OTEL_AVAILABLE:
        return False, f"opentelemetry deps not installed: {_IMPORT_ERR!r}"

    project_id = project_id or os.environ.get("PROJECT_ID")
    if not project_id:
        return False, "PROJECT_ID is not set — skipping OTEL setup"

    try:
        # service.instance.id triggers the generic_task monitored resource type in GCM
        # (instead of generic_node with empty node_id). This surfaces service.name correctly
        # in Cloud Trace and gives each run its own time series so rapid restarts don't
        # produce "points written too frequently" errors.
        # Include a startup timestamp so OS PID reuse across days doesn't collide.
        import time as _time
        resource = Resource.create({
            "service.name": SERVICE_NAME,
            "service.namespace": "playground",
            "service.instance.id": f"{socket.gethostname()}-{os.getpid()}-{int(_time.time())}",
            "gcp.project_id": project_id,
        })

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter(project_id=project_id))
        )
        trace.set_tracer_provider(tracer_provider)

        # 60s is good for GCM, but we ensure it's explicit.
        metric_reader = PeriodicExportingMetricReader(
            CloudMonitoringMetricsExporter(project_id=project_id),
            export_interval_millis=60_000,
        )
        # Drop otel.sdk.* internal self-observability metrics: they're written at sub-second
        # granularity and are the root cause of the "points written too frequently" error
        # from Cloud Monitoring when the shutdown flush fires close to the last scheduled export.
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[metric_reader],
            views=[View(instrument_name="otel.sdk.*", aggregation=DropAggregation())],
        )
        metrics.set_meter_provider(meter_provider)
    except Exception as e:
        return False, f"OTEL provider setup failed: {e!r}"

    _tracer = trace.get_tracer(SERVICE_NAME)
    _meter = metrics.get_meter(SERVICE_NAME)
    _m_claude_invocations = _meter.create_counter(
        "orchestrator.claude.invocations",
        description="Total claude -p subprocess invocations",
        unit="1",
    )
    _m_claude_duration = _meter.create_histogram(
        "orchestrator.claude.duration",
        description="claude -p invocation wall-clock duration",
        unit="s",
    )
    _m_shell_calls = _meter.create_counter(
        "orchestrator.shell.calls",
        description="Total shell/kubectl/gcloud subprocess calls",
        unit="1",
    )
    _enabled = True
    _project_id = project_id
    return True, f"OTEL configured for project={project_id}"


def is_enabled() -> bool:
    return _enabled


@contextmanager
def span(name: str, **attrs) -> Iterator[object]:
    """Span context manager — no-op if OTEL isn't set up.

    Usage:
        with telemetry.span("phase.bootstrap", phase="bootstrap") as s:
            ...
            if s is not None:
                s.set_attribute("check.number", n)
    """
    if not _enabled or _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name, attributes=attrs) as s:
        try:
            yield s
        except Exception as e:
            # Record exception but re-raise — caller controls flow.
            try:
                s.record_exception(e)
                from opentelemetry.trace import Status, StatusCode
                s.set_status(Status(StatusCode.ERROR, str(e)[:200]))
            except Exception:
                pass
            raise


def record_claude(agent_name: str, duration_s: float, status: str) -> None:
    if not _enabled:
        return
    labels = {"agent": agent_name, "status": status}
    _m_claude_invocations.add(1, labels)
    _m_claude_duration.record(duration_s, labels)


def record_shell(kind: str, status: str) -> None:
    if not _enabled:
        return
    _m_shell_calls.add(1, {"kind": kind, "status": status})


def claude_cli_otel_env(agent_name: str, phase: str) -> dict[str, str]:
    """Env vars to make Claude Code CLI export its own telemetry to GCP.

    Claude Code speaks OTLP; it can't use the GCP-native exporters. We point it
    at https://telemetry.googleapis.com with a fresh gcloud access token. Tokens
    are ~1h; we refresh per invocation since `claude -p` is short-lived.

    Returns {} if OTEL is disabled, PROJECT_ID is missing, or gcloud isn't
    available — in which case only the orchestrator side records the invocation.
    """
    if not _enabled or not _project_id:
        return {}

    try:
        token = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except Exception as e:
        log.debug("gcloud access token fetch failed: %r — CLI OTEL disabled", e)
        return {}
    if not token:
        return {}

    endpoint = "https://telemetry.googleapis.com"
    headers = f"Authorization=Bearer {token},x-goog-user-project={_project_id}"

    # We use a specific service name for Claude to distinguish it from orchestrator
    # while keeping it in the same namespace.
    claude_service_name = f"claude-{agent_name}"

    resource_attrs = (
        f"service.name={claude_service_name},"
        f"service.namespace=playground,"
        f"orchestrator.agent={agent_name},"
        f"orchestrator.phase={phase},"
        f"gcp.project_id={_project_id}"
    )
    env = {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_SERVICE_NAME": claude_service_name,
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_EXPORTER_OTLP_HEADERS": headers,
        "OTEL_RESOURCE_ATTRIBUTES": resource_attrs,
    }

    # Inject standard W3C Trace Context (traceparent, tracestate) into env.
    # The default propagator is W3C, which populates the carrier with
    # lowercase 'traceparent'/'tracestate'. Standard OTEL SDKs (including Node)
    # read these from the environment as uppercase TRACEPARENT/TRACESTATE.
    carrier = {}
    propagate.inject(carrier)
    if "traceparent" in carrier:
        env["TRACEPARENT"] = carrier["traceparent"]
    if "tracestate" in carrier:
        env["TRACESTATE"] = carrier["tracestate"]

    return env



def shutdown() -> None:
    """Flush pending spans/metrics. Called at normal exit.

    BatchSpanProcessor and PeriodicExportingMetricReader flush on process exit
    via atexit hooks, but calling explicitly is cleaner and catches any errors.
    """
    if not _enabled:
        return
    try:
        tp = trace.get_tracer_provider()
        if hasattr(tp, "shutdown"):
            tp.shutdown()
    except Exception:
        pass
    try:
        mp = metrics.get_meter_provider()
        if hasattr(mp, "shutdown"):
            mp.shutdown()
    except Exception:
        pass
