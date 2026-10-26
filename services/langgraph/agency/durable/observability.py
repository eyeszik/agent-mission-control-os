"""Observability read model over durable state. Every number is computed from persisted rows.

Metrics come from ``durable_ticks`` telemetry, ``durable_transitions``,
``durable_intents`` and the approvals table. Anything the rows do not contain
is reported as ``NOT_MEASURED`` (cost, GPU memory) or ``BASELINE_UNKNOWN``
(percentile comparisons): no metric is invented and no P99 is compared without
a measured baseline.

Span export is OpenTelemetry-shaped (trace_id, name, start/end, attributes).
It is emitted through the OpenTelemetry SDK only when that SDK is installed and
``AMC_OTEL_EXPORT=enabled``; Datadog export is never performed by this module.
Telemetry never carries prompts, secrets or client material: attributes are an
allowlist of identifiers, states, hashes and timings.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime
from statistics import median
from typing import Iterable, Optional

SPAN_ATTRIBUTES = ("trace_id", "mission_id", "project_id", "job_id", "node_id", "capability", "execution_mode", "attempt",
                   "logical_tick", "latency_ms", "queue_lag_ms", "observed_cost", "artifact_hash", "verification_state",
                   "failure_fingerprint", "checkpoint_version", "next_due_at", "final_state")


ACE_COUNTERS = frozenset({
    "lease_contention_total", "fence_rejection_total",
    "quarantine_events_total", "reconciliation_probe_total",
})
ACE_HISTOGRAMS = frozenset({"reconciliation_drift_seconds"})


def record_ace_counter(name: str, amount: int = 1) -> bool:
    """Emit an allowlisted OTel counter; false means no exporter is configured."""
    if name not in ACE_COUNTERS or amount <= 0:
        raise ValueError("invalid ACE metric")
    if exporter_status()["opentelemetry"] != "ENABLED":
        return False
    from opentelemetry import metrics  # type: ignore[import-not-found]

    meter = metrics.get_meter("amc.ace.v100")
    meter.create_counter(name).add(amount, {"component": "ace"})
    return True


def record_ace_duration(name: str, seconds: float) -> bool:
    if name not in ACE_HISTOGRAMS or seconds < 0:
        raise ValueError("invalid ACE duration")
    if exporter_status()["opentelemetry"] != "ENABLED":
        return False
    from opentelemetry import metrics  # type: ignore[import-not-found]

    metrics.get_meter("amc.ace.v100").create_histogram(name, unit="s").record(
        seconds, {"component": "ace"}
    )
    return True


def traced_boundary(span_name: str):
    """Propagate the OTel context across synchronous and asynchronous calls.

    All attributes are allowlisted by call sites. Disabled telemetry adds no
    external effect and leaves existing runtime behavior unchanged.
    """
    from functools import wraps
    if not span_name or len(span_name) > 80:
        raise ValueError("invalid OTel span name")

    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if exporter_status()["opentelemetry"] != "ENABLED":
                return fn(*args, **kwargs)
            from opentelemetry import trace
            with trace.get_tracer("amc.ace.v100").start_as_current_span(span_name):
                return fn(*args, **kwargs)
        return wrapper
    return decorate


def _ms_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    if not a or not b:
        return None
    return int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() * 1000)


def exporter_status() -> dict:
    otel_installed = importlib.util.find_spec("opentelemetry") is not None
    otel_enabled = (os.environ.get("AMC_OTEL_EXPORT") or "").strip().lower() == "enabled"
    return {
        "opentelemetry": ("ENABLED" if otel_installed and otel_enabled else
                          "NOT_INSTALLED" if not otel_installed else "NOT_CONFIGURED"),
        "datadog": "NOT_CONFIGURED: no exporter in this module; requires explicit configuration and authorization",
    }


def spans(ticks: Iterable[dict]) -> list[dict]:
    out = []
    for t in ticks:
        tel = t.get("telemetry") or {}
        out.append({"trace_id": t["trace_id"], "name": f"amc.durable.tick/{tel.get('node_id') or 'idle'}",
                    "start": t["started_at"], "end": t["finished_at"],
                    "attributes": {k: tel.get(k) for k in SPAN_ATTRIBUTES if k in tel}, "status": t["outcome"]})
    return out


def emit_spans(span_docs: list[dict]) -> dict:
    """Send to the OpenTelemetry SDK when installed and enabled; otherwise report why nothing was sent."""
    status = exporter_status()
    if status["opentelemetry"] != "ENABLED":
        return {"sent": 0, "status": status["opentelemetry"]}
    from opentelemetry import trace  # type: ignore[import-not-found]

    tracer = trace.get_tracer("amc.durable")
    for doc in span_docs:
        with tracer.start_as_current_span(doc["name"]) as span:
            for k, v in doc["attributes"].items():
                if v is not None:
                    span.set_attribute(f"amc.{k}", v if isinstance(v, (str, int, float, bool)) else str(v))
    return {"sent": len(span_docs), "status": "ENABLED"}


def metrics(*, ticks: list[dict], transitions: list[dict], intents: list[dict], approvals: list[dict] = ()) -> dict:
    working = [t for t in ticks if t["outcome"] != "NO_WORK"]
    lags = [t["telemetry"]["queue_lag_ms"] for t in working if t["telemetry"].get("queue_lag_ms") is not None]
    latencies = [t["telemetry"]["latency_ms"] for t in working if t["telemetry"].get("latency_ms") is not None]
    renders = [t["telemetry"].get("resource_usage", {}).get("render_wall_ms") for t in working]
    renders = [r for r in renders if r is not None]
    verified = [t for t in working if t["telemetry"].get("verification_state")]
    passed = sum(1 for t in verified if t["telemetry"]["verification_state"] == "PASSED")
    retries = sum(1 for tr in transitions if tr["to_state"] == "RETRY_PENDING")
    dispatch_failures = sum(1 for t in working if t["outcome"] in {"RETRY_PENDING", "DEAD_LETTER"})
    recoveries = [tr for tr in transitions if tr["from_state"] != "RECONCILING" and tr["to_state"] == "RECONCILING"]
    decided = [a for a in approvals if a.get("decided_at")]

    def summary(values: list[int]) -> dict:
        if not values:
            return {"count": 0, "median": None, "max": None}
        return {"count": len(values), "median": median(values), "max": max(values)}

    return {
        "ticks": len(ticks), "working_ticks": len(working),
        "queue_lag_ms": summary(lags), "tick_latency_ms": summary(latencies), "render_latency_ms": summary(renders),
        "verification": {"passed": passed, "failed_or_other": len(verified) - passed},
        "retry_rate": (retries / len(working)) if working else None, "dispatch_failures": dispatch_failures,
        "intents": {"committed": sum(1 for i in intents if i["status"] == "COMMITTED"),
                    "open": sum(1 for i in intents if i["status"] == "INTENT")},
        "recoveries": len(recoveries),
        "ace_v100": {
            "lease_contention_total": sum(1 for t in ticks if t["outcome"] == "LEASE_CONTENTION"),
            "fence_rejection_total": sum(1 for t in ticks if t["outcome"] == "STALE_FENCE"),
            "quarantine_events_total": sum(1 for t in ticks if t["outcome"] == "QUARANTINE"),
            "unconfirmed_intents": sum(1 for i in intents if i["status"] == "UNCONFIRMED"),
            "reconciliation_drift_seconds": summary([
                max(0, int(_ms_between(i.get("created_at"), i.get("committed_at")) / 1000))
                for i in intents
                if i.get("created_at") and i.get("committed_at")
                and _ms_between(i.get("created_at"), i.get("committed_at")) is not None
            ]),
            "scope": "persisted ticks and intents; runtime OTel counter totals require exporter",
        },
        "approval_latency_ms": summary([v for v in (_ms_between(a["created_at"], a["decided_at"]) for a in decided)
                                        if v is not None]),
        "gpu_memory": "NOT_MEASURED", "cost_per_verified_artifact": "NOT_MEASURED",
        "scheduler_availability": "NOT_MEASURED: no persistent worker is deployed; ticks are invoked explicitly",
        "percentile_comparison": "BASELINE_UNKNOWN",
        "exporters": exporter_status(),
    }


def project_metrics(project_id: str) -> dict:
    from services.langgraph.persistence import durable_runs as store

    jobs = store.jobs_for_project(project_id)
    transitions = [tr for j in jobs for tr in store.list_transitions(j["job_id"])]
    intents = [i for j in jobs for i in store.list_intents(j["job_id"])]
    return metrics(ticks=store.list_project_ticks(project_id), transitions=transitions, intents=intents)


__all__ = ["ACE_COUNTERS", "ACE_HISTOGRAMS", "SPAN_ATTRIBUTES", "emit_spans", "exporter_status", "metrics", "project_metrics", "record_ace_counter", "record_ace_duration", "spans", "traced_boundary"]
