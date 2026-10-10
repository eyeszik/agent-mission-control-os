"""Persistence for the durable run FSM: jobs, leases, fenced writes, intents, transitions, ticks.

Concurrency rules:

* A claim is a compare-and-set on ``version``; the winner's ``lease_token`` is
  incremented and becomes its fencing token.
* Every later write by that worker is conditioned on ``lease_token = <token>``,
  so a worker whose lease expired and was re-claimed can no longer write.
* An intent row is unique on its idempotency key; a second reservation of the
  same key returns the existing row instead of creating a duplicate effect.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from uuid import uuid4

from services.langgraph.agency.durable.fsm import CLAIMABLE, IN_FLIGHT, RunState, assert_transition
from services.langgraph.persistence.database import decode_json, json_param, normalize_record, table, transaction
from services.langgraph.persistence.tenancy import ensure_tenant_project


class StaleFence(RuntimeError):
    """The caller's lease was superseded; it must stop without writing."""


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _job(row: Any) -> Optional[dict]:
    if row is None:
        return None
    rec = normalize_record(row)
    for key, default in (("spec", {}), ("last_reasons", []), ("failure_fingerprints", {}), ("result", {})):
        rec[key] = decode_json(rec.get(key), default)
    return rec


def create_job(*, tenant_id: str, project_id: str, kind: str, spec: dict, spec_hash: str, requested_by: str,
               due_at: datetime, max_attempts: int = 3, recurrence_seconds: Optional[int] = None,
               job_id: Optional[str] = None) -> dict:
    job_id = job_id or f"djob-{uuid4().hex}"
    now = iso(datetime.now(timezone.utc))
    with transaction(write=True) as db:
        ensure_tenant_project(db, tenant_id, project_id)
        existing = db.execute(f"SELECT * FROM {table('durable_jobs')} WHERE job_id = ?", (job_id,)).fetchone()
        if existing is not None:
            found = _job(existing)
            if found["spec_hash"] != spec_hash or found["tenant_id"] != tenant_id or found["project_id"] != project_id:
                raise ValueError(f"job {job_id} already exists with a different spec or scope")
            return found
        db.execute(
            f"""INSERT INTO {table('durable_jobs')}
            (job_id, tenant_id, project_id, kind, spec, spec_hash, requested_by, state, logical_tick, version,
             lease_token, attempts, max_attempts, recurrence_seconds, next_due_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1, 0, 0, ?, ?, ?, ?, ?)""",
            (job_id, tenant_id, project_id, kind, json_param(spec), spec_hash, requested_by, RunState.SCHEDULED.value,
             max_attempts, recurrence_seconds, iso(due_at), now, now),
        )
        db.execute(
            f"""INSERT INTO {table('durable_transitions')}
            (job_id, tenant_id, project_id, from_state, to_state, fencing_token, logical_tick, reason, observed_at)
            VALUES (?, ?, ?, ?, ?, 0, 0, 'created', ?)""",
            (job_id, tenant_id, project_id, RunState.DORMANT.value, RunState.SCHEDULED.value, now),
        )
        return _job(db.execute(f"SELECT * FROM {table('durable_jobs')} WHERE job_id = ?", (job_id,)).fetchone())


def get_job(job_id: str) -> Optional[dict]:
    with transaction() as db:
        return _job(db.execute(f"SELECT * FROM {table('durable_jobs')} WHERE job_id = ?", (job_id,)).fetchone())


