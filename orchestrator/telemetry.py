"""
telemetry.py — OTEL wiring for the orchestrator, direct to GCP (no collector).

Three surfaces are observed:

1. The orchestrator's own Python (phases, DSPy/LiteLLM calls, shell calls)
   → exported via opentelemetry-exporter-gcp-trace and -monitoring, authenticating
   through Application Default Credentials (ADC).

2. Shell calls (kubectl, gcloud, git) — wrapped as Python-side spans
   around subprocess.run calls in main.py.

3. DSPy/LiteLLM invocations — tracked via record_llm() per module call.

Design principles:
- Never crash the orchestrator due to OTEL. If setup fails (missing deps,
  no ADC, no PROJECT_ID, quota errors), fall back to no-op tracers/meters.
- Small surface: counters/histograms + a span() context manager.
- One shared Resource: service.name=playground-orchestrator with
  service.instance.id=<host>-<pid>, which triggers the generic_task monitored
  resource type in GCM and avoids "points written too frequently" errors.
"""
import logging
import os
import socket
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
except Exception as e:
    _OTEL_AVAILABLE = False
    _IMPORT_ERR = e

SERVICE_NAME = "playground-orchestrator"

_tracer = None
_meter  = None
_m_llm_invocations  = None
_m_llm_duration     = None
_m_shell_calls      = None
_enabled    = False
_project_id: str | None = None


def setup_otel(project_id: str | None = None) -> tuple[bool, str]:
    """Configure tracer + meter providers with GCP exporters.

    Returns (ok, reason). On failure, the module stays in no-op mode.
    Never raises.
    """
    global _tracer, _meter, _enabled, _project_id
    global _m_llm_invocations, _m_llm_duration, _m_shell_calls

    if not _OTEL_AVAILABLE:
        return False, f"opentelemetry deps not installed: {_IMPORT_ERR!r}"

    project_id = project_id or os.environ.get("PROJECT_ID")
    if not project_id:
        return False, "PROJECT_ID is not set — skipping OTEL setup"

    try:
        resource = Resource.create({
            "service.name": SERVICE_NAME,
            "service.namespace": "playground",
            # instance.id triggers generic_task in GCM; each run gets its own
            # time series, preventing "points written too frequently" errors.
            "service.instance.id": f"{socket.gethostname()}-{os.getpid()}",
            "gcp.project_id": project_id,
        })

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter(project_id=project_id))
        )
        trace.set_tracer_provider(tracer_provider)

        metric_reader = PeriodicExportingMetricReader(
            CloudMonitoringMetricsExporter(project_id=project_id),
            export_interval_millis=60_000,
        )
        # Drop otel.sdk.* self-observability metrics — written at sub-second
        # granularity and trigger "points written too frequently" from GCM.
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[metric_reader],
            views=[View(instrument_name="otel.sdk.*", aggregation=DropAggregation())],
        )
        metrics.set_meter_provider(meter_provider)
    except Exception as e:
        return False, f"OTEL provider setup failed: {e!r}"

    _tracer = trace.get_tracer(SERVICE_NAME)
    _meter  = metrics.get_meter(SERVICE_NAME)
    _m_llm_invocations = _meter.create_counter(
        "orchestrator.llm.invocations",
        description="Total DSPy/LiteLLM module invocations",
        unit="1",
    )
    _m_llm_duration = _meter.create_histogram(
        "orchestrator.llm.duration",
        description="DSPy/LiteLLM module invocation wall-clock duration",
        unit="s",
    )
    _m_shell_calls = _meter.create_counter(
        "orchestrator.shell.calls",
        description="Total shell/kubectl/gcloud subprocess calls",
        unit="1",
    )
    _enabled    = True
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
            try:
                s.record_exception(e)
                from opentelemetry.trace import Status, StatusCode
                s.set_status(Status(StatusCode.ERROR, str(e)[:200]))
            except Exception:
                pass
            raise


def record_llm(module_name: str, duration_s: float, status: str) -> None:
    """Record a DSPy module invocation (AssessPhaseHealth, DiagnoseFailure, etc.)."""
    if not _enabled:
        return
    labels = {"module": module_name, "status": status}
    _m_llm_invocations.add(1, labels)
    _m_llm_duration.record(duration_s, labels)


def record_shell(kind: str, status: str) -> None:
    if not _enabled:
        return
    _m_shell_calls.add(1, {"kind": kind, "status": status})


def shutdown() -> None:
    """Flush pending spans/metrics. Called at normal exit."""
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
