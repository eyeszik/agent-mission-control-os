"""Reliability contracts for the project OS services.

Same rule as ``docs/production-slo-contract.md``: a numeric objective exists
only when an operator configures it (``AMC_SLO_<SERVICE>_<METRIC>``) after
measuring a baseline. Otherwise the objective reads ``GAP_NO_BASELINE``. The
*mechanisms* (bounded retry, dead letter, reconciliation) are real code and are
reported with the constant the code actually enforces.
"""

from __future__ import annotations

import os
from typing import Any

GAP = "GAP_NO_BASELINE"

SERVICES: dict[str, dict[str, Any]] = {
    "project_api": {"metrics": ("availability", "p95_latency_ms", "p99_latency_ms", "failure_rate"), "telemetry": "HTTP request logs"},
    "scheduler": {"metrics": ("scheduler_delay_seconds", "queue_age_seconds", "throughput_per_minute"), "telemetry": "scheduled_jobs.due_at vs updated_at"},
    "publication_worker": {"metrics": ("publication_delay_seconds", "failure_rate", "recovery_time_seconds"), "telemetry": "publication_attempts state timestamps"},
    "knowledge_pipeline": {"metrics": ("throughput_per_minute", "failure_rate"), "telemetry": "knowledge_items stage/status"},
    "memory": {"metrics": ("p95_latency_ms",), "telemetry": "memory resolve request logs"},
    "portfolio": {"metrics": ("p95_latency_ms",), "telemetry": "portfolio request logs"},
}

MECHANISMS: dict[str, dict[str, Any]] = {
    "bounded_retry": {"status": "IMPLEMENTED", "limit": 3, "source": "reliability.OutboxMessage.attempts <= 3"},
    "dead_letter": {"status": "IMPLEMENTED", "source": "outbox status FAILED + scheduled_jobs status FAILED (kept, never deleted)"},
    "duplicate_delivery_prevention": {"status": "IMPLEMENTED", "source": "compare-and-set job claim + provider idempotency key"},
    "reconciliation": {"status": "IMPLEMENTED", "source": "publication UNCERTAIN → provider.verify(idempotency_key)"},
    "object_reconciliation": {"status": "IMPLEMENTED", "source": "storage_objects PRESENT/MISSING reconcile"},
    "circuit_breaker": {"status": "NOT_IMPLEMENTED", "source": "no live provider exists to break against"},
    "backup_policy": {"status": "EXTERNAL_ACTIVATION_REQUIRED", "source": "PostgreSQL provider backups (Supabase)"},
    "restore_validation": {"status": GAP, "source": "requires a restore drill against the production provider"},
    "rto": {"status": GAP},
    "rpo": {"status": GAP},
    "resource_limits": {"status": "IMPLEMENTED", "source": "per-tenant run limits, per-run token budget, request size caps"},
}


def _configured(service: str, metric: str) -> float | str:
    raw = (os.environ.get(f"AMC_SLO_{service.upper()}_{metric.upper()}") or "").strip()
    if not raw:
        return GAP
    try:
        return float(raw)
    except ValueError:
        return GAP


def reliability_contracts() -> dict[str, Any]:
    return {
        "services": {
            name: {
                "objectives": {metric: _configured(name, metric) for metric in spec["metrics"]},
                "telemetry_source": spec["telemetry"],
            }
            for name, spec in SERVICES.items()
        },
        "mechanisms": MECHANISMS,
        "error_budget_policy": "derived from configured availability objectives only; none without a baseline",
    }
