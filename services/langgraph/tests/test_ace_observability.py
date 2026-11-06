"""Operational metrics are measured from persistence or explicitly unavailable."""
from services.langgraph.agency.durable.observability import (
    metrics, record_ace_counter, record_ace_duration, traced_boundary
)


def test_ace_operational_metrics_use_persisted_data_not_invented_numbers():
    ticks = [
        {"outcome": "STALE_FENCE", "telemetry": {"latency_ms": 20}},
        {"outcome": "QUARANTINE", "telemetry": {"latency_ms": 8}},
        {"outcome": "LEASE_CONTENTION", "telemetry": {"latency_ms": 2}},
    ]
    intents = [
        {"status": "UNCONFIRMED", "created_at": "2026-10-13T12:00:00+00:00",
         "committed_at": None},
        {"status": "COMMITTED", "created_at": "2026-10-13T12:00:00+00:00",
         "committed_at": "2026-10-13T12:00:02+00:00"},
    ]
    result = metrics(ticks=ticks, transitions=[], intents=intents)
    ace = result["ace_v100"]
    assert ace["lease_contention_total"] == 1
    assert ace["fence_rejection_total"] == 1
    assert ace["quarantine_events_total"] == 1
    assert ace["unconfirmed_intents"] == 1
    assert ace["reconciliation_drift_seconds"]["median"] == 2


def test_ace_telemetry_is_opt_in_and_metric_names_are_allowlisted(monkeypatch):
    monkeypatch.delenv("AMC_OTEL_EXPORT", raising=False)
    assert record_ace_counter("fence_rejection_total") is False
    assert record_ace_duration("reconciliation_drift_seconds", 0.5) is False
    import pytest
    with pytest.raises(ValueError):
        record_ace_counter("tenant_private_id")
    with pytest.raises(ValueError):
        record_ace_duration("unknown", -1)


def test_ace_trace_boundary_preserves_execution_semantics(monkeypatch):
    monkeypatch.delenv("AMC_OTEL_EXPORT", raising=False)
    calls = []
    @traced_boundary("amc.durable.test")
    def work(input_value):
        calls.append(input_value)
        return input_value * 2
    assert work(3) == 6
    assert calls == [3]


def test_ace_optional_otel_counter_has_no_pii_in_tags(monkeypatch):
    monkeypatch.setenv("AMC_OTEL_EXPORT", "enabled")
    from opentelemetry import metrics as otel_metrics
    captured = []
    class Counter:
        def add(self, value, attributes):
            captured.append((value, attributes))
    class Meter:
        def create_counter(self, name):
            assert name == "quarantine_events_total"
            return Counter()
    monkeypatch.setattr(otel_metrics, "get_meter", lambda name: Meter())
    assert record_ace_counter("quarantine_events_total") is True
    assert captured == [(1, {"component": "ace"})]
