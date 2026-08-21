from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from services.langgraph.persistence.database import json_param, normalize_record, table, transaction

logger = logging.getLogger(__name__)


def record_analytics_event(
    tenant_id: str,
    project_id: str,
    event_name: str,
    properties: dict,
    run_id: str | None = None,
    source: str = "amc_first_party",
) -> dict:
    event_id = str(uuid4())
    occurred_at = datetime.now(timezone.utc).isoformat()
    with transaction(write=True) as db:
        db.execute(
            f"INSERT INTO {table('analytics_events')} (event_id, tenant_id, project_id, run_id, event_name, source, occurred_at, properties, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, tenant_id, project_id, run_id, event_name, source, occurred_at, json_param(properties), "analytics-event-v1"),
        )
        row = db.execute(f"SELECT * FROM {table('analytics_events')} WHERE event_id = ?", (event_id,)).fetchone()
        record = normalize_record(row)
        if isinstance(record.get("properties"), str):
            record["properties"] = json.loads(record["properties"])
        return record


def emit_lifecycle_event(
    tenant_id: str,
    project_id: str,
    event_name: str,
    properties: dict,
    run_id: str | None = None,
) -> dict | None:
    """Best-effort first-party lifecycle telemetry.

    Lifecycle telemetry must never change the agency workflow's business outcome.
    Failures are logged with non-sensitive identifiers and the primary workflow
    continues; durable run events remain the authoritative execution audit trail.
    """

    try:
        return record_analytics_event(
            tenant_id=tenant_id,
            project_id=project_id,
            event_name=event_name,
            properties=properties,
            run_id=run_id,
        )
    except Exception:
        logger.exception(
            "Failed to persist lifecycle analytics event",
            extra={
                "amc_event_name": event_name,
                "amc_project_id": project_id,
                "amc_run_id": run_id,
            },
        )
        return None
