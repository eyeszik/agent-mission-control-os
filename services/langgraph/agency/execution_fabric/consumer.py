"""Wave execution consumer: the governed bridge from ``schedule_waves`` to ProjectOS artifacts.

For each wave the planner emitted, in order:

1. **Freshness.** The wave plan is recomputed with the same scheduler; a
   different ``wave_hash`` refuses the whole mission (``STALE_WAVE_PLAN``).
   Each cell's recorded input hashes are re-checked against the graph.
2. **Eligibility.** Planner/work-order blockers, held cells, upstream outcomes,
   server-only authority, the N3 role contract, the skill binding, provider,
   sandbox, side-effect ceiling, budget and an injection scan of the payload.
   Every refusal is a truthful :class:`ExecutionState`, never EXECUTOR_GAP.
3. **Collision split.** Cells in one wave that share a mutation target,
   resource lock or artifact identity are serialized into sub-waves.
4. **Two-phase write-ahead per cell.** Phase 1 (intent): reserve the
   idempotency key ``hash(tenant, project, mission, work_order, contract,
   input)`` in the tenant's scope and persist a DispatchPermit recording the
   target artifact's pre-image version. Phase 2 (commit): dispatch through
   ``dispatch_skill`` (non-colliding cells concurrently, deterministic pure
   handlers only), run validators, persist the artifact through ProjectOS with
   optimistic concurrency, write the ExecutionReceipt, read the stored bytes
   back for the ObservationReceipt, then complete the reservation.
5. **Reconcile before retry.** An uncommitted reservation older than the lease
   is reconciled against the permit's pre-image: nothing landed → retry; our
   write landed (provenance names our key) → adopt without a second version;
   anything else → halt (``RECONCILE_DIVERGENT``).

Consequential side effects (``REVERSIBLE_WRITE`` and above) are never
dispatched: without an approval they need a human, and with one they remain
``LIVE_GATED`` because no live executor exists.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.compiled.execution import CellStatus, advance_cell
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.execution.models import ExecutionReceipt, FailureFingerprint, ObservationReceipt
from services.langgraph.agency.kernel.lifecycle import TransitionContext, release_guard_failures
from services.langgraph.agency.kernel.roles import RoleContractError, assert_role_may_produce, get_role
from services.langgraph.agency.project_os.storage import LocalStorageAdapter, StorageAdapter
from services.langgraph.agency.project_os.vocabulary import ActivityType
from services.langgraph.agency.skills.dispatcher import (
    SKILL_RUNTIME_VERSION,
    TIMEOUT_SECONDS,
    SkillDispatchError,
    dispatch_skill,
)
from services.langgraph.persistence import idempotency as wal
from services.langgraph.persistence.agency_kernel import StaleArtifactVersionError, get_artifact
from services.langgraph.persistence.projects import (
    ProjectConflictError,
    append_project_event,
    create_project_artifact,
    ensure_project_workspace,
    project_artifact_id,
    register_storage_object,
    revise_project_artifact,
)
from services.langgraph.persistence.proofs import (
    list_dispatch_permits,
    put_dispatch_permit,
    put_execution_receipt,
    put_failure_fingerprint,
    put_observation_receipt,
)
from services.langgraph.persistence.runs import create_run_record, get_run_record, update_run_status

from .capsules import BrandContextCapsule, capsule_for, quarantine_reasons
from .contracts import (
    FABRIC_VERSION,
    Clock,
    ExecutionContext,
    ExecutionRequest,
    ExecutionState,
    FabricPermit,
    PermitInvalid,
    dominant_state,
    execution_key,
    issue_permit,
    reservation_scope,
    system_clock,
    verify_permit,
)
from .schedule import CellPlan, MissionSchedule, stale_inputs, wave_plan_fresh
from .skills import ARTIFACT_SKILLS, FABRIC_SKILLS, VALIDATORS, provider_blocker, sandbox_blocker, skill_binding_blockers

RUN_PIPELINE = "execution-fabric/v1"
EXECUTABLE_SIDE_EFFECTS = ("PURE", "DRAFT")
_RANK = {"PURE": 0, "DRAFT": 1, "REVERSIBLE_WRITE": 2, "IRREVERSIBLE_WRITE": 3}
_BRAND_SKILLS = frozenset({"brand_logo_svg", "dtcg_token_compile", "design_system_spec_compile"})
_MAX_WORKERS = 8


class CellOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_id: str
    node_id: str
    wave_index: int | None
    state: ExecutionState
    reasons: tuple[str, ...] = ()
    skill_id: str | None = None
    role_id: str | None = None
    attempts: int = 0
    idempotency_key: str | None = None
    artifact_ref: str | None = None
    content_hash: str | None = None
    verdicts: tuple[dict, ...] = ()
    replayed: bool = False
    reconciled: bool = False
    cell_status: str | None = None


class MissionExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fabric_version: str
    source: str
    mission_id: str
    plan_hash: str
    run_id: str
    mode: str
    wave_hash: str
    wave_plan_fresh: bool
    sub_waves: tuple[tuple[str, ...], ...]
    cells: dict[str, CellOutcome]
    release_boundary: dict[str, dict]
    summary: dict[str, int]

    @property
    def outcome_hash(self) -> str:
        """Hash of what happened, not how: identical inputs give an identical
        outcome hash whether a cell executed, replayed or was reconciled."""
        return canonical_hash({
            "mission_id": self.mission_id,
            "plan_hash": self.plan_hash,
            "cells": {k: [v.state.value, list(v.reasons), v.artifact_ref, v.content_hash] for k, v in sorted(self.cells.items())},
            "release_boundary": self.release_boundary,
        })


class SimulatedCrash(BaseException):
    """Raised by test hooks to stop the consumer mid-commit, like a killed worker."""


Hook = Callable[[str, dict], None]


@dataclass
class _Prepared:
    plan: CellPlan
    request: ExecutionRequest
    payload: dict[str, Any]
    artifact_id: str
    artifact_key: str
    snapshot_version: int
    attempts: int = 0
    permit: FabricPermit | None = None
    result: dict[str, Any] | None = None
    verdicts: tuple[dict, ...] = ()
    failure: tuple[ExecutionState, tuple[str, ...]] | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    fingerprint: str | None = None
    timed_out: bool = False


def _run_id(context: ExecutionContext, schedule: MissionSchedule) -> str:
    return "fabric-" + canonical_hash({
        "tenant": context.tenant_id, "project": context.project_id,
        "mission": schedule.mission_id, "plan": schedule.plan_hash,
    })[:24]


def _ensure_run(run_id: str, context: ExecutionContext, schedule: MissionSchedule) -> None:
    existing = get_run_record(run_id)
    if existing is not None:
        if (existing["tenant_id"], existing["project_id"]) != (context.tenant_id, context.project_id):
            raise PermissionError("fabric run id collides with another tenant's run")
        return
    create_run_record(run_id, context.tenant_id, context.project_id, RUN_PIPELINE, "executing",
                      {"fabric_version": FABRIC_VERSION, "mission_id": schedule.mission_id,
                       "plan_hash": schedule.plan_hash, "mode": context.mode, "source": schedule.source})


def _artifact_text(adapter: StorageAdapter, artifact_id: str) -> str | None:
    record = get_artifact(artifact_id)
    location = (record or {}).get("content_location")
    if not location:
        return None
    try:
        return adapter.get_bytes(location).decode("utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return None


class _Consumer:
    def __init__(self, schedule: MissionSchedule, context: ExecutionContext, *, brand: BrandContextCapsule | None,
                 node_inputs: Mapping[str, dict], skill_overrides: Mapping[str, str], clock: Clock,
                 hooks: Mapping[str, Hook], adapter: StorageAdapter):
        self.s = schedule
        self.ctx = context
        self.brand = brand
        self.node_inputs = node_inputs
        self.overrides = skill_overrides
        self.clock = clock
        self.hooks = hooks
        self.adapter = adapter
        self.run_id = _run_id(context, schedule)
        self.scope = reservation_scope(context.tenant_id)
        self.outcomes: dict[str, CellOutcome] = {}
        self.invocations = 0
        self.sub_waves: list[tuple[str, ...]] = []

    # ------------------------------------------------------------ helpers
    def _hook(self, point: str, cell_id: str, data: dict | None = None) -> None:
        hook = self.hooks.get(point)
        if hook is not None:
            hook(cell_id, data or {})

    def _block(self, cp: CellPlan, wave: int | None, reasons: list[str] | tuple[str, ...], **extra: Any) -> None:
        reasons = tuple(sorted(set(reasons)))
        self.outcomes[cp.cell.cell_id] = CellOutcome(
            cell_id=cp.cell.cell_id, node_id=cp.node_id, wave_index=wave,
            state=extra.pop("state", None) or dominant_state(reasons), reasons=reasons, **extra,
        )

    def _upstream_cells(self, cp: CellPlan) -> list[str]:
        own = cp.cell.cell_id
        return sorted({self.s.cell_for_node[a] for a in self.s.graph.ancestors(cp.node_id)
                       if a in self.s.cell_for_node and self.s.cell_for_node[a] != own and self.s.cell_for_node[a] in self.s.cells})

    # ------------------------------------------------------------ eligibility
    def _eligibility(self, cp: CellPlan) -> tuple[list[str], str | None, dict[str, Any]]:
        reasons: list[str] = list(cp.blockers)
        reasons += list(self.s.wave_plan.held.get(cp.cell.cell_id, ()))
        if not cp.execution_ready and not reasons:
            reasons.append("WORK_ORDER_NOT_EXECUTION_READY")
        for upstream in self._upstream_cells(cp):
            outcome = self.outcomes.get(upstream)
            if outcome is None or outcome.state is not ExecutionState.SUCCEEDED:
                reasons.append(f"UPSTREAM_NOT_SUCCEEDED:{upstream}")
        reasons += [f"STALE_INPUT:{d}" for d in stale_inputs(self.s, cp.cell.cell_id)]

        if cp.side_effect_class not in EXECUTABLE_SIDE_EFFECTS:
            reasons.append("MISSING_EXACT_APPROVAL_REF" if not cp.approval_refs else f"LIVE_GATED:{cp.side_effect_class}")
        if set(cp.authority_refs) - set(self.ctx.authority_refs):
            reasons.append("AUTHORITY_NOT_SERVER_ISSUED")
        if set(cp.approval_refs) - set(self.ctx.approval_refs):
            reasons.append("AUTHORITY_APPROVAL_NOT_SERVER_ISSUED")

        skill_id = self.overrides.get(cp.node_id) or ARTIFACT_SKILLS.get(cp.artifact_type or "")
        reasons += list(skill_binding_blockers(cp.artifact_type, skill_id))
        spec = FABRIC_SKILLS.get(skill_id or "")
        role = cp.n3_role_id
        if role is None:
            reasons.append("ROLE_NO_N3_CONTRACT")
        else:
            try:
                contract = get_role(role)
                if cp.artifact_type:
                    assert_role_may_produce(role, cp.artifact_type)
                if spec is not None and spec.skill.capability not in contract.capabilities:
                    reasons.append(f"ROLE_LACKS_CAPABILITY:{spec.skill.capability.value}")
            except RoleContractError as exc:
                reasons.append(f"ROLE_MAY_NOT_PRODUCE:{exc}")
        if spec is not None:
            for blocker in (provider_blocker(spec.skill.provider_requirement), sandbox_blocker(spec.skill.sandbox_requirement)):
                if blocker:
                    reasons.append(blocker)
            ceiling = min(_RANK.get(cp.side_effect_class, 3), _RANK["DRAFT"])
            if _RANK[spec.skill.side_effect_class] > ceiling:
                reasons.append("POLICY_SKILL_EXCEEDS_SIDE_EFFECT_CEILING")
            if skill_id in _BRAND_SKILLS and self.brand is None:
                reasons.append("CONTRACT_MISSING_BRAND_CAPSULE")
        if self.invocations >= self.ctx.budget.max_invocations:
            reasons.append("BUDGET_EXCEEDED:invocations")

        payload: dict[str, Any] = {"inputs": dict(self.node_inputs.get(cp.node_id, {}))}
        if self.brand is not None:
            payload["brand"] = self.brand.model_dump(mode="json")
        if self.ctx.client_inputs:
            payload["client"] = dict(self.ctx.client_inputs)
        upstream: dict[str, str] = {}
        for up in self._upstream_cells(cp):
            outcome = self.outcomes.get(up)
            if outcome and outcome.artifact_ref:
                text = _artifact_text(self.adapter, outcome.artifact_ref.rsplit(":v", 1)[0])
                if text is not None:
                    upstream[self.s.cells[up].artifact_type or up] = text
        if upstream:
            payload["upstream"] = upstream
        capsules = [capsule_for("server_inputs", {"inputs": payload["inputs"], "brand": payload.get("brand")}, "SERVER_INPUT")]
        if "client" in payload:
            capsules.append(capsule_for("client_inputs", payload["client"], "CLIENT_INPUT"))
        capsules += [capsule_for(f"upstream:{k}", v, "UPSTREAM_ARTIFACT") for k, v in sorted(upstream.items())]
        reasons += list(quarantine_reasons(capsules))
        return reasons, skill_id, payload

    def _prepare(self, cp: CellPlan, wave: int) -> _Prepared | None:
        reasons, skill_id, payload = self._eligibility(cp)
        if reasons:
            self._block(cp, wave, reasons, skill_id=skill_id, role_id=cp.n3_role_id)
            return None
        input_hash = canonical_hash(payload)
        key = execution_key(tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id, mission_id=self.s.mission_id,
                            work_order_id=cp.work_order_id or cp.node_id, contract_hash=cp.contract_hash, input_hash=input_hash)
        request = ExecutionRequest(
            tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id, mission_id=self.s.mission_id,
            cell_id=cp.cell.cell_id, node_id=cp.node_id, work_order_id=cp.work_order_id or cp.node_id,
            role_id=cp.n3_role_id or "", skill_id=skill_id or "", artifact_type=cp.artifact_type or "",
            contract_hash=cp.contract_hash, context_hash=cp.context_hash,
            dependency_hashes=tuple(cp.cell.input_refs), input_hash=input_hash, idempotency_key=key,
        )
        artifact_key = f"{self.s.mission_id}/{cp.node_id}"
        artifact_id = project_artifact_id(self.ctx.project_id, artifact_key)
        head = get_artifact(artifact_id)
        return _Prepared(cp, request, payload, artifact_id, artifact_key, int(head["version"]) if head else 0)

    # ------------------------------------------------------------ phase 1
    def _intent(self, p: _Prepared, wave: int) -> bool:
        """Reserve + permit. Returns True when the cell should be dispatched."""
        key = p.request.idempotency_key
        res = wal.reserve_idempotency(self.scope, key, p.request.request_hash)
        state = res["state"]
        if state == "replay":
            result = res["record"]["result"] or {}
            self._succeeded(p, wave, result, replayed=True)
            return False
        if state == "conflict":
            self._block(p.plan, wave, ["IDEMPOTENCY_CONFLICT"], state=ExecutionState.FAILED, idempotency_key=key)
            return False
        if state == "in_progress" and self._reconcile(p, wave, res["record"]) is not True:
            return False
        now = self.clock()
        p.permit = issue_permit(
            p.request, context=self.ctx, snapshot_hash=self.s.snapshot_hash, causal_epoch=wave,
            dependency_version_refs=(f"target:{p.artifact_id}@v{p.snapshot_version}",
                                     *(f"{dep}@{h}" for dep, h in p.request.dependency_hashes)),
            authority_refs=tuple(p.plan.authority_refs), approval_refs=tuple(p.plan.approval_refs), now=now,
        )
        put_dispatch_permit(self.run_id, self.ctx.tenant_id, self.ctx.project_id, p.permit.permit)
        self._hook("after_intent", p.plan.cell.cell_id, {"key": key})
        return True

    def _reconcile(self, p: _Prepared, wave: int, record: dict) -> bool | None:
        key = p.request.idempotency_key
        try:
            updated = datetime.fromisoformat(str(record["updated_at"]))
        except (KeyError, TypeError, ValueError):
            updated = None
        if updated is not None and (self.clock() - updated).total_seconds() < self.ctx.lease_seconds:
            self._block(p.plan, wave, ["EXECUTION_IN_PROGRESS_ELSEWHERE"], idempotency_key=key)
            return None
        permit_id = f"permit-{key[:32]}"
        prior = [x for x in list_dispatch_permits(self.run_id) if x.get("permit_id") == permit_id]
        pre_image = None
        if prior:
            for ref in prior[-1].get("dependency_version_refs") or ():
                if ref.startswith(f"target:{p.artifact_id}@v"):
                    pre_image = int(ref.rsplit("@v", 1)[1])
        head = get_artifact(p.artifact_id)
        provenance = ((head or {}).get("metadata") or {}).get("v2", {}).get("provenance_ref")
        if head is not None and provenance == f"execution:{key}":
            # Our commit landed before the crash: adopt it, never write a second version.
            result = {"artifact_ref": f"{p.artifact_id}:v{head['version']}", "content_hash": head.get("content_hash")}
            self._write_receipts(p, head, attempts=1, reconciled=True)
            wal.complete_idempotency(self.scope, key, result)
            self._succeeded(p, wave, result, reconciled=True)
            return None
        head_version = int(head["version"]) if head else 0
        if pre_image is not None and head_version == pre_image:
            # Nothing landed: release the crashed reservation and run again.
            wal.fail_idempotency(self.scope, key, "RECONCILED_CRASH:no_commit")
            again = wal.reserve_idempotency(self.scope, key, p.request.request_hash)
            if again["state"] != "new":
                self._block(p.plan, wave, [f"RECONCILE_RESERVE_{again['state'].upper()}"], idempotency_key=key)
                return None
            p.snapshot_version = head_version
            append_project_event(tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id,
                                 event_type=ActivityType.RECOVERING, actor=self.ctx.actor,
                                 subject_ref=p.artifact_id, payload={"cell_id": p.plan.cell.cell_id, "reason": "crashed_reservation_released"})
            return True
        self._block(p.plan, wave, ["RECONCILE_DIVERGENT"], idempotency_key=key)
        return None

    # ------------------------------------------------------------ phase 2a: dispatch (pure, concurrent)
    def _dispatch(self, p: _Prepared) -> None:
        spec = FABRIC_SKILLS[p.request.skill_id]
        try:
            verify_permit(p.permit, p.request, now=self.clock(), max_skew_seconds=self.ctx.max_clock_skew_seconds)
        except PermitInvalid as exc:
            p.failure = (ExecutionState.BLOCKED_POLICY, (exc.code,))
            return
        fingerprints: list[str] = []
        p.started_at = self.clock()
        while p.attempts < min(p.plan.max_attempts, self.ctx.budget.max_attempts_per_cell):
            p.attempts += 1
            try:
                outcome = dispatch_skill(p.request.role_id, p.request.skill_id, p.payload)
            except (RoleContractError, SkillDispatchError) as exc:
                p.failure = (ExecutionState.BLOCKED_AUTHORITY, (f"AUTHORITY_DISPATCH_REFUSED:{type(exc).__name__}",))
                return
            if outcome.succeeded:
                p.result = outcome.result
                break
            fp = canonical_hash({"error": outcome.error_class, "skill": p.request.skill_id, "input": p.request.input_hash})
            p.fingerprint = fp
            if fp in fingerprints:
                p.failure = (ExecutionState.NEEDS_HUMAN, ("APPROVAL_HUMAN_REVIEW_REQUIRED:CIRCUIT_BREAKER_SAME_FAILURE",))
                return
            fingerprints.append(fp)
            p.failure = (ExecutionState.FAILED, (f"SKILL_FAILED:{outcome.error_class}",))
        p.ended_at = self.clock()
        if p.result is None:
            return
        p.failure = None
        content = p.result.get("content")
        if not isinstance(content, str):
            p.failure = (ExecutionState.FAILED, ("SKILL_OUTPUT_INVALID",))
            return
        if len(content.encode("utf-8")) > self.ctx.budget.max_output_bytes:
            p.failure = (ExecutionState.BLOCKED_POLICY, ("BUDGET_EXCEEDED:output_bytes",))
            return
        verdicts = [VALIDATORS[v](p.result, p.payload) for v in spec.skill.validator_ids]
        p.verdicts = tuple(v.as_dict() for v in verdicts)
        failed = [v.validator_id for v in verdicts if not v.passed]
        if failed:
            p.failure = (ExecutionState.FAILED, tuple(f"VALIDATION_FAILED:{v}" for v in failed))

    # ------------------------------------------------------------ phase 2b: commit (serial)
    def _commit(self, p: _Prepared, wave: int) -> None:
        key = p.request.idempotency_key
        if p.timed_out:
            p.failure, p.verdicts = (ExecutionState.FAILED, ("SKILL_TIMEOUT",)), ()
        if p.failure is not None:
            state, reasons = p.failure
            wal.fail_idempotency(self.scope, key, ",".join(reasons))
            fp = p.fingerprint or canonical_hash({"reasons": reasons, "input": p.request.input_hash})
            put_failure_fingerprint(self.run_id, self.ctx.tenant_id, self.ctx.project_id, f"op-{key[:40]}", FailureFingerprint(
                fingerprint=fp, failure_class=state.value, causal_node=p.plan.node_id,
                work_order_input_hash=p.request.input_hash, dependency_snapshot_hash=self.s.snapshot_hash,
                tool_contract_hash=canonical_hash({"skill": p.request.skill_id, "runtime": SKILL_RUNTIME_VERSION}),
                environment_signature=canonical_hash({"mode": self.ctx.mode, "fabric": FABRIC_VERSION}),
                error_class=reasons[0].split(":", 1)[0], error_code=reasons[0],
            ))
            append_project_event(tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id, event_type=ActivityType.QA_BLOCKED,
                                 actor=self.ctx.actor, subject_ref=p.artifact_id,
                                 payload={"cell_id": p.plan.cell.cell_id, "state": state.value, "reasons": list(reasons)})
            self._block(p.plan, wave, reasons, state=state, skill_id=p.request.skill_id, role_id=p.request.role_id,
                        attempts=p.attempts, idempotency_key=key, verdicts=p.verdicts)
            return

        self._hook("before_commit", p.plan.cell.cell_id, {"artifact_id": p.artifact_id})
        result = p.result or {}
        v2 = {"mime_type": result.get("mime_type"), "media_type": "data" if result.get("mime_type") == "application/json" else None,
              "provenance_ref": f"execution:{key}", "source_refs": [ref for ref, _ in p.request.dependency_hashes]}
        content_text: str | None = result["content"]
        content_hash = storage_uri = None
        if result.get("content_file"):
            with open(result["content_file"], "rb") as handle:
                stored = self.adapter.put_bytes(tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id, data=handle.read())
            register_storage_object(tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id, stored=stored,
                                    mime_type=result.get("content_file_mime") or "application/octet-stream")
            report = self.adapter.put_bytes(tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id, data=content_text.encode("utf-8"))
            v2.update({"mime_type": result.get("content_file_mime"), "media_type": "video", "evidence_refs": [report.storage_uri]})
            content_text, content_hash, storage_uri = None, stored.content_hash, stored.storage_uri
        try:
            if p.snapshot_version == 0:
                create_project_artifact(
                    tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id, actor=self.ctx.actor,
                    artifact_key=p.artifact_key, artifact_type=p.request.artifact_type, adapter=self.adapter,
                    content_text=content_text, content_hash=content_hash, storage_uri=storage_uri,
                    subtype=result.get("subtype"), v2=v2,
                )
            else:
                revise_project_artifact(
                    project_id=self.ctx.project_id, artifact_id=p.artifact_id, actor=self.ctx.actor, adapter=self.adapter,
                    expected_version=p.snapshot_version, content_text=content_text, content_hash=content_hash,
                    storage_uri=storage_uri, v2_patch=v2, change_kind="revise",
                )
        except (ProjectConflictError, StaleArtifactVersionError) as exc:
            wal.fail_idempotency(self.scope, key, f"WRITE_COLLISION:{type(exc).__name__}")
            self._block(p.plan, wave, ["STALE_WRITE_COLLISION"], state=ExecutionState.FAILED, skill_id=p.request.skill_id,
                        role_id=p.request.role_id, attempts=p.attempts, idempotency_key=key, verdicts=p.verdicts)
            return
        head = get_artifact(p.artifact_id)
        self._hook("after_artifact", p.plan.cell.cell_id, {"artifact_id": p.artifact_id})
        observed = self._write_receipts(p, head, attempts=p.attempts)
        if not observed:
            wal.fail_idempotency(self.scope, key, "OBSERVATION_MISMATCH")
            self._block(p.plan, wave, ["OBSERVATION_MISMATCH"], state=ExecutionState.FAILED, idempotency_key=key)
            return
        out = {"artifact_ref": f"{p.artifact_id}:v{head['version']}", "content_hash": head.get("content_hash")}
        wal.complete_idempotency(self.scope, key, out)
        self._succeeded(p, wave, out)

    def _write_receipts(self, p: _Prepared, head: dict, *, attempts: int, reconciled: bool = False) -> bool:
        now = self.clock()
        op = f"op-{p.request.idempotency_key[:40]}"
        put_execution_receipt(self.run_id, self.ctx.tenant_id, self.ctx.project_id, ExecutionReceipt(
            operation_id=op, work_order_id=p.request.work_order_id, actor_role_id=p.request.role_id,
            tool=f"skill:{p.request.skill_id}", tool_contract_ref=f"{SKILL_RUNTIME_VERSION}:{p.request.skill_id}",
            args_hash=p.request.input_hash, target=p.artifact_id, idempotency_key=p.request.idempotency_key,
            attempt=max(1, min(3, attempts)), started_at=p.started_at or now, ended_at=p.ended_at or now,
            returned_state="RECONCILED" if reconciled else "SUCCEEDED", result_ref=f"{p.artifact_id}:v{head['version']}",
        ))
        try:
            data = self.adapter.get_bytes(head["content_location"])
            observed_hash = hashlib.sha256(data).hexdigest()
        except Exception:  # an unreadable object is an observation failure, not a crash
            observed_hash = None
        matches = observed_hash is not None and observed_hash == head.get("content_hash")
        put_observation_receipt(self.run_id, self.ctx.tenant_id, self.ctx.project_id, ObservationReceipt(
            operation_id=op, target=p.artifact_id,
            expected_postcondition={"content_hash": head.get("content_hash"), "version": head["version"]},
            observed_postcondition={"content_hash": observed_hash},
            observation_method="storage_readback_sha256", evidence_refs=(head["content_location"],), observed_at=now,
            matches=matches,
        ))
        return matches

    def _succeeded(self, p: _Prepared, wave: int, result: dict, *, replayed: bool = False, reconciled: bool = False) -> None:
        cell = p.plan.cell
        if cell.status is CellStatus.FORMED:
            for to in (CellStatus.READY, CellStatus.EXECUTING, CellStatus.VALIDATING, CellStatus.ACCEPTED):
                cell = advance_cell(cell, to)
        self.outcomes[cell.cell_id] = CellOutcome(
            cell_id=cell.cell_id, node_id=p.plan.node_id, wave_index=wave, state=ExecutionState.SUCCEEDED,
            skill_id=p.request.skill_id, role_id=p.request.role_id, attempts=p.attempts,
            idempotency_key=p.request.idempotency_key, artifact_ref=result.get("artifact_ref"),
            content_hash=result.get("content_hash"), verdicts=p.verdicts, replayed=replayed, reconciled=reconciled,
            cell_status=cell.status.value,
        )

    # ------------------------------------------------------------ driver
    def _sub_waves(self, prepared: list[_Prepared]) -> list[list[_Prepared]]:
        buckets: list[tuple[set[str], list[_Prepared]]] = []
        for p in sorted(prepared, key=lambda x: x.plan.cell.cell_id):
            keys = set(p.plan.cell.mutation_targets) | set(p.plan.cell.resource_locks) | {p.artifact_id}
            for used, members in buckets:
                if not used & keys:
                    used |= keys
                    members.append(p)
                    break
            else:
                buckets.append((set(keys), [p]))
        return [members for _, members in buckets]

    def run(self) -> MissionExecutionReport:
        ensure_project_workspace(tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id, actor=self.ctx.actor)
        _ensure_run(self.run_id, self.ctx, self.s)
        fresh = wave_plan_fresh(self.s)
        append_project_event(tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id, event_type=ActivityType.WORK_STARTED,
                             actor=self.ctx.actor, subject_ref=self.run_id,
                             payload={"pipeline": RUN_PIPELINE, "mission_id": self.s.mission_id, "fresh": fresh})
        if not fresh:
            for cp in self.s.cells.values():
                self._block(cp, None, ["STALE_WAVE_PLAN"])
            return self._report(fresh)

        for wave in self.s.wave_plan.waves:
            prepared = [p for p in (self._prepare(self.s.cells[cid], wave.index) for cid in wave.cells if cid in self.s.cells) if p]
            for group in self._sub_waves(prepared):
                self.sub_waves.append(tuple(p.plan.cell.cell_id for p in group))
                runnable = []
                for p in group:
                    # The budget is charged at reservation, so cells prepared in
                    # the same wave cannot jointly overrun it.
                    if self.invocations >= self.ctx.budget.max_invocations:
                        self._block(p.plan, wave.index, ["BUDGET_EXCEEDED:invocations"], skill_id=p.request.skill_id,
                                    role_id=p.request.role_id)
                    elif self._intent(p, wave.index):
                        self.invocations += 1
                        runnable.append(p)
                pool = concurrent.futures.ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, max(1, len(runnable))))
                try:
                    futures = {pool.submit(self._dispatch, p): p for p in runnable}
                    for future, p in futures.items():
                        timeout = TIMEOUT_SECONDS[FABRIC_SKILLS[p.request.skill_id].skill.timeout_class] * p.plan.max_attempts
                        try:
                            future.result(timeout=timeout)
                        except concurrent.futures.TimeoutError:
                            # A thread cannot be killed; the flag wins over
                            # anything the late handler writes afterwards.
                            p.timed_out = True
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
                for p in sorted(runnable, key=lambda x: x.plan.cell.cell_id):
                    self._commit(p, wave.index)
        for cid, cp in self.s.cells.items():
            if cid not in self.outcomes:
                self._eligibility_only(cp)
        return self._report(fresh)

    def _eligibility_only(self, cp: CellPlan) -> None:
        reasons, skill_id, _ = self._eligibility(cp)
        self._block(cp, None, reasons or ["NOT_SCHEDULED_IN_ANY_WAVE"], skill_id=skill_id, role_id=cp.n3_role_id)

    def _report(self, fresh: bool) -> MissionExecutionReport:
        boundary: dict[str, dict] = {}
        for root in sorted(self.s.deliverables):
            closure = sorted({self.s.cell_for_node[n] for n in self.s.graph.ancestors(root) | {root}
                              if n in self.s.cell_for_node and self.s.cell_for_node[n] in self.outcomes})
            unmet = [c for c in closure if self.outcomes[c].state is not ExecutionState.SUCCEEDED]
            ctx = TransitionContext(generation_mode="DETERMINISTIC_LOCAL", unmet_hard_dependencies=tuple(unmet))
            codes = [f.code for f in release_guard_failures(ctx)] + (["unmet_hard_dependencies"] if unmet else [])
            state = (dominant_state([r for c in unmet for r in self.outcomes[c].reasons] or ["UPSTREAM_NOT_SUCCEEDED"])
                     if unmet else ExecutionState.NEEDS_HUMAN)
            boundary[root] = {"state": state.value, "release_guard_failures": codes, "cells": closure, "unmet": unmet,
                              "human_gates": [g for g in self.s.human_gates if g.endswith(f":{root}")]}
        if any(b["state"] == ExecutionState.NEEDS_HUMAN.value for b in boundary.values()):
            append_project_event(tenant_id=self.ctx.tenant_id, project_id=self.ctx.project_id,
                                 event_type=ActivityType.APPROVAL_REQUIRED, actor=self.ctx.actor, subject_ref=self.run_id,
                                 payload={"boundary": {k: v["release_guard_failures"] for k, v in boundary.items()}})
        summary: dict[str, int] = {}
        for outcome in self.outcomes.values():
            summary[outcome.state.value] = summary.get(outcome.state.value, 0) + 1
        all_ok = self.outcomes and all(o.state is ExecutionState.SUCCEEDED for o in self.outcomes.values())
        update_run_status(self.run_id, "executed" if all_ok else ("awaiting_human" if boundary else "blocked"))
        return MissionExecutionReport(
            fabric_version=FABRIC_VERSION, source=self.s.source, mission_id=self.s.mission_id, plan_hash=self.s.plan_hash,
            run_id=self.run_id, mode=self.ctx.mode, wave_hash=self.s.wave_plan.wave_hash, wave_plan_fresh=fresh,
            sub_waves=tuple(self.sub_waves), cells=dict(sorted(self.outcomes.items())), release_boundary=boundary,
            summary=dict(sorted(summary.items())),
        )


def execute_mission(
    schedule: MissionSchedule,
    context: ExecutionContext,
    *,
    brand: BrandContextCapsule | None = None,
    node_inputs: Mapping[str, dict] | None = None,
    skill_overrides: Mapping[str, str] | None = None,
    clock: Clock = system_clock,
    hooks: Mapping[str, Hook] | None = None,
    adapter: StorageAdapter | None = None,
) -> MissionExecutionReport:
    """Execute every eligible cell of ``schedule`` and report every cell's truthful state.

    ``brand``, ``node_inputs`` and ``skill_overrides`` are server-side inputs;
    client text reaches skills only through ``context.client_inputs``, which
    :class:`ExecutionContext` has already screened for authority injection.
    """
    return _Consumer(
        schedule, context, brand=brand, node_inputs=node_inputs or {}, skill_overrides=skill_overrides or {},
        clock=clock, hooks=hooks or {}, adapter=adapter or LocalStorageAdapter(context.export_root),
    ).run()


__all__ = ["CellOutcome", "MissionExecutionReport", "RUN_PIPELINE", "SimulatedCrash", "execute_mission"]
