"""Persistence for the governed action plane (migration 16).

Rows only. Authorization, risk and lifecycle rules live in
``agency/actions``. What the database layer itself guarantees, whoever calls it:

* every state change is a compare-and-set on ``version`` and the expected
  state, and appends a transition whose hash covers the previous one, so a
  lost update is impossible and an edited history is detectable;
* one action per (tenant, idempotency key), checked and inserted under a lock;
* budget reservations are checked against every applicable ceiling and
  inserted in one locked transaction, so concurrent reservations cannot
  jointly exceed a ceiling (I10);
* the sandbox effect store dedupes on (tenant, provider, idempotency key), so
  an at-least-once retry cannot create a second fake effect.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from uuid import uuid4

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence.database import decode_json, is_postgres, json_param, normalize_record, table, transaction
from services.langgraph.persistence.tenancy import ensure_tenant_project


class ActionNotFound(LookupError):
    pass


class ActionConflict(ValueError):
    """A compare-and-set lost, or an identity already exists with a different body."""


class BudgetExceeded(ValueError):
    def __init__(self, code: str, details: dict):
        super().__init__(code)
        self.code = code
        self.details = details


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def now_iso() -> str:
    return iso(datetime.now(timezone.utc))


def _lock(db: Any, ref: str) -> None:
    if is_postgres():
        db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (ref,))


_REQUEST_JSON = (("args", {}), ("dependency_hashes", []), ("risk", {}), ("binding", {}), ("reasons", []),
                 ("outcome", None), ("injection_flags", []))


def _request(row: Any) -> Optional[dict]:
    if row is None:
        return None
    rec = normalize_record(row)
    for key, default in _REQUEST_JSON:
        rec[key] = decode_json(rec.get(key), default)
    rec["retry_eligible"] = bool(rec.get("retry_eligible"))
    return rec


# --------------------------------------------------------------------------- requests

_INSERT_COLUMNS = (
    "action_id", "tenant_id", "project_id", "client_id", "capability_id", "capability_version", "environment", "actor_ref",
    "target_ref", "args", "args_hash", "payload_hash", "context_hash", "dependency_hashes", "policy_version", "risk",
    "risk_hash", "effective_class", "binding", "binding_hash", "run_id", "approval_id", "financial_approval_id",
    "budget_reservation_id", "idempotency_key", "request_hash", "correlation_id", "state", "version", "attempts",
    "reconcile_attempts", "lease_owner", "lease_expires_at", "retry_eligible", "reasons", "outcome", "injection_flags",
    "created_at", "updated_at", "expires_at",
)
_JSON_COLUMNS = {"args", "dependency_hashes", "risk", "binding", "reasons", "outcome", "injection_flags"}
# Columns a transition may change. Identity, args and binding never change after insert.
_MUTABLE = frozenset({"run_id", "approval_id", "financial_approval_id", "budget_reservation_id", "attempts",
                      "reconcile_attempts", "lease_owner", "lease_expires_at", "retry_eligible", "reasons", "outcome"})


def _append_transition(db: Any, *, action_id: str, tenant_id: str, from_state: Optional[str], to_state: str, actor: str,
                       reason: str, evidence: dict, created_at: str) -> dict:
    _lock(db, f"action-chain:{action_id}")
    prev = db.execute(f"SELECT entry_hash FROM {table('action_transitions')} WHERE action_id = ? ORDER BY entry_id DESC LIMIT 1",
                      (action_id,)).fetchone()
    prev_hash = normalize_record(prev)["entry_hash"] if prev else None
    body = {"action_id": action_id, "tenant_id": tenant_id, "from_state": from_state, "to_state": to_state, "actor": actor,
            "reason": reason, "evidence": evidence, "prev_hash": prev_hash, "created_at": created_at}
    entry_hash = canonical_hash(body)
    db.execute(
        f"""INSERT INTO {table('action_transitions')} (action_id, tenant_id, from_state, to_state, actor, reason, evidence,
        prev_hash, entry_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (action_id, tenant_id, from_state, to_state, actor, reason, json_param(evidence), prev_hash, entry_hash, created_at),
    )
    return {**body, "entry_hash": entry_hash}


