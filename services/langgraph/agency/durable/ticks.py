"""One bounded, durable tick of the run FSM. A tick handles at most one job and then returns.

    1  acquire a scoped lease and fencing token        (claim_due_job, CAS on version)
    2  precheck authority, budget, capability, approval (handler.precheck)
    3  load the job spec and its immutable input hash
    4  compute a stable idempotency identity           (idempotency_key: no wall clock in it)
    5  persist the write intent before any side effect  (reserve_intent, unique on the key)
    6  dispatch only an available, authorised local capability
    7  read back the persisted effect                   (handler.observe)
    8  run the independent verifier                     (handler.verify)
    9  CAS-commit receipt and state under the fence     (commit_intent + transition)
    10 record telemetry and the next due time           (record_tick)
    11 release the lease                                (lease_owner cleared on the final transition)

An interrupted job (lease expired while in flight) is claimed into RECONCILING:
its open intent is reconciled against the target's pre-image before anything
is re-dispatched, so a crash after dispatch adopts the persisted effect instead
of repeating it. Exactly-once external effects would need provider
cooperation; for the local effects here the guarantee is at-least-once
dispatch with de-duplication by intent key and pre-image reconciliation.
"""

from __future__ import annotations

import hashlib
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional, Protocol
from uuid import uuid4

from services.langgraph.agency.execution.canonical import canonical_hash, canonical_bytes

from .fsm import RunState

TICK_VERSION = "amc-durable-tick/v1"
MAX_RETRIES = 3
RETRY_BACKOFF_S = (30, 120, 600)


def idempotency_key(*, tenant: str, project: str, job: str, logical_tick: int, operation: str, target: str,
                    input_hash: str, contract_version: str) -> str:
    """SHA256(canonical(tenant, project, job, logical_tick, operation, target, input_hash, contract_version))."""
    return hashlib.sha256(canonical_bytes({
        "tenant": tenant, "project": project, "job": job, "logical_tick": logical_tick, "operation": operation,
        "target": target, "input_hash": input_hash, "contract_version": contract_version,
    })).hexdigest()


class JobHandler(Protocol):
    operation: str
    contract_version: str
    retry_class: str  # RETRY_SAFE | COMPENSATABLE | NON_RETRYABLE

    def target(self, job: dict) -> str: ...
    def input_hash(self, job: dict) -> str: ...
    def precheck(self, job: dict) -> tuple[Optional[RunState], list[str]]: ...
    def environment_fingerprint(self, job: dict) -> str: ...
    def pre_image(self, job: dict) -> dict: ...
    def dispatch(self, job: dict) -> dict: ...
    def observe(self, job: dict, dispatched: dict) -> dict: ...
    def verify(self, job: dict, observation: dict) -> dict: ...
    def reconcile(self, job: dict, intent: dict) -> tuple[str, Optional[dict]]: ...
    def on_commit(self, job: dict, observation: dict, verification: dict) -> tuple[RunState, dict]: ...


@dataclass
class TickReport:
    trace_id: str
    outcome: str
    job_id: Optional[str] = None
    final_state: Optional[str] = None
    idempotency_key: Optional[str] = None
    dispatched: bool = False
    adopted: bool = False
    reasons: list[str] = field(default_factory=list)
    telemetry: dict = field(default_factory=dict)


Hook = Callable[[str], None]


def _fingerprint(operation: str, reason: str, env: str) -> str:
    code = reason.split(":")[0].split(" ")[0][:80]
    return canonical_hash({"operation": operation, "code": code, "env": env})[:24]


def _lag_ms(due_at: Optional[str], started: datetime) -> Optional[int]:
    if not due_at:
        return None
    due = datetime.fromisoformat(due_at)
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return max(0, int((started - due).total_seconds() * 1000))


