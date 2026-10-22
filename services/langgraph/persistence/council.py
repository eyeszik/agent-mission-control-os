"""Persistence for the mission council (SQLite migration 19 / 20261022_amc_mission_council_v1.sql).

A mission's status lives on its ``runs`` row; this module stores what is
council-specific. ``update_mission`` is the only writer of mission rows: it
compares and sets on ``version`` and accepts an allowlisted column set.
Checkpoints are hash-chained per mission. ``consume_approval`` inserts on the
approval's primary key, so an approval can be consumed once and never replayed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence.database import (
    decode_json,
    json_param,
    normalize_record,
    table,
    transaction,
)
from services.langgraph.persistence.tenancy import ensure_tenant_project

GENESIS_HASH = "0" * 64
MISSION_COLUMNS = frozenset({"phase", "lease_owner", "lease_expires_at", "approval_id", "approval_subject_hash",
                             "consumed_approval_id", "cancel_requested", "attempts", "last_error"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(record: dict, *keys: str) -> dict:
    for key in keys:
        if key in record:
            record[key] = decode_json(record[key], None)
    return record


def _is_unique_violation(exc: Exception) -> bool:
    name = type(exc).__name__
    return name in {"IntegrityError", "UniqueViolation"} or "UNIQUE" in str(exc).upper()


# ------------------------------------------------------------------------------------- ideas


def create_idea(*, tenant_id: str, project_id: str, title: str, description: str, created_by: str,
                seed_key: str | None = None) -> dict:
    """Insert an idea; with ``seed_key`` the call is idempotent per tenant (demo seeding)."""
    idea_id = f"idea_{uuid4().hex[:20]}"
    now = _now()
    with transaction(write=True) as db:
        ensure_tenant_project(db, tenant_id, project_id)
        if seed_key:
            row = db.execute(f"SELECT idea_id FROM {table('council_ideas')} WHERE tenant_id = ? AND seed_key = ?",
                             (tenant_id, seed_key)).fetchone()
            if row:
                idea_id = row["idea_id"]
                return get_idea(idea_id, db=db)  # type: ignore[return-value]
        db.execute(
            f"""INSERT INTO {table('council_ideas')} (idea_id, tenant_id, project_id, title, description, status,
                created_by, seed_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)""",
            (idea_id, tenant_id, project_id, title, description, created_by, seed_key, now, now),
        )
        return get_idea(idea_id, db=db)  # type: ignore[return-value]


def get_idea(idea_id: str, *, db: Any = None) -> dict | None:
    if db is None:
        with transaction() as fresh:
            return get_idea(idea_id, db=fresh)
    row = db.execute(f"SELECT * FROM {table('council_ideas')} WHERE idea_id = ?", (idea_id,)).fetchone()
    if not row:
        return None
    record = normalize_record(row)
    record.pop("seed_key", None)
    return record


def list_ideas(tenant_id: str, project_ids: list[str], *, limit: int = 20, before: str | None = None) -> list[dict]:
    if not project_ids:
        return []
    marks = ", ".join("?" for _ in project_ids)
    params: list[Any] = [tenant_id, *project_ids]
    cursor = ""
    if before:
        cursor = " AND created_at < ?"
        params.append(before)
    params.append(max(1, min(limit, 100)))
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('council_ideas')} WHERE tenant_id = ? AND project_id IN ({marks}){cursor} "
            "ORDER BY created_at DESC, idea_id DESC LIMIT ?", params).fetchall()
    out = []
    for row in rows:
        record = normalize_record(row)
        record.pop("seed_key", None)
        out.append(record)
    return out


def set_idea_status(idea_id: str, status: str) -> None:
    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('council_ideas')} SET status = ?, updated_at = ? WHERE idea_id = ?",
                   (status, _now(), idea_id))


# ---------------------------------------------------------------------------------- missions


def insert_mission(*, mission_id: str, idea_id: str, tenant_id: str, project_id: str, engine: str,
                   model_mode: str) -> dict:
    now = _now()
    with transaction(write=True) as db:
        db.execute(
            f"""INSERT INTO {table('council_missions')} (mission_id, idea_id, tenant_id, project_id, engine, model_mode,
                phase, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'STRATEGY', 0, ?, ?)""",
            (mission_id, idea_id, tenant_id, project_id, engine, model_mode, now, now),
        )
    return get_mission_row(mission_id)  # type: ignore[return-value]


def get_mission_row(mission_id: str) -> dict | None:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('council_missions')} WHERE mission_id = ?", (mission_id,)).fetchone()
    return normalize_record(row) if row else None


def update_mission(mission_id: str, expected_version: int, **fields: Any) -> dict | None:
    """Compare-and-set on ``version``; returns the new row or None when another writer won."""
    unknown = set(fields) - MISSION_COLUMNS
    if unknown:
        raise ValueError(f"not writable: {sorted(unknown)}")
    assignments = ", ".join(f"{name} = ?" for name in fields)
    params = [*fields.values(), _now(), mission_id, expected_version]
    with transaction(write=True) as db:
        cursor = db.execute(
            f"UPDATE {table('council_missions')} SET {assignments}{', ' if assignments else ''}version = version + 1, "
            "updated_at = ? WHERE mission_id = ? AND version = ?", params)
        if cursor.rowcount != 1:
            return None
    return get_mission_row(mission_id)


def acquire_lease(mission_id: str, owner: str, ttl_seconds: int) -> dict | None:
    """Take the execution lease if it is free or expired. One worker per mission at a time."""
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
    with transaction(write=True) as db:
        cursor = db.execute(
            f"""UPDATE {table('council_missions')} SET lease_owner = ?, lease_expires_at = ?, version = version + 1,
                updated_at = ? WHERE mission_id = ? AND (lease_owner IS NULL OR lease_expires_at IS NULL
                OR lease_expires_at < ? OR lease_owner = ?)""",
            (owner, expires, now.isoformat(), mission_id, now.isoformat(), owner))
        if cursor.rowcount != 1:
            return None
    return get_mission_row(mission_id)


def release_lease(mission_id: str, owner: str) -> None:
    with transaction(write=True) as db:
        db.execute(
            f"""UPDATE {table('council_missions')} SET lease_owner = NULL, lease_expires_at = NULL, version = version + 1,
                updated_at = ? WHERE mission_id = ? AND lease_owner = ?""", (_now(), mission_id, owner))


def lease_expired(row: dict) -> bool:
    expires = row.get("lease_expires_at")
    return not row.get("lease_owner") or not expires or expires < datetime.now(timezone.utc).isoformat()


def list_missions(tenant_id: str, project_ids: list[str], *, idea_id: str | None = None,
                  limit: int = 20, before: str | None = None) -> list[dict]:
    if not project_ids:
        return []
    marks = ", ".join("?" for _ in project_ids)
    params: list[Any] = [tenant_id, *project_ids]
    extra = ""
    if idea_id:
        extra += " AND m.idea_id = ?"
        params.append(idea_id)
    if before:
        extra += " AND m.created_at < ?"
        params.append(before)
    params.append(max(1, min(limit, 100)))
    with transaction() as db:
        rows = db.execute(
            f"""SELECT m.*, r.status AS status FROM {table('council_missions')} m
                JOIN {table('runs')} r ON r.run_id = m.mission_id
                WHERE m.tenant_id = ? AND m.project_id IN ({marks}){extra}
                ORDER BY m.created_at DESC, m.mission_id DESC LIMIT ?""", params).fetchall()
    return [normalize_record(r) for r in rows]


def missions_for_idea(idea_id: str) -> list[dict]:
    with transaction() as db:
        rows = db.execute(
            f"""SELECT m.*, r.status AS status FROM {table('council_missions')} m
                JOIN {table('runs')} r ON r.run_id = m.mission_id WHERE m.idea_id = ? ORDER BY m.created_at""",
            (idea_id,)).fetchall()
    return [normalize_record(r) for r in rows]


def stale_running_missions() -> list[dict]:
    """Missions whose worker stopped: running or resuming with an expired lease (restart recovery)."""
    now = _now()
    with transaction() as db:
        rows = db.execute(
            f"""SELECT m.mission_id FROM {table('council_missions')} m JOIN {table('runs')} r ON r.run_id = m.mission_id
                WHERE r.status IN ('queued', 'running', 'resuming')
                AND (m.lease_owner IS NULL OR m.lease_expires_at IS NULL OR m.lease_expires_at < ?)""",
            (now,)).fetchall()
    return [normalize_record(r) for r in rows]


# ------------------------------------------------------------------------------- checkpoints


def append_checkpoint(*, mission_id: str, phase: str, engine: str, state: dict,
                      native_checkpoint_id: str | None = None) -> dict:
    """Append a hash-chained snapshot of the council state."""
    checkpoint_id = f"cp_{uuid4().hex[:20]}"
    state_hash = canonical_hash(state)
    with transaction(write=True) as db:
        last = db.execute(
            f"SELECT seq, state_hash, prev_hash FROM {table('council_checkpoints')} WHERE mission_id = ? "
            "ORDER BY seq DESC LIMIT 1", (mission_id,)).fetchone()
        seq = (int(last["seq"]) + 1) if last else 0
        prev = canonical_hash({"prev": last["prev_hash"], "state": last["state_hash"]}) if last else GENESIS_HASH
        db.execute(
            f"""INSERT INTO {table('council_checkpoints')} (checkpoint_id, mission_id, seq, phase, engine, state, state_hash,
                prev_hash, native_checkpoint_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (checkpoint_id, mission_id, seq, phase, engine, json_param(state), state_hash, prev, native_checkpoint_id, _now()))
    return {"checkpoint_id": checkpoint_id, "seq": seq, "state_hash": state_hash, "prev_hash": prev}