def find_by_key(tenant_id: str, idempotency_key: str) -> Optional[dict]:
    with transaction() as db:
        return _request(db.execute(f"SELECT * FROM {table('action_requests')} WHERE tenant_id = ? AND idempotency_key = ?",
                                   (tenant_id, idempotency_key)).fetchone())


def insert_request(row: dict, *, actor: str, reason: str, evidence: Optional[dict] = None) -> tuple[dict, bool]:
    """Insert a PROPOSED action. Returns (row, created). A second insert with the
    same (tenant, idempotency key) returns the existing row when the request is
    identical and raises ActionConflict when it differs (E01)."""
    with transaction(write=True) as db:
        ensure_tenant_project(db, row["tenant_id"], row["project_id"])
        _lock(db, f"action-key:{row['tenant_id']}:{row['idempotency_key']}")
        existing = _request(db.execute(f"SELECT * FROM {table('action_requests')} WHERE tenant_id = ? AND idempotency_key = ?",
                                       (row["tenant_id"], row["idempotency_key"])).fetchone())
        if existing is not None:
            if existing["request_hash"] != row["request_hash"]:
                raise ActionConflict("IDEMPOTENCY_KEY_REUSED: the key was used for a different request")
            return existing, False
        values = [json_param(row[c]) if c in _JSON_COLUMNS else row[c] for c in _INSERT_COLUMNS]
        db.execute(f"INSERT INTO {table('action_requests')} ({', '.join(_INSERT_COLUMNS)}) VALUES ({', '.join('?' for _ in _INSERT_COLUMNS)})",
                   values)
        _append_transition(db, action_id=row["action_id"], tenant_id=row["tenant_id"], from_state=None, to_state=row["state"],
                           actor=actor, reason=reason, evidence=evidence or {}, created_at=row["created_at"])
        created = _request(db.execute(f"SELECT * FROM {table('action_requests')} WHERE action_id = ?", (row["action_id"],)).fetchone())
    return created, True


def get_request(action_id: str) -> Optional[dict]:
    with transaction() as db:
        return _request(db.execute(f"SELECT * FROM {table('action_requests')} WHERE action_id = ?", (action_id,)).fetchone())


def list_requests(tenant_id: str, *, project_ids: Optional[Iterable[str]] = None, states: Iterable[str] = (),
                  limit: int = 200) -> list[dict]:
    query = f"SELECT * FROM {table('action_requests')} WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]
    if project_ids is not None:
        ids = list(project_ids)
        if not ids:
            return []
        query += f" AND project_id IN ({', '.join('?' for _ in ids)})"
        params += ids
    states = list(states)
    if states:
        query += f" AND state IN ({', '.join('?' for _ in states)})"
        params += states
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with transaction() as db:
        return [_request(r) for r in db.execute(query, params).fetchall()]