def claim_due_job(*, worker_id: str, now: datetime, lease_seconds: int, job_id: Optional[str] = None,
                  project_id: Optional[str] = None) -> Optional[tuple[dict, RunState]]:
    """Take one lease. Returns (job, entered_state): LEASED for due work, RECONCILING for an
    interrupted job whose lease expired. CAS on ``version`` makes concurrent claims safe."""
    stamp, expires = iso(now), iso(now + timedelta(seconds=lease_seconds))
    claimable = [s.value for s in CLAIMABLE]
    in_flight = [s.value for s in IN_FLIGHT]
    query = (f"SELECT * FROM {table('durable_jobs')} WHERE ((state IN ({','.join('?' * len(claimable))}) AND next_due_at <= ?) "
             f"OR (state IN ({','.join('?' * len(in_flight))}) AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?))")
    params: list[Any] = [*claimable, stamp, *in_flight, stamp]
    if job_id:
        query += " AND job_id = ?"
        params.append(job_id)
    if project_id:
        query += " AND project_id = ?"
        params.append(project_id)
    query += " ORDER BY next_due_at, job_id LIMIT 5"
    with transaction() as db:
        candidates = [_job(r) for r in db.execute(query, params).fetchall()]
    for job in candidates:
        current = RunState(job["state"])
        entered = RunState.RECONCILING if current in IN_FLIGHT else RunState.LEASED
        assert_transition(current, entered)
        with transaction(write=True) as db:
            cur = db.execute(
                f"""UPDATE {table('durable_jobs')} SET state = ?, lease_owner = ?, lease_token = lease_token + 1,
                lease_expires_at = ?, version = version + 1, updated_at = ? WHERE job_id = ? AND version = ?""",
                (entered.value, worker_id, expires, stamp, job["job_id"], job["version"]),
            )
            if cur.rowcount != 1:
                continue  # another worker won the CAS
            claimed = _job(db.execute(f"SELECT * FROM {table('durable_jobs')} WHERE job_id = ?", (job["job_id"],)).fetchone())
            db.execute(
                f"""INSERT INTO {table('durable_transitions')}
                (job_id, tenant_id, project_id, from_state, to_state, fencing_token, logical_tick, reason, observed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (claimed["job_id"], claimed["tenant_id"], claimed["project_id"], current.value, entered.value,
                 claimed["lease_token"], claimed["logical_tick"], f"claimed by {worker_id}", stamp),
            )
            return claimed, entered
    return None


# Column names are interpolated into SQL, so only these may be set by a transition.
_MUTABLE_FIELDS = frozenset({"lease_owner", "lease_expires_at", "attempts", "logical_tick", "next_due_at", "last_reasons",
                             "failure_fingerprints", "result"})


def transition(job: dict, to: RunState, *, fencing_token: int, now: datetime, reason: str = "", trace_id: Optional[str] = None,
               **fields: Any) -> dict:
    """Fenced, logged state change. Raises StaleFence if the lease was superseded."""
    with transaction() as db:
        current = _job(db.execute(f"SELECT * FROM {table('durable_jobs')} WHERE job_id = ?", (job["job_id"],)).fetchone())
    if current is None or int(current["lease_token"]) != int(fencing_token):
        raise StaleFence(f"job {job['job_id']}: fencing token {fencing_token} superseded")
    assert_transition(current["state"], to)
    sets = ["state = ?", "version = version + 1", "updated_at = ?"]
    params: list[Any] = [to.value, iso(now)]
    unknown = set(fields) - _MUTABLE_FIELDS
    if unknown:
        raise ValueError(f"transition cannot set {sorted(unknown)}")
    for key, value in fields.items():
        sets.append(f"{key} = ?")
        params.append(json_param(value) if isinstance(value, (dict, list, tuple)) else value)
    with transaction(write=True) as db:
        cur = db.execute(
            f"UPDATE {table('durable_jobs')} SET {', '.join(sets)} WHERE job_id = ? AND lease_token = ? AND state = ?",
            (*params, job["job_id"], fencing_token, current["state"]),
        )
        if cur.rowcount != 1:
            raise StaleFence(f"job {job['job_id']}: concurrent change lost the fence")
        updated = _job(db.execute(f"SELECT * FROM {table('durable_jobs')} WHERE job_id = ?", (job["job_id"],)).fetchone())
        db.execute(
            f"""INSERT INTO {table('durable_transitions')}
            (job_id, tenant_id, project_id, from_state, to_state, fencing_token, logical_tick, reason, trace_id, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (updated["job_id"], updated["tenant_id"], updated["project_id"], current["state"], to.value, fencing_token,
             updated["logical_tick"], reason[:500], trace_id, iso(now)),
        )
        return updated


def operator_move(job_id: str, to: RunState, *, actor: str, reason: str, now: Optional[datetime] = None) -> dict:
    """A human operator's state change (e.g. DEAD_LETTER -> PAUSED -> SCHEDULED). Refused while a worker
    holds an unexpired lease; otherwise fenced on the job's current token like any other move."""
    moment = now or datetime.now(timezone.utc)
    job = get_job(job_id)
    if job is None:
        raise LookupError(job_id)
    if RunState(job["state"]) in IN_FLIGHT and job.get("lease_expires_at") and job["lease_expires_at"] > iso(moment):
        raise StaleFence(f"job {job_id} is leased until {job['lease_expires_at']}")
    fields = {"next_due_at": iso(moment)} if to is RunState.SCHEDULED else {}
    return transition(job, to, fencing_token=int(job["lease_token"]), now=moment, reason=f"operator {actor}: {reason}"[:500],
                      **fields)


def reserve_intent(*, key: str, job: dict, logical_tick: int, operation: str, target: str, input_hash: str,
                   contract_version: str, retry_class: str, pre_image: dict, fencing_token: int, now: datetime) -> tuple[dict, bool]:
    """Write-ahead intent. Returns (row, created). An existing key is returned untouched."""
    with transaction(write=True) as db:
        row = db.execute(f"SELECT * FROM {table('durable_intents')} WHERE idempotency_key = ?", (key,)).fetchone()
        if row is not None:
            return _intent(row), False
        db.execute(
            f"""INSERT INTO {table('durable_intents')}
            (idempotency_key, job_id, tenant_id, project_id, logical_tick, operation, target, input_hash, contract_version,
             retry_class, pre_image, status, fencing_token, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'INTENT', ?, ?)""",
            (key, job["job_id"], job["tenant_id"], job["project_id"], logical_tick, operation, target, input_hash,
             contract_version, retry_class, json_param(pre_image), fencing_token, iso(now)),
        )
        return _intent(db.execute(f"SELECT * FROM {table('durable_intents')} WHERE idempotency_key = ?", (key,)).fetchone()), True


def _intent(row: Any) -> dict:
    rec = normalize_record(row)
    rec["pre_image"] = decode_json(rec.get("pre_image"), {})
    rec["receipt"] = decode_json(rec.get("receipt"), {})
    return rec


def get_intent(key: str) -> Optional[dict]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('durable_intents')} WHERE idempotency_key = ?", (key,)).fetchone()
    return _intent(row) if row is not None else None