def list_checkpoints(mission_id: str, *, include_state: bool = False) -> list[dict]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('council_checkpoints')} WHERE mission_id = ? ORDER BY seq",
                          (mission_id,)).fetchall()
    out = []
    for row in rows:
        record = _json(normalize_record(row), "state")
        if not include_state:
            record.pop("state", None)
        out.append(record)
    return out


def latest_checkpoint_state(mission_id: str) -> dict | None:
    with transaction() as db:
        row = db.execute(f"SELECT state FROM {table('council_checkpoints')} WHERE mission_id = ? ORDER BY seq DESC LIMIT 1",
                         (mission_id,)).fetchone()
    return decode_json(row["state"], {}) if row else None


def verify_checkpoint_chain(mission_id: str) -> tuple[bool, str]:
    rows = list_checkpoints(mission_id, include_state=True)
    prev_state, prev_link = None, None
    for i, row in enumerate(rows):
        if row["seq"] != i:
            return False, f"checkpoint sequence gap at {i}"
        if canonical_hash(row["state"]) != row["state_hash"]:
            return False, f"checkpoint {i} state does not match its hash"
        expected = GENESIS_HASH if i == 0 else canonical_hash({"prev": prev_link, "state": prev_state})
        if row["prev_hash"] != expected:
            return False, f"checkpoint {i} breaks the hash chain"
        prev_state, prev_link = row["state_hash"], row["prev_hash"]
    return True, f"{len(rows)} checkpoint(s) verified"