def transition(action_id: str, *, expected_version: int, expected_states: Iterable[str], to_state: str, actor: str,
               reason: str, evidence: Optional[dict] = None, updates: Optional[dict] = None,
               now: Optional[datetime] = None) -> dict:
    """Compare-and-set state change plus one chained transition entry."""
    updates = dict(updates or {})
    illegal = set(updates) - _MUTABLE
    if illegal:
        raise ValueError(f"transition may not change {sorted(illegal)}")
    expected = list(expected_states)
    stamp = iso(now) if now else now_iso()
    sets = ["state = ?", "version = version + 1", "updated_at = ?"]
    params: list[Any] = [to_state, stamp]
    for key in sorted(updates):
        sets.append(f"{key} = ?")
        value = updates[key]
        params.append(json_param(value) if key in _JSON_COLUMNS else value)
    params += [action_id, expected_version, *expected]
    with transaction(write=True) as db:
        current = _request(db.execute(f"SELECT * FROM {table('action_requests')} WHERE action_id = ?", (action_id,)).fetchone())
        if current is None:
            raise ActionNotFound(action_id)
        cursor = db.execute(
            f"UPDATE {table('action_requests')} SET {', '.join(sets)} WHERE action_id = ? AND version = ? "
            f"AND state IN ({', '.join('?' for _ in expected)})", params)
        if cursor.rowcount != 1:
            raise ActionConflict(f"STALE_ACTION_VERSION: expected v{expected_version} in {expected}, found "
                                 f"v{current['version']} in {current['state']}")
        _append_transition(db, action_id=action_id, tenant_id=current["tenant_id"], from_state=current["state"],
                           to_state=to_state, actor=actor, reason=reason, evidence=evidence or {}, created_at=stamp)
        return _request(db.execute(f"SELECT * FROM {table('action_requests')} WHERE action_id = ?", (action_id,)).fetchone())


def annotate(action_id: str, *, expected_version: int, actor: str, reason: str, evidence: dict, outcome: dict) -> dict:
    """Record evidence on an action without changing its state (e.g. a
    compensation of a COMPLETED action). Same CAS and chain as a transition."""
    stamp = now_iso()
    with transaction(write=True) as db:
        current = _request(db.execute(f"SELECT * FROM {table('action_requests')} WHERE action_id = ?", (action_id,)).fetchone())
        if current is None:
            raise ActionNotFound(action_id)
        cursor = db.execute(f"UPDATE {table('action_requests')} SET outcome = ?, version = version + 1, updated_at = ? "
                            f"WHERE action_id = ? AND version = ?", (json_param(outcome), stamp, action_id, expected_version))
        if cursor.rowcount != 1:
            raise ActionConflict(f"STALE_ACTION_VERSION: expected v{expected_version}, found v{current['version']}")
        _append_transition(db, action_id=action_id, tenant_id=current["tenant_id"], from_state=current["state"],
                           to_state=current["state"], actor=actor, reason=reason, evidence=evidence, created_at=stamp)
        return _request(db.execute(f"SELECT * FROM {table('action_requests')} WHERE action_id = ?", (action_id,)).fetchone())


def list_transitions(action_id: str) -> list[dict]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('action_transitions')} WHERE action_id = ? ORDER BY entry_id", (action_id,)).fetchall()
    out = []
    for r in rows:
        rec = normalize_record(r)
        rec["evidence"] = decode_json(rec.get("evidence"), {})
        out.append(rec)
    return out


def verify_transition_chain(action_id: str) -> dict:
    entries = list_transitions(action_id)
    prev: Optional[str] = None
    for i, e in enumerate(entries):
        body = {k: e[k] for k in ("action_id", "tenant_id", "from_state", "to_state", "actor", "reason", "evidence",
                                  "prev_hash", "created_at")}
        if e["prev_hash"] != prev:
            return {"intact": False, "entries": len(entries), "break_at": i, "reason": "prev_hash does not link"}
        if canonical_hash(body) != e["entry_hash"]:
            return {"intact": False, "entries": len(entries), "break_at": i, "reason": "entry content changed"}
        prev = e["entry_hash"]
    return {"intact": True, "entries": len(entries), "head": prev}


def leased_past(now: datetime, states: Iterable[str], *, tenant_id: Optional[str] = None) -> list[dict]:
    states = list(states)
    if not states:
        return []
    query = f"SELECT * FROM {table('action_requests')} WHERE state IN ({', '.join('?' for _ in states)}) "
    params: list[Any] = [*states]
    if tenant_id is not None:
        query += "AND tenant_id = ? "
        params.append(tenant_id)
    query += "AND lease_expires_at IS NOT NULL AND lease_expires_at < ? ORDER BY lease_expires_at"
    params.append(iso(now))
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_request(r) for r in rows]


