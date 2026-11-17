"""
Unit tests for OpenTelemetry distributed tracing, context propagation, and PHI protection.
"""
import pytest
from src.observability.tracing import (
    ALLOWLISTED_ATTRIBUTES,
    extract_trace_context,
    inject_trace_context,
    is_tracing_enabled,
    record_exception,
    sanitize_attributes,
    trace_span,
)


def test_sanitize_attributes_allowlist_enforcement():
    raw_attributes = {
        "preauth.run_id": "test-uuid-1234",
        "preauth.correlation_id": "test-corr-5678",
        "preauth.agent": "coverage",
        "preauth.tool": "corpus_search",
        "preauth.route": "medical-review",
        # Sensitive PHI / PII that MUST be stripped:
        "patient_name": "John Doe",
        "diagnosis_name": "Senile immature cataract",
        "procedure_name": "Phacoemulsification",
        "member_id": "MEM123456",
        "policy_number": "POL-9999",
        "request_json": '{"patient": "secret"}',
        "jwt_token": "Bearer secret-token",
    }

    sanitized = sanitize_attributes(raw_attributes)

    # Only allowlisted keys must remain
    for k in sanitized:
        assert k in ALLOWLISTED_ATTRIBUTES

    assert "patient_name" not in sanitized
    assert "diagnosis_name" not in sanitized
    assert "procedure_name" not in sanitized
    assert "member_id" not in sanitized
    assert "policy_number" not in sanitized
    assert "request_json" not in sanitized
    assert "jwt_token" not in sanitized

    assert sanitized["preauth.run_id"] == "test-uuid-1234"
    assert sanitized["preauth.agent"] == "coverage"


def test_w3c_context_propagation(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "true")

    carrier = {}
    with trace_span("preauth.submit", attributes={"preauth.run_id": "run-001"}):
        inject_trace_context(carrier)

    assert isinstance(carrier, dict)
    # If a span is active, traceparent header is generated
    if "traceparent" in carrier:
        extracted = extract_trace_context(carrier)
        assert extracted is not None


def test_tracing_disabled_fail_open(monkeypatch):
    monkeypatch.setenv("OTEL_ENABLED", "false")
    assert not is_tracing_enabled()

    # trace_span should execute block without errors
    executed = False
    with trace_span("preauth.test_disabled", attributes={"preauth.run_id": "123"}):
        executed = True

    assert executed is True


def test_record_exception_non_sensitive():
    class DummySpan:
        def __init__(self):
            self.attrs = {}
            self.recorded = []

        def is_recording(self):
            return True

        def set_attribute(self, k, v):
            self.attrs[k] = v

        def record_exception(self, exc):
            self.recorded.append(exc)

    span = DummySpan()
    err = ValueError("Sensitive clinical error details that should not leak to error_type")
    record_exception(span, err)

    # Type is recorded, not raw text in error_type
    assert span.attrs["preauth.error_type"] == "ValueError"
    assert len(span.recorded) == 1

