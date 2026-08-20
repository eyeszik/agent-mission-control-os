from __future__ import annotations

from services.langgraph.persistence.database import is_postgres, normalize_record, transaction


def list_active_memberships(user_id: str) -> list[dict]:
    if not is_postgres():
        return []
    with transaction() as db:
        rows = db.execute(
            "SELECT tenant_id, user_id, role, allowed_project_ids, active FROM amc.tenant_memberships WHERE user_id = ? AND active = true ORDER BY tenant_id",
            (user_id,),
        ).fetchall()
        result: list[dict] = []
        for row in rows:
            record = normalize_record(row)
            record["allowed_project_ids"] = list(record.get("allowed_project_ids") or [])
            result.append(record)
        return result