def expiring_before(tenant_id: str, moment: datetime, states: Iterable[str]) -> list[dict]:
    states = list(states)
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('action_requests')} WHERE tenant_id = ? AND state IN ({', '.join('?' for _ in states)}) "
            f"AND expires_at < ? ORDER BY expires_at", [tenant_id, *states, iso(moment)]).fetchall()
    return [_request(r) for r in rows]


# --------------------------------------------------------------------------- budget

BUDGET_SCOPES = ("ACTION", "PROJECT", "CLIENT", "TENANT_DAY", "TENANT_MONTH")


def set_budget_policy(*, tenant_id: str, scope_kind: str, scope_ref: str, currency: str, ceiling_minor: int, actor: str) -> dict:
    """Operator-managed ceiling. Not exposed through the API (a ceiling change is
    a governance change); used by provisioning, the CLI and tests."""
    if scope_kind not in BUDGET_SCOPES:
        raise ValueError(f"unknown budget scope {scope_kind}")
    if ceiling_minor < 0:
        raise ValueError("ceiling_minor must be >= 0")
    currency = currency.upper()
    with transaction(write=True) as db:
        db.execute(f"INSERT INTO {table('tenants')} (tenant_id, name) VALUES (?, ?) ON CONFLICT (tenant_id) DO NOTHING",
                   (tenant_id, tenant_id))
        db.execute(
            f"""INSERT INTO {table('action_budget_policies')} (policy_id, tenant_id, scope_kind, scope_ref, currency,
            ceiling_minor, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (tenant_id, scope_kind, scope_ref, currency) DO UPDATE SET ceiling_minor = excluded.ceiling_minor,
            created_by = excluded.created_by, created_at = excluded.created_at""",
            (f"bp-{uuid4().hex}", tenant_id, scope_kind, scope_ref, currency, int(ceiling_minor), actor, now_iso()))
        row = db.execute(f"SELECT * FROM {table('action_budget_policies')} WHERE tenant_id = ? AND scope_kind = ? AND scope_ref = ? "
                         f"AND currency = ?", (tenant_id, scope_kind, scope_ref, currency)).fetchone()
    return normalize_record(row)


def list_budget_policies(tenant_id: str) -> list[dict]:
    with transaction() as db:
        return [normalize_record(r) for r in db.execute(
            f"SELECT * FROM {table('action_budget_policies')} WHERE tenant_id = ? ORDER BY scope_kind, scope_ref, currency",
            (tenant_id,)).fetchall()]


def _applicable(policies: list[dict], *, tenant_id: str, project_id: str, client_id: Optional[str]) -> list[dict]:
    out = []
    for p in policies:
        kind, ref = p["scope_kind"], p["scope_ref"]
        if kind == "ACTION" and ref in {"*", project_id}:
            out.append(p)
        elif kind == "PROJECT" and ref == project_id:
            out.append(p)
        elif kind == "CLIENT" and client_id and ref == client_id:
            out.append(p)
        elif kind in {"TENANT_DAY", "TENANT_MONTH"} and ref == tenant_id:
            out.append(p)
    return out


def _usage(db: Any, policy: dict, *, tenant_id: str, project_id: str, client_id: Optional[str], currency: str,
           now: datetime) -> int:
    query = (f"SELECT COALESCE(SUM(CASE WHEN status = 'COMMITTED' THEN COALESCE(committed_minor, amount_minor) "
             f"ELSE amount_minor END), 0) AS used FROM {table('action_budget_reservations')} "
             f"WHERE tenant_id = ? AND currency = ? AND status IN ('RESERVED', 'COMMITTED')")
    params: list[Any] = [tenant_id, currency]
    kind = policy["scope_kind"]
    if kind == "PROJECT":
        query += " AND project_id = ?"
        params.append(project_id)
    elif kind == "CLIENT":
        query += " AND client_id = ?"
        params.append(client_id)
    elif kind == "TENANT_DAY":
        query += " AND created_at >= ?"
        params.append(iso(now.replace(hour=0, minute=0, second=0, microsecond=0)))
    elif kind == "TENANT_MONTH":
        query += " AND created_at >= ?"
        params.append(iso(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)))
    row = db.execute(query, params).fetchone()
    return int(normalize_record(row)["used"] or 0)


