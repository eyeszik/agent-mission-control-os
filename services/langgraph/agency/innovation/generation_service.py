"""Immutable generation intent, canonical approval and non-replayable durable invocation.

Network work never runs inside a joined database transaction. Unknown invocation
outcomes remain RECONCILING and are never re-dispatched by this adapter.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from services.langgraph.agency.durable.fsm import RunState
from services.langgraph.agency.durable.ticks import run_tick
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.intake.release import artifact_release_verdict, open_artifact_approval
from services.langgraph.agency.kernel.roles import assert_role_may_produce
from services.langgraph.agency.project_os.storage import StorageAdapter, StorageIntegrityError
from services.langgraph.api.routes._project_common import authorize_project_access
from services.langgraph.persistence import durable_runs
from services.langgraph.persistence.agency_kernel import get_artifact, StaleArtifactVersionError
from services.langgraph.persistence.approvals import list_approvals_for_subject_refs
from services.langgraph.persistence.database import atomic_transaction
from services.langgraph.persistence.projects import create_project_artifact, project_artifact_id
from services.langgraph.security.auth import Principal
from services.langgraph.security.approval_authority import run_initiator
from services.langgraph.persistence.runs import get_run_record

from .contracts import Contract, InnovationBrief
from .generation import GenerationResult, GenerationSpec, create_spec, invoke_generation, provider_blocker
from .service import _read, _check_version, MAX_BYTES

POLICY = "unbound-generation/v1"
KIND = "unbound_live_generation"
PURPOSE = "INNOVATION_GENERATION"


class GenerationPlan(Contract):
    schema_version: Literal["unbound-generation-plan/v1"] = "unbound-generation-plan/v1"
    run_id: str
    brief: InnovationBrief
    spec: GenerationSpec

    @model_validator(mode="after")
    def bind_brief(self):
        if self.run_id != self.spec.run_id or canonical_hash(self.brief) != self.spec.brief_hash:
            raise ValueError("Generation plan differs from its admitted brief")
        if self.brief.provider != "live":
            raise ValueError("Generation requires an explicitly live brief")
        return self


class GenerationOutput(Contract):
    schema_version: Literal["unbound-generation-output/v1"] = "unbound-generation-output/v1"
    plan_hash: str
    result: GenerationResult


class GenerationEnvelope(Contract):
    schema_version: Literal["unbound-generation-stage/v1"] = "unbound-generation-stage/v1"
    artifact_id: str
    version: int = Field(ge=1)
    content_hash: str
    job_id: str
    spec: GenerationSpec
    approval: dict | None
    status: str
    reasons: list[str]
    output: GenerationResult | None


def _key(run_id: str) -> str:
    return "ig-" + canonical_hash({"run": run_id})[:28]


def _output_key(head: dict) -> str:
    return "igo-" + head["content_hash"][:28]


def _read_plan(principal: Principal, project: str, run_id: str, adapter: StorageAdapter):
    document, source = _read(principal, project, run_id, adapter)
    head = get_artifact(project_artifact_id(project, _key(run_id)))
    if not head or (head["tenant_id"], head["project_id"], head.get("subtype")) != (principal.tenant_id, project, "innovation_generation_plan"):
        raise HTTPException(404, "Generation has not been prepared")
    data = _read_bytes(head, adapter)
    plan = GenerationPlan.model_validate_json(data)
    if plan.run_id != run_id or plan.spec.run_id != run_id or canonical_hash(plan.brief) != plan.spec.brief_hash:
        raise StorageIntegrityError("Generation plan identity mismatch")
    return plan, head, document, source


def _read_bytes(head: dict, adapter: StorageAdapter) -> bytes:
    data = adapter.get_bytes(head["content_location"])
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != head["content_hash"]:
        raise StorageIntegrityError("Generation bytes differ from their current artifact head")
    return data


def _approval(head: dict, project: str) -> dict | None:
    approvals = list_approvals_for_subject_refs(project, [head["artifact_id"]])
    matching = [a for a in approvals if a.get("subject_hash") == head["content_hash"] and a.get("subject_version_ref") == str(head["version"])
                and a.get("subject_type") == PURPOSE and a.get("policy_version") == POLICY]
    return next((a for a in matching if a.get("status") == "resolved" and a.get("decision") == "approve"), matching[-1] if matching else None)


def _reasons(principal: Principal, project: str, plan: GenerationPlan, head: dict, document, source: dict) -> list[str]:
    reasons = []
    spec = plan.spec
    if (source["artifact_id"], int(source["version"]), source["content_hash"]) != (spec.source_artifact_id, spec.source_version, spec.source_hash):
        reasons.append("SOURCE_VERSION_STALE")
    if document.run.status in {"CANCELLED", "PAUSED"}:
        reasons.append("SOURCE_RUN_" + document.run.status)
    if canonical_hash(document.brief) != spec.brief_hash:
        reasons.append("BRIEF_CHANGED")
    approval = _approval(head, project)
    if approval is None:
        reasons.append("APPROVAL_REQUIRED")
    else:
        verdict = artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=head["artifact_id"],
            verified_version=int(head["version"]), verified_hash=head["content_hash"], approval_id=approval["approval_id"],
            tenant_id=principal.tenant_id, project_id=project)
        reasons.extend(verdict.reasons)
        if approval.get("status") == "resolved" and approval.get("decision") == "approve":
            anchor = get_run_record(approval["run_id"])
            initiator = run_initiator(anchor) if anchor else None
            if not initiator or not approval.get("reviewer") or approval["reviewer"] == initiator:
                reasons.append("GENERATION_SEPARATION_OF_DUTIES")
        if approval.get("subject_ref") != head["artifact_id"]:
            reasons.append("APPROVAL_TARGET_MISMATCH")
    blocker = provider_blocker(spec)
    if blocker:
        reasons.append(blocker)
    return reasons


def _output(project: str, head: dict, adapter: StorageAdapter) -> GenerationResult | None:
    output = get_artifact(project_artifact_id(project, _output_key(head)))
    if output is None:
        return None
    if (output["tenant_id"], output["project_id"], output.get("subtype")) != (head["tenant_id"], project, "innovation_generation_output"):
        raise StorageIntegrityError("Generation output scope mismatch")
    parsed = GenerationOutput.model_validate_json(_read_bytes(output, adapter))
    if parsed.plan_hash != head["content_hash"]:
        raise StorageIntegrityError("Generation result does not match its admitted plan")
    plan = GenerationPlan.model_validate_json(_read_bytes(head, adapter))
    from .generation import validate_generation_result
    validate_generation_result(parsed.result, plan.brief, plan.spec)
    return parsed.result


def get_generation(principal: Principal, project: str, run_id: str, adapter: StorageAdapter) -> dict:
    plan, head, document, source = _read_plan(principal, project, run_id, adapter)
    result = _output(project, head, adapter)
    job_id = _key(run_id)
    job = durable_runs.get_job(job_id)
    reasons = _reasons(principal, project, plan, head, document, source)
    status = result.state if result and not reasons else "BLOCKED" if reasons else (job or {}).get("state", "UNKNOWN")
    return GenerationEnvelope(artifact_id=head["artifact_id"], version=int(head["version"]), content_hash=head["content_hash"],
        job_id=job_id, spec=plan.spec, approval=_approval(head, project), status=status, reasons=reasons, output=result).model_dump(mode="python")


def prepare_generation(principal: Principal, project: str, run_id: str, expected_version: int, adapter: StorageAdapter) -> dict:
    document, source = _read(principal, project, run_id, adapter)
    _check_version(source, expected_version)
    if document.brief.provider != "live":
        raise HTTPException(409, "Prepare a live brief explicitly; fixture provenance cannot be upgraded")
    if document.run.status in {"CANCELLED", "PAUSED"}:
        raise HTTPException(409, "Source run is paused or cancelled")
    assert_role_may_produce("market_researcher", "research_brief")
    with atomic_transaction():
        existing = get_artifact(project_artifact_id(project, _key(run_id)))
        if existing is None:
            spec = create_spec(document.brief, run_id, source["artifact_id"], int(source["version"]), source["content_hash"])
            plan = GenerationPlan(run_id=run_id, brief=document.brief, spec=spec)
            created = create_project_artifact(tenant_id=principal.tenant_id, project_id=project, actor=principal.user_id,
                artifact_key=_key(run_id), artifact_type="research_brief", subtype="innovation_generation_plan", adapter=adapter,
                content_text=plan.model_dump_json(), depends_on=(source["artifact_id"],), v2={"mime_type": "application/json", "media_type": "data"})
            existing = get_artifact(created.artifact_id)
            durable_runs.create_job(tenant_id=principal.tenant_id, project_id=project, kind=KIND,
                spec={"run_id": run_id, "plan_hash": existing["content_hash"]}, spec_hash=existing["content_hash"],
                requested_by=principal.user_id, due_at=datetime.now(timezone.utc), max_attempts=1, job_id=_key(run_id))
        _open_approval(principal, project, run_id, existing)
    return get_generation(principal, project, run_id, adapter)


def _open_approval(principal, project, run_id, head):
    if _approval(head, project) is not None:
        return
    open_artifact_approval(principal, tenant_id=principal.tenant_id, project_id=project,
        mission_id=f"{project}:{run_id}:generation", contract_hash=head["content_hash"], artifact_id=head["artifact_id"],
        version=int(head["version"]), content_hash=head["content_hash"], run_pipeline="innovation_generation",
        policy_version=POLICY, subject_type=PURPOSE,
        reason="Authorize exactly one model invocation of the immutable generation plan; this is not artifact-release approval",
        metadata={"approval_policy": {PURPOSE: {"no_self_approval": True}}})


class GenerationHandler:
    operation = "innovation.invoke_generation"
    contract_version = POLICY
    retry_class = "NON_RETRYABLE"

    def __init__(self, principal, project, run_id, adapter):
        self.principal, self.project, self.run_id, self.adapter = principal, project, run_id, adapter

    def target(self, job):
        return project_artifact_id(self.project, _key(self.run_id))

    def input_hash(self, job):
        return job["spec_hash"]

    def precheck(self, job):
        plan, head, document, source = _read_plan(self.principal, self.project, self.run_id, self.adapter)
        if (job["tenant_id"], job["project_id"], job["spec_hash"]) != (self.principal.tenant_id, self.project, head["content_hash"]):
            return RunState.BLOCKED_AUTHORITY, ["GENERATION_SCOPE_OR_PLAN_MISMATCH"]
        reasons = _reasons(self.principal, self.project, plan, head, document, source)
        if reasons:
            return RunState.WAITING_APPROVAL, reasons
        return None, []

    def environment_fingerprint(self, job):
        return job["spec_hash"]

    def pre_image(self, job):
        return {"artifact_id": self.target(job), "plan_hash": job["spec_hash"]}

    def dispatch(self, job):
        # Recheck exact scope, source and authority immediately before the call.
        blocked, reasons = self.precheck(job)
        if blocked:
            return {"blocked_state": blocked.value, "reasons": reasons}
        plan, head, _, _ = _read_plan(self.principal, self.project, self.run_id, self.adapter)
        approval = _approval(head, self.project)
        result = invoke_generation(plan.brief, plan.spec, authorization_ref=approval["approval_id"])
        document = GenerationOutput(plan_hash=head["content_hash"], result=result)
        stored = self.adapter.put_bytes(tenant_id=self.principal.tenant_id, project_id=self.project, data=document.model_dump_json().encode())
        return {"storage_uri": stored.storage_uri, "content_hash": stored.content_hash}

    def observe(self, job, dispatched):
        # A readback fault is terminal verification failure, never an automatic network retry.
        try:
            data = self.adapter.get_bytes(dispatched["storage_uri"])
            if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != dispatched["content_hash"]:
                return {"invalid": True}
            parsed = GenerationOutput.model_validate_json(data)
            return {**dispatched, "document": parsed.model_dump(mode="json")}
        except (ValueError, OSError, StorageIntegrityError):
            return {"invalid": True}

    def verify(self, job, observation):
        try:
            parsed = GenerationOutput.model_validate(observation["document"])
            plan, _, _, _ = _read_plan(self.principal, self.project, self.run_id, self.adapter)
            from .generation import validate_generation_result
            validate_generation_result(parsed.result, plan.brief, plan.spec)
            valid = parsed.plan_hash == job["spec_hash"]
        except (ValueError, KeyError):
            valid = False
        return {"status": "PASSED" if valid else "FAILED", "scope": "MODEL_OUTPUT_STRUCTURE_ONLY"}

    def reconcile(self, job, intent):
        return "UNKNOWN", None

    def on_commit(self, job, observation, verification):
        plan, head, document, source = _read_plan(self.principal, self.project, self.run_id, self.adapter)
        if _reasons(self.principal, self.project, plan, head, document, source):
            raise PermissionError("Generation authority or source changed before result registration")
        parsed = GenerationOutput.model_validate(observation["document"])
        from .generation import validate_generation_result
        validate_generation_result(parsed.result, plan.brief, plan.spec)
        with atomic_transaction():
            current = _output(self.project, head, self.adapter)
            if current is None:
                create_project_artifact(tenant_id=self.principal.tenant_id, project_id=self.project, actor=self.principal.user_id,
                    artifact_key=_output_key(head), artifact_type="research_brief", subtype="innovation_generation_output",
                    adapter=self.adapter, content_text=parsed.model_dump_json(), depends_on=(head["artifact_id"],),
                    v2={"mime_type": "application/json", "media_type": "data"})
            elif canonical_hash(current) != canonical_hash(parsed.result):
                raise StorageIntegrityError("Generation output already has different registered bytes")
        return RunState.DORMANT, {"artifact_id": project_artifact_id(self.project, _output_key(head)), "state": parsed.result.state}


def tick_generation(principal: Principal, project: str, run_id: str, expected_version: int, adapter: StorageAdapter) -> dict:
    plan, head, document, source = _read_plan(principal, project, run_id, adapter)
    _check_version(head, expected_version)
    if _output(project, head, adapter) is not None:
        return get_generation(principal, project, run_id, adapter)
    job = durable_runs.get_job(_key(run_id))
    reasons = _reasons(principal, project, plan, head, document, source)
    if reasons:
        return get_generation(principal, project, run_id, adapter)
    if job["state"] == RunState.WAITING_APPROVAL.value and not durable_runs.list_intents(job["job_id"]):
        durable_runs.operator_move(job["job_id"], RunState.SCHEDULED, actor=principal.user_id, reason="Exact generation approval and provider prechecks now satisfied")
    handler = GenerationHandler(principal, project, run_id, adapter)
    run_tick(worker_id=f"innovation-generation:{principal.user_id}", handlers={KIND: handler}, job_id=job["job_id"], project_id=project, lease_seconds=120)
    return get_generation(principal, project, run_id, adapter)
