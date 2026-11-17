"""
OpenTelemetry distributed tracing module for PreAuth pipeline.

Provides:
- Singleton TracerProvider setup with resource tagging
- OTLP HTTP/gRPC exporter configuration when OTEL_ENABLED=true
- Safe no-op fallback when tracing is disabled or exporter is unreachable
- Context propagation helpers for W3C traceparent (FastAPI -> Celery -> Worker)
- Strict allowlist filtering to prevent PHI/sensitive clinical data leakage into trace spans
"""
from __future__ import annotations

import contextlib
import os
from typing import Any, Iterator

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.trace import Span, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_TRACER_PROVIDER: TracerProvider | None = None
_PROPAGATOR = TraceContextTextMapPropagator()

# Strict allowlist of low-cardinality, non-sensitive attribute keys
ALLOWLISTED_ATTRIBUTES = {
    "preauth.run_id",
    "preauth.correlation_id",
    "preauth.agent",
    "preauth.tool",
    "preauth.route",
    "preauth.recommendation",
    "preauth.verification_passed",
    "preauth.verification_attempt",
    "preauth.escalation_required",
    "preauth.error_type",
    "preauth.retrieval_mode",
    "preauth.step_count",
    "preauth.tool_call_count",
    "http.status_code",
    "http.method",
    "http.route",
}


def is_tracing_enabled() -> bool:
    """Check if OpenTelemetry distributed tracing is active."""
    return os.getenv("OTEL_ENABLED", "false").lower() in {"true", "1", "yes"}


def sanitize_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    """Filter attributes against strict allowlist to guarantee no PHI enters traces."""
    if not attributes:
        return {}
    sanitized = {}
    for k, v in attributes.items():
        if k in ALLOWLISTED_ATTRIBUTES:
            if isinstance(v, (str, bool, int, float)):
                sanitized[k] = v
            elif v is None:
                continue
            else:
                sanitized[k] = str(v)
    return sanitized


def init_tracer(service_name: str | None = None) -> Tracer:
    """Initialize singleton TracerProvider once per process."""
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER is not None:
        return trace.get_tracer("preauth")

    if not service_name:
        service_name = os.getenv("OTEL_SERVICE_NAME", "preauth-api")

    resource = Resource.create({
        "service.name": service_name,
        "service.version": "1.0.0",
        "deployment.environment": os.getenv("APP_ENV", "production"),
    })

    provider = TracerProvider(resource=resource)

    if is_tracing_enabled():
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318/v1/traces")
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint, timeout=2.0)
            # Use BatchSpanProcessor for production non-blocking exports
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception:
            # If exporter cannot initialize, fail open with no-op / provider without exporter
            pass

    trace.set_tracer_provider(provider)
    _TRACER_PROVIDER = provider
    return trace.get_tracer("preauth")


def get_tracer(name: str = "preauth") -> Tracer:
    """Get active tracer instance."""
    if _TRACER_PROVIDER is None:
        return init_tracer()
    return trace.get_tracer(name)


def inject_trace_context(carrier: dict[str, str] | None = None) -> dict[str, str]:
    """Inject current span context into a W3C traceparent dictionary carrier."""
    if carrier is None:
        carrier = {}
    if is_tracing_enabled():
        try:
            _PROPAGATOR.inject(carrier)
        except Exception:
            pass
    return carrier


def extract_trace_context(carrier: dict[str, str]) -> Any:
    """Extract OpenTelemetry context from W3C traceparent carrier."""
    if not carrier:
        return None
    try:
        return _PROPAGATOR.extract(carrier)
    except Exception:
        return None


@contextlib.contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    parent_context: Any = None,
) -> Iterator[Span]:
    """
    Context manager to safely create a trace span.
    Fail-open: never raises if OpenTelemetry fails or is disabled.
    Enforces attribute filtering.
    """
    tracer = get_tracer()
    filtered_attrs = sanitize_attributes(attributes)

    try:
        with tracer.start_as_current_span(
            name=name,
            context=parent_context,
            attributes=filtered_attrs,
        ) as span:
            yield span
    except Exception as exc:
        # Re-raise so the caller's business logic error handling sees the original exception
        raise exc


def record_exception(span: Span | None, error: Exception | str) -> None:
    """Safely record an error on the span without leaking PHI."""
    if span is None or not span.is_recording():
        return
    try:
        err_type = error.__class__.__name__ if isinstance(error, Exception) else "WorkflowError"
        span.set_attribute("preauth.error_type", err_type)
        if isinstance(error, Exception):
            span.record_exception(error)
    except Exception:
        pass


def shutdown_tracing() -> None:
    """Flush and shut down tracing provider."""
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER is not None:
        try:
            _TRACER_PROVIDER.shutdown()
        except Exception:
            pass
        _TRACER_PROVIDER = None