def reserve_budget(*, tenant_id: str, project_id: str, client_id: Optional[str], action_id: str, currency: str,
                   amount_minor: int, expires_at: datetime, now: datetime) -> dict:
    """Atomically check every applicable ceiling and reserve. Fails closed when
    no ceiling applies (NO_BUDGET_POLICY)."""
    if amount_minor < 0:
        raise ValueError("amount_minor must be >= 0")
    currency = currency.upper()
    stamp = iso(now)
    with transaction(write=True) as db:
        _lock(db, f"budget:{tenant_id}:{currency}")
        db.execute(f"UPDATE {table('action_budget_reservations')} SET status = 'EXPIRED', updated_at = ? "
                   f"WHERE tenant_id = ? AND status = 'RESERVED' AND expires_at < ?", (stamp, tenant_id, stamp))
        policies = [normalize_record(r) for r in db.execute(
            f"SELECT * FROM {table('action_budget_policies')} WHERE tenant_id = ? AND currency = ?", (tenant_id, currency)).fetchall()]
        applicable = _applicable(policies, tenant_id=tenant_id, project_id=project_id, client_id=client_id)
        if not applicable:
            raise BudgetExceeded("NO_BUDGET_POLICY", {"currency": currency, "reason": "no ceiling applies, so no spend is allowed"})
        breaches = []
        for p in applicable:
            used = 0 if p["scope_kind"] == "ACTION" else _usage(db, p, tenant_id=tenant_id, project_id=project_id,
                                                                client_id=client_id, currency=currency, now=now)
            if used + amount_minor > int(p["ceiling_minor"]):
                breaches.append({"scope_kind": p["scope_kind"], "scope_ref": p["scope_ref"], "ceiling_minor": int(p["ceiling_minor"]),
                                 "used_minor": used, "requested_minor": amount_minor})
        if breaches:
            raise BudgetExceeded("BUDGET_CEILING_EXCEEDED", {"currency": currency, "breaches": breaches})
        reservation_id = f"res-{uuid4().hex}"
        db.execute(
            f"""INSERT INTO {table('action_budget_reservations')} (reservation_id, tenant_id, project_id, client_id, action_id,
            currency, amount_minor, committed_minor, status, expires_at, evidence, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'RESERVED', ?, ?, ?, ?)""",
            (reservation_id, tenant_id, project_id, client_id, action_id, currency, int(amount_minor), iso(expires_at),
             json_param({"policies": [p["policy_id"] for p in applicable]}), stamp, stamp))
        return _reservation(db.execute(f"SELECT * FROM {table('action_budget_reservations')} WHERE reservation_id = ?",
                                       (reservation_id,)).fetchone())


def _reservation(row: Any) -> Optional[dict]:
    if row is None:
        return None
    rec = normalize_record(row)
    rec["evidence"] = decode_json(rec.get("evidence"), {})
    return rec


def get_reservation(reservation_id: str) -> Optional[dict]:
    with transaction() as db:
        return _reservation(db.execute(f"SELECT * FROM {table('action_budget_reservations')} WHERE reservation_id = ?",
                                       (reservation_id,)).fetchone())