def run_tick(*, worker_id: str, handlers: Mapping[str, JobHandler], now: Optional[datetime] = None,
             lease_seconds: int = 900, job_id: Optional[str] = None, project_id: Optional[str] = None,
             hook: Optional[Hook] = None) -> TickReport:
    from services.langgraph.persistence import durable_runs as store

    started_wall, started_mono = (now or datetime.now(timezone.utc)), time.monotonic()
    trace_id = uuid4().hex
    report = TickReport(trace_id=trace_id, outcome="NO_WORK")
    hook = hook or (lambda point: None)
    claimed = store.claim_due_job(worker_id=worker_id, now=started_wall, lease_seconds=lease_seconds, job_id=job_id,
                                  project_id=project_id)
    if claimed is None:
        store.record_tick(trace_id=trace_id, job=None, worker_id=worker_id, outcome="NO_WORK", telemetry={"trace_id": trace_id},
                          started_at=started_wall, finished_at=datetime.now(timezone.utc))
        return report

    job, entered = claimed
    token = int(job["lease_token"])
    report.job_id = job["job_id"]
    handler = handlers.get(job["kind"])
    tick_n = int(job["logical_tick"]) + 1
    telemetry: dict[str, Any] = {
        "trace_id": trace_id, "mission_id": job["spec"].get("mission_id"), "project_id": job["project_id"],
        "job_id": job["job_id"], "node_id": job["kind"], "capability": None, "execution_mode": "REAL_EXECUTION",
        "attempt": int(job["attempts"]) + 1, "logical_tick": tick_n, "observed_cost": "NOT_MEASURED",
        "artifact_hash": None, "verification_state": None, "failure_fingerprint": None,
        "wall_started_at": store.iso(started_wall), "tick_version": TICK_VERSION,
        "queue_lag_ms": _lag_ms(job.get("next_due_at"), started_wall), "resource_usage": {"gpu_memory": "NOT_MEASURED"},
    }

    def move(to: RunState, reason: str = "", **fields: Any) -> dict:
        nonlocal job
        job = store.transition(job, to, fencing_token=token, now=datetime.now(timezone.utc), reason=reason,
                               trace_id=trace_id, **fields)
        return job

    def release(to: RunState, reasons: list[str], *, retry: bool = False, **fields: Any) -> TickReport:
        due = datetime.now(timezone.utc) + timedelta(seconds=RETRY_BACKOFF_S[min(int(job["attempts"]), 2)] if retry else 300)
        move(to, "; ".join(reasons)[:500], lease_owner=None, lease_expires_at=None, last_reasons=list(reasons),
             next_due_at=store.iso(due), **fields)
        report.outcome, report.final_state, report.reasons = to.value, to.value, reasons
        return finish()

    def finish() -> TickReport:
        telemetry.update({"latency_ms": int((time.monotonic() - started_mono) * 1000), "checkpoint_version": job["version"],
                          "next_due_at": job.get("next_due_at"), "final_state": report.final_state,
                          "wall_finished_at": store.iso(datetime.now(timezone.utc))})
        report.telemetry = telemetry
        store.record_tick(trace_id=trace_id, job=job, worker_id=worker_id, outcome=report.outcome, telemetry=telemetry,
                          started_at=started_wall, finished_at=datetime.now(timezone.utc))
        return report

    def fail(reason: str, *, from_running: bool) -> TickReport:
        env = handler.environment_fingerprint(job) if handler else "none"
        fp = _fingerprint(handler.operation if handler else job["kind"], reason, env)
        telemetry["failure_fingerprint"] = fp
        seen = dict(job.get("failure_fingerprints") or {})
        repeat = fp in seen
        seen[fp] = {"count": int(seen.get(fp, {}).get("count", 0)) + 1, "env": env, "last_seen": store.iso(datetime.now(timezone.utc))}
        attempts = int(job["attempts"]) + 1
        retryable = handler is not None and handler.retry_class == "RETRY_SAFE"
        if retryable and attempts < min(MAX_RETRIES, int(job["max_attempts"])) and not repeat:
            return release(RunState.RETRY_PENDING, [reason], retry=True, attempts=attempts, failure_fingerprints=seen)
        why = [reason, "NEGATIVE_KNOWLEDGE: identical failure under unchanged environment"] if repeat else [reason]
        return release(RunState.DEAD_LETTER, why, attempts=attempts, failure_fingerprints=seen)

    if handler is None:
        move(RunState.PRECHECK, "precheck")
        return release(RunState.BLOCKED_ENVIRONMENT, [f"NO_HANDLER_FOR_KIND:{job['kind']}"])

    key = idempotency_key(tenant=job["tenant_id"], project=job["project_id"], job=job["job_id"], logical_tick=tick_n,
                          operation=handler.operation, target=handler.target(job), input_hash=handler.input_hash(job),
                          contract_version=handler.contract_version)
    report.idempotency_key = key
    observation: Optional[dict] = None

    if entered is RunState.LEASED:
        move(RunState.PRECHECK, "precheck")
        blocked, reasons = handler.precheck(job)
        if blocked is not None:
            return release(blocked, reasons)
        move(RunState.READY, "precheck passed")
        intent, created = store.reserve_intent(key=key, job=job, logical_tick=tick_n, operation=handler.operation,
                                               target=handler.target(job), input_hash=handler.input_hash(job),
                                               contract_version=handler.contract_version, retry_class=handler.retry_class,
                                               pre_image=handler.pre_image(job), fencing_token=token,
                                               now=datetime.now(timezone.utc))
        if not created:
            move(RunState.RECONCILING, "intent already exists for this tick")
            entered = RunState.RECONCILING
    if entered is RunState.RECONCILING:
        intent = store.get_intent(key)
        if intent is None:
            move(RunState.READY, "no intent was written before the interruption")
            intent, _ = store.reserve_intent(key=key, job=job, logical_tick=tick_n, operation=handler.operation,
                                             target=handler.target(job), input_hash=handler.input_hash(job),
                                             contract_version=handler.contract_version, retry_class=handler.retry_class,
                                             pre_image=handler.pre_image(job), fencing_token=token,
                                             now=datetime.now(timezone.utc))
        elif intent["status"] == "COMMITTED":
            observation = intent["receipt"].get("observation")
            report.adopted = True
            move(RunState.OBSERVING, "adopting the committed receipt; nothing re-dispatched")
        else:
            decision, adopted = handler.reconcile(job, intent)
            if decision == "ADOPT":
                observation = adopted
                report.adopted = True
                move(RunState.OBSERVING, "persisted effect found after the pre-image; adopted, not re-dispatched")
            elif decision == "REDO" and handler.retry_class == "RETRY_SAFE":
                move(RunState.READY, "no effect after the pre-image; safe to re-dispatch under the same intent")
            else:
                return release(RunState.DEAD_LETTER, [f"RECONCILE_{decision}: needs human intervention"])

    if observation is None:
        move(RunState.RUNNING, "dispatch")
        hook("after_intent")
        try:
            dispatched = handler.dispatch(job)
            report.dispatched = True
        except Exception as exc:  # noqa: BLE001 - every failure becomes a durable, fingerprinted state
            return fail(f"DISPATCH_FAILED:{type(exc).__name__}: {str(exc)[:200]}", from_running=True)
        hook("after_dispatch")
        if dispatched.get("blocked_state"):
            return release(RunState(dispatched["blocked_state"]), list(dispatched.get("reasons") or ["BLOCKED"]))
        if dispatched.get("failed"):
            return fail("RENDER_FAILED:" + "; ".join(dispatched.get("reasons") or [])[:300], from_running=True)
        move(RunState.OBSERVING, "dispatch returned; reading back")
        try:
            observation = handler.observe(job, dispatched)
        except Exception as exc:  # noqa: BLE001
            move(RunState.INCONCLUSIVE, f"readback failed: {type(exc).__name__}")
            return release(RunState.SCHEDULED, [f"READBACK_FAILED:{type(exc).__name__}"], retry=True)

    move(RunState.VERIFYING, "independent verification")
    verification = handler.verify(job, observation)
    telemetry.update({"artifact_hash": observation.get("content_hash"), "verification_state": verification.get("status"),
                      "capability": observation.get("route"),
                      "resource_usage": {"render_wall_ms": observation.get("wall_ms"), "gpu_memory": "NOT_MEASURED"}})
    if verification.get("status") != "PASSED":
        if verification.get("status") == "INCONCLUSIVE":
            move(RunState.INCONCLUSIVE, "verifier inconclusive")
            return release(RunState.SCHEDULED, ["VERIFICATION_INCONCLUSIVE"], retry=True)
        return fail("VERIFICATION_FAILED:" + ",".join(verification.get("findings") or [])[:300], from_running=False)

    move(RunState.COMMITTING, "verified; committing")
    hook("before_commit")
    receipt = {"observation": observation, "verification": verification, "trace_id": trace_id, "logical_tick": tick_n,
               "wall_committed_at": store.iso(datetime.now(timezone.utc))}
    current = store.get_intent(key)
    if current and current["status"] == "INTENT":
        store.commit_intent(key=key, receipt=receipt, fencing_token=token, job_id=job["job_id"], now=datetime.now(timezone.utc))
    final_state, extra = handler.on_commit(job, observation, verification)
    due = datetime.now(timezone.utc) + timedelta(seconds=int(job.get("recurrence_seconds") or 0))
    move(final_state, "committed", logical_tick=tick_n, attempts=0, lease_owner=None, lease_expires_at=None,
         next_due_at=store.iso(due), last_reasons=[], result={**extra, "idempotency_key": key})
    report.outcome, report.final_state = "COMMITTED", final_state.value
    return finish()


def format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception_only(type(exc), exc)).strip()


__all__ = ["JobHandler", "MAX_RETRIES", "TICK_VERSION", "TickReport", "idempotency_key", "run_tick"]
