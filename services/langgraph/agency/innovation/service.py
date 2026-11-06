"""ProjectOS-backed H02 simulation, using canonical durable ticks and CAS.

Only bounded offline fixture compilation is supported. The transaction encloses
the durable intent, result revision and receipt; an interrupted request rolls
back relational state. Content-addressed orphan bytes are harmless and reusable.
No experiment is executed, and no simulation supplies evidence or approval.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from services.langgraph.agency.durable.fsm import RunState
from services.langgraph.agency.durable.ticks import run_tick
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.kernel.roles import assert_role_may_produce
from services.langgraph.agency.project_os.storage import StorageAdapter, StorageIntegrityError
from services.langgraph.api.routes._project_common import authorize_project_access
from services.langgraph.persistence import durable_runs
from services.langgraph.persistence.agency_kernel import StaleArtifactVersionError, get_artifact
from services.langgraph.persistence.database import atomic_transaction, table, transaction
from services.langgraph.persistence.idempotency import complete_idempotency, reserve_idempotency
from services.langgraph.persistence.projects import create_project_artifact, project_artifact_id, revise_project_artifact
from services.langgraph.security.auth import Principal

from .contracts import Contract, InnovationBrief, RunResult

KIND = "unbound_innovation_simulation"
SUBTYPE = "innovation_run"
MAX_BYTES = 512 * 1024
RUN_ID = re.compile(r"^ir-[0-9a-f]{32}$")


class RunDocument(Contract):
    brief: InnovationBrief
    input_hash: str
    run: RunResult

    @model_validator(mode="after")
    def bind_inputs(self):
        mode = "GENERAL" if self.brief.mode == "AUTO" else self.brief.mode
        if self.input_hash != canonical_hash(self.brief) or self.run.objective != self.brief.objective:
            raise ValueError("innovation result does not match the admitted brief")
        if self.run.mode != mode or self.run.simulation != (self.brief.provider == "simulated"):
            raise ValueError("innovation result mode or provider does not match admission")
        return self


class RunEnvelope(Contract):
    run: RunResult
    version: int = Field(ge=1)
    artifact_id: str
    content_hash: str


class RunSummary(Contract):
    run_id: str
    version: int = Field(ge=1)
    status: str
    phase: str
    objective: str
    simulation: bool


class RunListing(Contract):
    runs: list[RunSummary] = Field(max_length=100)
    total: int = Field(ge=0)


class TickRequest(Contract):
    expected_version: int = Field(ge=1, le=2**31 - 1)


class ControlRequest(TickRequest):
    action: Literal["pause", "resume", "cancel"]


def _artifact_id(project_id: str, run_id: str) -> str:
    if not RUN_ID.fullmatch(run_id):
        raise HTTPException(404, "Innovation run not found")
    return project_artifact_id(project_id, run_id)


def _bytes(document: RunDocument) -> bytes:
    data = document.model_dump_json().encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("innovation document exceeds bounded storage size")
    return data


def _read(principal: Principal, project_id: str, run_id: str, adapter: StorageAdapter) -> tuple[RunDocument, dict]:
    authorize_project_access(principal, project_id)
    head = get_artifact(_artifact_id(project_id, run_id))
    if not head or head["tenant_id"] != principal.tenant_id or head["project_id"] != project_id or head.get("subtype") != SUBTYPE:
        raise HTTPException(404, "Innovation run not found")
    data = adapter.get_bytes(head["content_location"])
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != head["content_hash"]:
        raise StorageIntegrityError("innovation artifact bytes differ from the recorded head")
    document = RunDocument.model_validate_json(data)
    if document.run.run_id != run_id or document.input_hash != canonical_hash(document.brief):
        raise StorageIntegrityError("innovation document identity mismatch")
    return document, head


def _envelope(document: RunDocument, head: dict) -> dict:
    return {"run": document.run.model_dump(mode="json"), "version": int(head["version"]),
            "artifact_id": head["artifact_id"], "content_hash": head["content_hash"]}


def get_run(principal: Principal, project_id: str, run_id: str, adapter: StorageAdapter) -> dict:
    return _envelope(*_read(principal, project_id, run_id, adapter))


def _check_version(head: dict, expected: int) -> None:
    if int(head["version"]) != expected:
        raise StaleArtifactVersionError("innovation run changed; refresh before retrying")


def _save(principal: Principal, project_id: str, document: RunDocument, expected: int, adapter: StorageAdapter) -> dict:
    revise_project_artifact(project_id=project_id, artifact_id=_artifact_id(project_id, document.run.run_id),
                            actor=principal.user_id, adapter=adapter, expected_version=expected,
                            content_text=_bytes(document).decode("utf-8"))
    return get_run(principal, project_id, document.run.run_id, adapter)


def create_run(principal: Principal, project_id: str, brief: InnovationBrief, key: str, adapter: StorageAdapter) -> dict:
    from .compiler import received_run

    authorize_project_access(principal, project_id)
    assert_role_may_produce("market_researcher", "research_brief")
    if not key.strip() or len(key) > 128:
        raise ValueError("Idempotency-Key must contain 1 to 128 characters")
    scope = f"{principal.tenant_id}:{principal.user_id}:innovation:{project_id}"
    run_id = "ir-" + canonical_hash({"scope": scope, "key": key})[:32]
    with atomic_transaction():
        reservation = reserve_idempotency(scope, key, canonical_hash(brief))
        if reservation["state"] in {"conflict", "in_progress"}:
            raise HTTPException(409, "Idempotency-Key is in use or has different input")
        if reservation["state"] == "replay":
            return get_run(principal, project_id, run_id, adapter)
        return _create_reserved(principal, project_id, brief, run_id, scope, key, adapter, received_run)


def _create_reserved(principal, project_id, brief, run_id, scope, key, adapter, received_run):
    head = get_artifact(_artifact_id(project_id, run_id))
    if head is not None:
        document, _ = _read(principal, project_id, run_id, adapter)
        if document.input_hash != canonical_hash(brief):
            raise HTTPException(409, "Idempotency-Key has different persisted input")
    else:
        document = RunDocument(brief=brief, input_hash=canonical_hash(brief), run=received_run(brief, run_id))
        create_project_artifact(tenant_id=principal.tenant_id, project_id=project_id, actor=principal.user_id,
                                artifact_key=run_id, artifact_type="research_brief", subtype=SUBTYPE, adapter=adapter,
                                content_text=_bytes(document).decode("utf-8"), v2={"mime_type": "application/json", "media_type": "data"})
        durable_runs.create_job(tenant_id=principal.tenant_id, project_id=project_id, kind=KIND,
                                spec={"run_id": run_id, "input_hash": document.input_hash},
                                spec_hash=document.input_hash, requested_by=principal.user_id,
                                due_at=datetime.now(timezone.utc), max_attempts=2, job_id=run_id)
    response = get_run(principal, project_id, run_id, adapter)
    complete_idempotency(scope, key, {"run_id": run_id})
    return response


def list_runs(principal: Principal, project_id: str, adapter: StorageAdapter, *, limit: int = 20, offset: int = 0) -> dict:
    authorize_project_access(principal, project_id)
    limit, offset = max(1, min(limit, 100)), max(0, min(offset, 100000))
    condition = "tenant_id = ? AND project_id = ? AND subtype = ?"
    params = (principal.tenant_id, project_id, SUBTYPE)
    with transaction() as db:
        count = db.execute(f"SELECT COUNT(*) AS n FROM {table('agency_artifacts')} WHERE {condition}", params).fetchone()
        rows = db.execute(f"SELECT metadata FROM {table('agency_artifacts')} WHERE {condition} ORDER BY created_at DESC, artifact_id LIMIT ? OFFSET ?",
                          (*params, limit, offset)).fetchall()
    from services.langgraph.persistence.database import decode_json
    runs = []
    for row in rows:
        run_id = decode_json(row["metadata"], {})["artifact_key"]
        envelope = get_run(principal, project_id, run_id, adapter)
        summary = {k: envelope["run"][k] for k in ("run_id", "status", "phase", "objective", "simulation")}
        runs.append({**summary, "version": envelope["version"]})
    return {"runs": runs, "total": int(count["n"])}


class SimulationHandler:
    operation = "innovation.compile_simulation"
    contract_version = "unbound-h02/simulation-v1"
    retry_class = "RETRY_SAFE"

    def __init__(self, principal, project_id, document, version, adapter):
        self.principal, self.project_id, self.document = principal, project_id, document
        self.version, self.adapter = version, adapter

    def target(self, job):
        return _artifact_id(self.project_id, self.document.run.run_id)

    def input_hash(self, job):
        return self.document.input_hash

    def precheck(self, job):
        current, head = _read(self.principal, self.project_id, self.document.run.run_id, self.adapter)
        _check_version(head, self.version)
        if job["tenant_id"] != self.principal.tenant_id or current.input_hash != job["spec_hash"]:
            return RunState.BLOCKED_AUTHORITY, ["SCOPE_OR_INPUT_MISMATCH"]
        if current.brief.provider != "simulated":
            return RunState.BLOCKED_PROVIDER, ["PROVIDER_GAP"]
        return None, []

    def environment_fingerprint(self, job):
        return self.contract_version

    def pre_image(self, job):
        return {"artifact_id": self.target(job), "version": self.version, "simulation": True}

    def dispatch(self, job):
        from .compiler import compile_run
        try:
            result = compile_run(self.document.brief, self.document.run.run_id)
            candidate = RunDocument(brief=self.document.brief, input_hash=self.document.input_hash, run=result)
            stored = self.adapter.put_bytes(tenant_id=self.principal.tenant_id, project_id=self.project_id, data=_bytes(candidate))
            return {"storage_uri": stored.storage_uri, "content_hash": stored.content_hash}
        except Exception as exc:  # Bounded local compiler fault, never a remote unknown write.
            return {"failed": True, "reasons": [type(exc).__name__]}

    def observe(self, job, dispatched):
        try:
            data = self.adapter.get_bytes(dispatched["storage_uri"])
            if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != dispatched["content_hash"]:
                raise StorageIntegrityError("simulation candidate byte hash mismatch")
            return {**dispatched, "document": json.loads(data), "simulation": True, "experiments_executed": False}
        except Exception as exc:  # Retain the refusal in a durable, bounded verification failure.
            return {"failure": type(exc).__name__}

    def verify(self, job, observation):
        try:
            candidate = RunDocument.model_validate(observation["document"])
            valid = candidate.input_hash == self.document.input_hash and candidate.run.run_id == self.document.run.run_id
            valid = valid and canonical_hash(candidate.brief) == canonical_hash(self.document.brief)
            valid = valid and candidate.run.status == "COMPLETED" and candidate.run.simulation
        except (ValueError, KeyError):
            valid = False
        return {"status": "PASSED" if valid else "FAILED", "scope": "SIMULATED_STRUCTURAL_ONLY"}

    def reconcile(self, job, intent):
        # The only dispatch effect is immutable content-addressed fixture bytes.
        # Safe to regenerate; authoritative revision/receipt are one transaction.
        return "REDO", None

    def on_commit(self, job, observation, verification):
        candidate = RunDocument.model_validate(observation["document"])
        _save(self.principal, self.project_id, candidate, self.version, self.adapter)
        return RunState.DORMANT, {"simulation": True, "artifact_id": self.target(job), "experiments_executed": False}


def tick_run(principal: Principal, project_id: str, run_id: str, expected_version: int, adapter: StorageAdapter) -> dict:
    from .compiler import compile_run
    with atomic_transaction():
        document, head = _read(principal, project_id, run_id, adapter)
        _check_version(head, expected_version)
        if document.run.status in {"COMPLETED", "BLOCKED", "CANCELLED"}:
            return _envelope(document, head)
        if document.run.status == "PAUSED":
            raise HTTPException(409, "Resume this run before advancing")
        handler = SimulationHandler(principal, project_id, document, expected_version, adapter)
        report = run_tick(worker_id=f"innovation:{principal.user_id}", handlers={KIND: handler}, job_id=run_id,
                          project_id=project_id, lease_seconds=60)
        if report.outcome == "UNCONFIRMED":
            report.final_state = _settle_local_fault(run_id)
        if report.final_state == RunState.BLOCKED_PROVIDER.value:
            document.run = compile_run(document.brief, run_id)
            return _save(principal, project_id, document, expected_version, adapter)
        if report.final_state == RunState.DEAD_LETTER.value:
            values = document.run.model_dump(mode="json")
            values.update(status="BLOCKED", phase="RETRY_EXHAUSTED")
            values["limitations"] = [*values["limitations"], "Bounded simulation retries exhausted; inspect durable tick evidence."]
            document.run = RunResult.model_validate(values)
            return _save(principal, project_id, document, expected_version, adapter)
        if report.outcome == "COMMITTED":
            return get_run(principal, project_id, run_id, adapter)
    # Preserve canonical retry/unknown-outcome state before returning a refusal.
    raise HTTPException(409, "Innovation tick pending recovery; inspect durable tick evidence before retrying")


def _settle_local_fault(run_id: str) -> str:
    """Bound unknown outcomes only for this pure compiler, never remote effects.

    Its sole dispatch effect is reusable immutable bytes. A second bounded tick
    reconciles by safely regenerating them; the canonical fence remains in force.
    """
    job = durable_runs.get_job(run_id)
    attempts = int(job["attempts"]) + 1
    exhausted = attempts >= min(2, int(job["max_attempts"]))
    state = RunState.DEAD_LETTER if exhausted else RunState.RECONCILING
    now = datetime.now(timezone.utc)
    durable_runs.transition(job, state, fencing_token=int(job["lease_token"]), now=now,
                            reason="bounded offline compiler recovery", attempts=attempts,
                            lease_owner=None, lease_expires_at=durable_runs.iso(now),
                            last_reasons=["SIMULATED_LOCAL_COMPILER_FAULT"])
    return state.value


def control_run(principal: Principal, project_id: str, run_id: str, req: ControlRequest, adapter: StorageAdapter) -> dict:
    mapping = {"pause": ("RECEIVED", "PAUSED", RunState.PAUSED),
               "resume": ("PAUSED", "RECEIVED", RunState.SCHEDULED),
               "cancel": ("RECEIVED", "CANCELLED", RunState.STOPPED)}
    with atomic_transaction():
        document, head = _read(principal, project_id, run_id, adapter)
        _check_version(head, req.expected_version)
        before, after, state = mapping[req.action]
        if document.run.status != before and not (req.action == "cancel" and document.run.status == "PAUSED"):
            raise HTTPException(409, "Control is unavailable for the current run state")
        durable_runs.operator_move(run_id, state, actor=principal.user_id, reason=f"innovation {req.action}")
        document.run = RunResult.model_validate({**document.run.model_dump(mode="json"), "status": after, "phase": after})
        return _save(principal, project_id, document, req.expected_version, adapter)