def settle_reservation(reservation_id: str, *, status: str, committed_minor: Optional[int] = None,
                       evidence: Optional[dict] = None, expected_status: str = "RESERVED") -> dict:
    if status not in {"COMMITTED", "RELEASED", "EXPIRED", "REFUNDED"}:
        raise ValueError(f"unknown reservation status {status}")
    with transaction(write=True) as db:
        current = _reservation(db.execute(f"SELECT * FROM {table('action_budget_reservations')} WHERE reservation_id = ?",
                                          (reservation_id,)).fetchone())
        if current is None:
            raise ActionNotFound(reservation_id)
        merged = {**current["evidence"], **(evidence or {})}
        cursor = db.execute(
            f"UPDATE {table('action_budget_reservations')} SET status = ?, committed_minor = COALESCE(?, committed_minor), "
            f"evidence = ?, updated_at = ? WHERE reservation_id = ? AND status = ?",
            (status, committed_minor, json_param(merged), now_iso(), reservation_id, expected_status))
        if cursor.rowcount != 1:
            raise ActionConflict(f"reservation {reservation_id} is {current['status']}, not {expected_status}")
        return _reservation(db.execute(f"SELECT * FROM {table('action_budget_reservations')} WHERE reservation_id = ?",
                                       (reservation_id,)).fetchone())


def list_reservations(tenant_id: str, *, statuses: Iterable[str] = ()) -> list[dict]:
    query = f"SELECT * FROM {table('action_budget_reservations')} WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]
    statuses = list(statuses)
    if statuses:
        query += f" AND status IN ({', '.join('?' for _ in statuses)})"
        params += statuses
    with transaction() as db:
        return [_reservation(r) for r in db.execute(query + " ORDER BY created_at", params).fetchall()]


# --------------------------------------------------------------------------- freezes and settings


def create_freeze(*, tenant_id: str, scope_kind: str, scope_ref: str, reason: str, actor: str) -> dict:
    if scope_kind not in {"TENANT", "PROJECT"}:
        raise ValueError("scope_kind must be TENANT or PROJECT")
    freeze_id = f"frz-{uuid4().hex}"
    with transaction(write=True) as db:
        db.execute(f"INSERT INTO {table('tenants')} (tenant_id, name) VALUES (?, ?) ON CONFLICT (tenant_id) DO NOTHING",
                   (tenant_id, tenant_id))
        db.execute(f"""INSERT INTO {table('action_freezes')} (freeze_id, tenant_id, scope_kind, scope_ref, reason, frozen_by,
            frozen_at) VALUES (?, ?, ?, ?, ?, ?, ?)""", (freeze_id, tenant_id, scope_kind, scope_ref, reason, actor, now_iso()))
        return normalize_record(db.execute(f"SELECT * FROM {table('action_freezes')} WHERE freeze_id = ?", (freeze_id,)).fetchone())


def get_freeze(freeze_id: str) -> Optional[dict]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('action_freezes')} WHERE freeze_id = ?", (freeze_id,)).fetchone()
        return normalize_record(row) if row else None


def lift_freeze(freeze_id: str, *, actor: str, reason: str) -> dict:
    with transaction(write=True) as db:
        cursor = db.execute(f"UPDATE {table('action_freezes')} SET lifted_by = ?, lifted_at = ?, lift_reason = ? "
                            f"WHERE freeze_id = ? AND lifted_at IS NULL", (actor, now_iso(), reason, freeze_id))
        if cursor.rowcount != 1:
            raise ActionConflict(f"freeze {freeze_id} is not active")
        return normalize_record(db.execute(f"SELECT * FROM {table('action_freezes')} WHERE freeze_id = ?", (freeze_id,)).fetchone())


def active_freezes(tenant_id: str) -> list[dict]:
    with transaction() as db:
        return [normalize_record(r) for r in db.execute(
            f"SELECT * FROM {table('action_freezes')} WHERE tenant_id = ? AND lifted_at IS NULL ORDER BY frozen_at",
            (tenant_id,)).fetchall()]


def get_autonomy(project_id: str) -> Optional[dict]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('action_project_settings')} WHERE project_id = ?", (project_id,)).fetchone()
        return normalize_record(row) if row else None