# --------------------------------------------------------------------------- approvals, audit


def consume_approval(*, approval_id: str, mission_id: str, action_hash: str, consumed_by: str) -> bool:
    """True the first time this approval is used for this action; False on any replay."""
    try:
        with transaction(write=True) as db:
            db.execute(
                f"""INSERT INTO {table('council_approval_consumptions')} (approval_id, mission_id, action_hash, consumed_by,
                    consumed_at) VALUES (?, ?, ?, ?, ?)""", (approval_id, mission_id, action_hash, consumed_by, _now()))
        return True
    except Exception as exc:
        if _is_unique_violation(exc):
            return False
        raise


def approval_consumption(approval_id: str, action_hash: str) -> dict | None:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('council_approval_consumptions')} WHERE approval_id = ? AND action_hash = ?",
                         (approval_id, action_hash)).fetchone()
    return normalize_record(row) if row else None


def record_tool_audit(*, tenant_id: str, project_id: str, mission_id: str | None, seat: str | None, tool_id: str,
                      sensitivity: str, decision: str, reason_code: str, args_redacted: Any, args_hash: str,
                      result_summary: str | None = None, approval_id: str | None = None,
                      action_hash: str | None = None, duration_ms: int | None = None) -> dict:
    audit_id = f"ta_{uuid4().hex[:20]}"
    with transaction(write=True) as db:
        db.execute(
            f"""INSERT INTO {table('council_tool_audits')} (audit_id, tenant_id, project_id, mission_id, seat, tool_id,
                sensitivity, decision, reason_code, args_redacted, args_hash, result_summary, approval_id, action_hash,
                duration_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (audit_id, tenant_id, project_id, mission_id, seat, tool_id, sensitivity, decision, reason_code,
             json_param(args_redacted), args_hash, (result_summary or "")[:500] or None, approval_id, action_hash,
             duration_ms, _now()))
    return {"audit_id": audit_id, "decision": decision, "reason_code": reason_code}


def list_tool_audits(mission_id: str) -> list[dict]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('council_tool_audits')} WHERE mission_id = ? ORDER BY created_at",
                          (mission_id,)).fetchall()
    return [_json(normalize_record(r), "args_redacted") for r in rows]


# -------------------------------------------------------------------------------- blueprints


def create_blueprint(*, idea_id: str, tenant_id: str, project_id: str, content: dict, sources: list[dict],
                     created_by: str) -> dict:
    blueprint_id = f"bp_{uuid4().hex[:20]}"
    with transaction(write=True) as db:
        db.execute(
            f"""INSERT INTO {table('council_blueprints')} (blueprint_id, idea_id, tenant_id, project_id, status, content,
                content_hash, sources, created_by, created_at) VALUES (?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?)""",
            (blueprint_id, idea_id, tenant_id, project_id, json_param(content), canonical_hash(content),
             json_param(sources), created_by, _now()))
    return get_blueprint(blueprint_id)  # type: ignore[return-value]


def get_blueprint(blueprint_id: str) -> dict | None:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('council_blueprints')} WHERE blueprint_id = ?", (blueprint_id,)).fetchone()
    return _json(normalize_record(row), "content", "sources", "verification") if row else None


def list_blueprints(idea_id: str) -> list[dict]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('council_blueprints')} WHERE idea_id = ? ORDER BY created_at DESC",
                          (idea_id,)).fetchall()
    return [_json(normalize_record(r), "content", "sources", "verification") for r in rows]


def promote_blueprint(blueprint_id: str, *, promoted_by: str, verification: dict) -> dict | None:
    with transaction(write=True) as db:
        cursor = db.execute(
            f"""UPDATE {table('council_blueprints')} SET status = 'PROMOTED', promoted_by = ?, promoted_at = ?,
                verification = ? WHERE blueprint_id = ? AND status = 'DRAFT'""",
            (promoted_by, _now(), json_param(verification), blueprint_id))
        if cursor.rowcount != 1:
            return None
    return get_blueprint(blueprint_id)


def record_verification(blueprint_id: str, verification: dict) -> None:
    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('council_blueprints')} SET verification = ? WHERE blueprint_id = ?",
                   (json_param(verification), blueprint_id))


__all__ = [
    "GENESIS_HASH", "MISSION_COLUMNS", "acquire_lease", "append_checkpoint", "approval_consumption", "consume_approval",
    "create_blueprint", "create_idea", "get_blueprint", "get_idea", "get_mission_row", "insert_mission",
    "latest_checkpoint_state", "lease_expired", "list_blueprints", "list_checkpoints", "list_ideas", "list_missions",
    "list_tool_audits", "missions_for_idea", "promote_blueprint", "record_tool_audit", "record_verification",
    "release_lease", "set_idea_status", "stale_running_missions", "update_mission", "verify_checkpoint_chain",
]