def commit_intent(*, key: str, receipt: dict, fencing_token: int, job_id: str, now: datetime) -> None:
    """Commit only while still holding the job's fence; never overwrite a committed receipt."""
    with transaction(write=True) as db:
        job = db.execute(f"SELECT lease_token FROM {table('durable_jobs')} WHERE job_id = ?", (job_id,)).fetchone()
        if job is None or int(normalize_record(job)["lease_token"]) != int(fencing_token):
            raise StaleFence(f"job {job_id}: fence lost before commit")
        cur = db.execute(
            f"""UPDATE {table('durable_intents')} SET status = 'COMMITTED', receipt = ?, committed_at = ?
            WHERE idempotency_key = ? AND status = 'INTENT'""",
            (json_param(receipt), iso(now), key),
        )
        if cur.rowcount != 1:
            raise StaleFence(f"intent {key[:12]} is no longer open")


def list_intents(job_id: str) -> list[dict]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('durable_intents')} WHERE job_id = ? ORDER BY logical_tick, created_at",
                          (job_id,)).fetchall()
    return [_intent(r) for r in rows]


def list_transitions(job_id: str) -> list[dict]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('durable_transitions')} WHERE job_id = ? ORDER BY transition_id",
                          (job_id,)).fetchall()
    return [normalize_record(r) for r in rows]


def record_tick(*, trace_id: str, job: Optional[dict], worker_id: str, outcome: str, telemetry: dict,
                started_at: datetime, finished_at: datetime) -> None:
    with transaction(write=True) as db:
        db.execute(
            f"""INSERT INTO {table('durable_ticks')}
            (trace_id, job_id, tenant_id, project_id, worker_id, logical_tick, outcome, telemetry, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trace_id, (job or {}).get("job_id"), (job or {}).get("tenant_id"), (job or {}).get("project_id"), worker_id,
             (job or {}).get("logical_tick"), outcome, json_param(telemetry), iso(started_at), iso(finished_at)),
        )


def list_ticks(job_id: str) -> list[dict]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('durable_ticks')} WHERE job_id = ? ORDER BY started_at", (job_id,)).fetchall()
    out = []
    for r in rows:
        rec = normalize_record(r)
        rec["telemetry"] = decode_json(rec.get("telemetry"), {})
        out.append(rec)
    return out


def list_project_ticks(project_id: str) -> list[dict]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('durable_ticks')} WHERE project_id = ? ORDER BY started_at",
                          (project_id,)).fetchall()
    out = []
    for r in rows:
        rec = normalize_record(r)
        rec["telemetry"] = decode_json(rec.get("telemetry"), {})
        out.append(rec)
    return out


def jobs_for_project(project_id: str, states: Iterable[str] = ()) -> list[dict]:
    query, params = f"SELECT * FROM {table('durable_jobs')} WHERE project_id = ?", [project_id]
    states = list(states)
    if states:
        query += f" AND state IN ({','.join('?' * len(states))})"
        params += states
    with transaction() as db:
        return [_job(r) for r in db.execute(query + " ORDER BY created_at", params).fetchall()]


__all__ = ["StaleFence", "claim_due_job", "commit_intent", "create_job", "get_intent", "get_job", "iso", "jobs_for_project",
           "list_intents", "operator_move", "list_project_ticks", "list_ticks", "list_transitions", "record_tick", "reserve_intent",
           "transition"]