def set_autonomy(*, tenant_id: str, project_id: str, autonomy: str, actor: str) -> dict:
    with transaction(write=True) as db:
        ensure_tenant_project(db, tenant_id, project_id)
        db.execute(f"""INSERT INTO {table('action_project_settings')} (project_id, tenant_id, autonomy, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT (project_id) DO UPDATE SET autonomy = excluded.autonomy,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at""",
                   (project_id, tenant_id, autonomy, actor, now_iso()))
        return normalize_record(db.execute(f"SELECT * FROM {table('action_project_settings')} WHERE project_id = ?",
                                           (project_id,)).fetchone())


# --------------------------------------------------------------------------- sandbox fake provider store


def _effect(row: Any) -> Optional[dict]:
    if row is None:
        return None
    rec = normalize_record(row)
    rec["body"] = decode_json(rec.get("body"), {})
    return rec


def sandbox_put(*, tenant_id: str, provider: str, operation: str, idempotency_key: str, target_ref: str, payload_hash: str,
                state: str, body: dict, cost_minor: int = 0, currency: Optional[str] = None) -> tuple[dict, bool]:
    stamp = now_iso()
    with transaction(write=True) as db:
        _lock(db, f"sandbox:{tenant_id}:{provider}:{idempotency_key}")
        existing = _effect(db.execute(f"SELECT * FROM {table('action_sandbox_effects')} WHERE tenant_id = ? AND provider = ? "
                                      f"AND idempotency_key = ?", (tenant_id, provider, idempotency_key)).fetchone())
        if existing is not None:
            return existing, False
        effect_id = f"sbx-{uuid4().hex}"
        db.execute(f"""INSERT INTO {table('action_sandbox_effects')} (effect_id, tenant_id, provider, operation, idempotency_key,
            target_ref, payload_hash, state, cost_minor, currency, body, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   (effect_id, tenant_id, provider, operation, idempotency_key, target_ref, payload_hash, state, int(cost_minor),
                    currency, json_param(body), stamp, stamp))
        return _effect(db.execute(f"SELECT * FROM {table('action_sandbox_effects')} WHERE effect_id = ?", (effect_id,)).fetchone()), True


def sandbox_get(*, tenant_id: str, provider: str, idempotency_key: str) -> Optional[dict]:
    with transaction() as db:
        return _effect(db.execute(f"SELECT * FROM {table('action_sandbox_effects')} WHERE tenant_id = ? AND provider = ? "
                                  f"AND idempotency_key = ?", (tenant_id, provider, idempotency_key)).fetchone())


def sandbox_set_state(effect_id: str, state: str, *, expected_state: str) -> dict:
    with transaction(write=True) as db:
        cursor = db.execute(f"UPDATE {table('action_sandbox_effects')} SET state = ?, updated_at = ? WHERE effect_id = ? AND state = ?",
                            (state, now_iso(), effect_id, expected_state))
        if cursor.rowcount != 1:
            raise ActionConflict(f"sandbox effect {effect_id} is not {expected_state}")
        return _effect(db.execute(f"SELECT * FROM {table('action_sandbox_effects')} WHERE effect_id = ?", (effect_id,)).fetchone())


def sandbox_list(tenant_id: str, *, provider: Optional[str] = None) -> list[dict]:
    query = f"SELECT * FROM {table('action_sandbox_effects')} WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]
    if provider:
        query += " AND provider = ?"
        params.append(provider)
    with transaction() as db:
        return [_effect(r) for r in db.execute(query + " ORDER BY created_at", params).fetchall()]


# --------------------------------------------------------------------------- clients


def create_client(*, tenant_id: str, display_name: str, slug: str, notes: str, actor: str) -> dict:
    stamp = now_iso()
    client_id = f"cli-{uuid4().hex[:20]}"
    with transaction(write=True) as db:
        db.execute(f"INSERT INTO {table('tenants')} (tenant_id, name) VALUES (?, ?) ON CONFLICT (tenant_id) DO NOTHING",
                   (tenant_id, tenant_id))
        if db.execute(f"SELECT 1 FROM {table('agency_clients')} WHERE tenant_id = ? AND slug = ?", (tenant_id, slug)).fetchone():
            raise ActionConflict(f"a client with slug {slug!r} already exists")
        db.execute(f"""INSERT INTO {table('agency_clients')} (client_id, tenant_id, display_name, slug, status, notes, created_by,
            created_at, updated_at) VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)""",
                   (client_id, tenant_id, display_name, slug, notes, actor, stamp, stamp))
        return normalize_record(db.execute(f"SELECT * FROM {table('agency_clients')} WHERE client_id = ?", (client_id,)).fetchone())


def get_client(client_id: str) -> Optional[dict]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('agency_clients')} WHERE client_id = ?", (client_id,)).fetchone()
        return normalize_record(row) if row else None


def list_clients(tenant_id: str) -> list[dict]:
    with transaction() as db:
        return [normalize_record(r) for r in db.execute(
            f"SELECT * FROM {table('agency_clients')} WHERE tenant_id = ? ORDER BY display_name", (tenant_id,)).fetchall()]


def set_client_status(client_id: str, status: str, *, expected: str) -> dict:
    with transaction(write=True) as db:
        cursor = db.execute(f"UPDATE {table('agency_clients')} SET status = ?, updated_at = ? WHERE client_id = ? AND status = ?",
                            (status, now_iso(), client_id, expected))
        if cursor.rowcount != 1:
            raise ActionConflict(f"client {client_id} is not {expected}")
        return normalize_record(db.execute(f"SELECT * FROM {table('agency_clients')} WHERE client_id = ?", (client_id,)).fetchone())


def link_project(*, tenant_id: str, client_id: str, project_id: str, actor: str) -> dict:
    with transaction(write=True) as db:
        ensure_tenant_project(db, tenant_id, project_id)
        current = db.execute(f"SELECT client_id FROM {table('agency_client_projects')} WHERE project_id = ?", (project_id,)).fetchone()
        if current is not None:
            if normalize_record(current)["client_id"] == client_id:
                return normalize_record(db.execute(f"SELECT * FROM {table('agency_client_projects')} WHERE project_id = ?",
                                                   (project_id,)).fetchone())
            raise ActionConflict("project is already linked to another client")
        db.execute(f"""INSERT INTO {table('agency_client_projects')} (project_id, client_id, tenant_id, linked_by, linked_at)
            VALUES (?, ?, ?, ?, ?)""", (project_id, client_id, tenant_id, actor, now_iso()))
        return normalize_record(db.execute(f"SELECT * FROM {table('agency_client_projects')} WHERE project_id = ?",
                                           (project_id,)).fetchone())


def client_for_project(project_id: str) -> Optional[str]:
    with transaction() as db:
        row = db.execute(f"SELECT client_id FROM {table('agency_client_projects')} WHERE project_id = ?", (project_id,)).fetchone()
        return normalize_record(row)["client_id"] if row else None


def projects_for_client(client_id: str) -> list[str]:
    with transaction() as db:
        return [normalize_record(r)["project_id"] for r in db.execute(
            f"SELECT project_id FROM {table('agency_client_projects')} WHERE client_id = ? ORDER BY linked_at", (client_id,)).fetchall()]


__all__ = [
    "ActionConflict", "ActionNotFound", "annotate", "BUDGET_SCOPES", "BudgetExceeded", "active_freezes", "client_for_project",
    "create_client", "create_freeze", "expiring_before", "find_by_key", "get_autonomy", "get_client", "get_freeze",
    "get_request", "get_reservation", "insert_request", "iso", "leased_past", "lift_freeze", "link_project",
    "list_budget_policies", "list_clients", "list_requests", "list_reservations", "list_transitions", "now_iso",
    "projects_for_client", "reserve_budget", "sandbox_get", "sandbox_list", "sandbox_put", "sandbox_set_state",
    "set_autonomy", "set_budget_policy", "set_client_status", "settle_reservation", "transition", "verify_transition_chain",
]
