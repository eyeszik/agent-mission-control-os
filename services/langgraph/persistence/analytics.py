from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from services.langgraph.persistence.database import json_param, normalize_record, table, transaction


def record_analytics_event(tenant_id: str, project_id: str, event_name: str, properties: dict, run_id: str | None = None, source: str = "amc_first_party") -> dict:
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
            import json
            record["properties"] = json.loads(record["properties"])
        return record
