"""Run one governed mission: intent -> project -> context -> execution -> verification -> approval.

Every step reuses an existing primitive:

* identity and project access: ``security.auth.Principal`` (server-derived);
* memory authority: ``project_os.memory.resolve`` via :mod:`.context`;
* planning: the compiled agency planner, with upstream inputs taken from the
  project's real artifact heads (missing inputs plan as blocked work);
* execution: ``execution_fabric.execute_mission`` in LOCAL mode, which owns
  permits, idempotency, Project OS persistence and storage read-back;
* approval: the existing ``approvals`` table and ``/approvals/{id}/decide``
  route, which enforce the approver role and separation of duties;
* events: the existing project event stream.

New here: the typed receipts, an independent verifier that re-reads the
persisted bytes, and a fail-closed release gate bound to the exact artifact
version and hash. External effects (publish, spend, send) are never
dispatched; each one gets a :class:`NonActionReceipt` instead.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree

from pydantic import ValidationError

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.execution_fabric.capsules import BrandContextCapsule
from services.langgraph.agency.execution_fabric.verifiers import palette_conformance, svg_safety
from services.langgraph.agency.project_os.storage import LocalStorageAdapter, StorageAdapter
from services.langgraph.agency.project_os.vocabulary import ActivityType
from services.langgraph.security.auth import Principal

from .context import DEFAULT_BYTE_BUDGET, compile_context, project_fingerprint
from .contracts import (
    AcceptancePredicate,
    ArtifactVerification,
    Deliverable,
    ExecutionMode,
    MissionContract,
    MissionOutcome,
    NonActionReceipt,
    PredicateState,
    ReleaseVerdict,
    SideEffect,
)
from .intent import compile_intent
from .release import approval_run_id, artifact_release_verdict, open_artifact_approval
from .resolver import resolve_project

RUN_PIPELINE = "intake_mission"
APPROVAL_POLICY_VERSION = "amc-intake-approval/v1"
BRAND_SUBJECT = "brand.identity"
# Brand facts that drive rendering must be approved decisions or canon; a
# conversation or learning signal can never set them.
BRAND_AUTHORITY_FLOOR = "APPROVED_PROJECT_DECISION"

# deliverable -> (N1 artifact type, fabric skill)
ROUTES: dict[Deliverable, tuple[str, str]] = {
    Deliverable.VECTOR_MARK: ("media_asset", "brand_logo_svg"),
    Deliverable.RASTER_IMAGE: ("media_asset", "t2i_image_generate"),
    Deliverable.GENERATED_VIDEO: ("media_asset", "ai_video_generate"),
    Deliverable.DESIGN_TOKENS: ("design_token_set", "dtcg_token_compile"),
}


class MissionNotReleasable(ValueError):
    pass


def _now(clock: Optional[datetime]) -> datetime:
    return clock or datetime.now(timezone.utc)


def _observed_counts(project_id: str) -> dict[str, int]:
    from services.langgraph.persistence.project_ops import list_jobs, list_publication_attempts

    return {"publication_attempts": len(list_publication_attempts(project_id)), "scheduled_jobs": len(list_jobs(project_id))}


def _event(principal: Principal, project_id: str, event_type: ActivityType, subject_ref: str, payload: dict) -> None:
    from services.langgraph.persistence.projects import append_project_event

    append_project_event(tenant_id=principal.tenant_id, project_id=project_id, event_type=event_type,
                         actor=principal.user_id, subject_ref=subject_ref, payload=payload)


def _predicates(mission_effects: tuple[SideEffect, ...]) -> list[AcceptancePredicate]:
    preds = [
        AcceptancePredicate(predicate_id="P1_PROJECT_BOUND", description="The request is bound to one accessible project."),
        AcceptancePredicate(predicate_id="P2_BRAND_CONTEXT", description="Brand facts come from approved project memory."),
        AcceptancePredicate(predicate_id="P3_ARTIFACT_PRODUCED", description="A real execution produced and persisted the artifact."),
        AcceptancePredicate(predicate_id="P4_ARTIFACT_VERIFIED", description="Independent read-back verification passed."),
        AcceptancePredicate(predicate_id="P5_HUMAN_APPROVED", description="A human approved this exact artifact version."),
    ]
    for effect in mission_effects:
        preds.append(AcceptancePredicate(predicate_id=f"P6_{effect.value}_AUTHORIZED",
                                         description=f"{effect.value.title()} is separately authorized by a human."))
    return preds


def _set(preds: list[AcceptancePredicate], pid: str, state: PredicateState, *, evidence=(), reasons=()) -> None:
    for i, p in enumerate(preds):
        if p.predicate_id == pid:
            preds[i] = p.model_copy(update={"state": state, "evidence": tuple(evidence), "reasons": tuple(reasons)})


def _existing_inputs(project_id: str) -> dict[str, str]:
    """Real upstream artifact heads (type -> content hash) for the planner."""
    from services.langgraph.persistence.projects import list_project_artifacts

    heads: dict[str, str] = {}
    for meta in list_project_artifacts(project_id, limit=1000):
        if meta.content_hash and meta.artifact_type not in heads:
            heads[meta.artifact_type] = meta.content_hash
    return heads


def _plan(project_id: str, artifact_type: str, objective: str, now: datetime, existing: dict[str, str]):
    from services.langgraph.agency.compiled.backchain import DeliverableSpec
    from services.langgraph.agency.compiled.planner import CompiledAgencyRequest, compile_agency_plan
    from services.langgraph.agency.execution_fabric.schedule import from_compiled_agency_plan
    from services.langgraph.agency.role_os import RoleOSRegistry

    root = Path(__file__).resolve().parents[4]
    spec = DeliverableSpec(id=artifact_type, requested_outcome=objective[:200], output_contract=artifact_type,
                           acceptance_criteria=("independent read-back verification passes",), domains=("BRAND",))
    existing = {k: v for k, v in existing.items() if k != artifact_type}
    request = CompiledAgencyRequest(project_id=project_id, as_of=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    deliverables=(spec,), existing_artifacts=existing)
    return from_compiled_agency_plan(compile_agency_plan(request, registry=RoleOSRegistry(root / "runtime" / "role_os")))


# --------------------------------------------------------------------------- verification


def verify_artifact(artifact_id: str, *, expected_version: int, adapter: StorageAdapter,
                    palette: Optional[dict[str, str]] = None, now: Optional[datetime] = None) -> ArtifactVerification:
    """Re-read the persisted artifact and check it independently of the producer."""
    import hashlib

    from services.langgraph.persistence.agency_kernel import get_artifact

    moment = _now(now).isoformat()
    head = get_artifact(artifact_id)
    checks: list[dict] = []
    findings: list[str] = []

    def done(status: str, version: int, content_hash: Optional[str]) -> ArtifactVerification:
        return ArtifactVerification(artifact_id=artifact_id, version=version, content_hash=content_hash, status=status,
                                    checks=tuple(checks), findings=tuple(findings),
                                    verifier="intake.verify_artifact/v1 (storage read-back)", verified_at=moment)

    if head is None:
        findings.append("ARTIFACT_MISSING")
        return done("FAILED", expected_version, None)
    version, recorded_hash, location = int(head["version"]), head.get("content_hash"), head.get("content_location")
    if version != expected_version:
        findings.append(f"VERSION_MISMATCH: head v{version} != produced v{expected_version}")
    try:
        data = adapter.get_bytes(location) if location else None
    except Exception as exc:  # noqa: BLE001 - any read failure is a verification failure, reported by class
        data = None
        findings.append(f"READ_BACK_FAILED: {type(exc).__name__}")
    if data is None:
        findings.append("NO_STORED_BYTES")
        return done("FAILED", version, recorded_hash)
    observed = hashlib.sha256(data).hexdigest()
    checks.append({"family": "FILE_INTEGRITY", "check": "sha256(read-back) == recorded content_hash",
                   "passed": observed == recorded_hash, "observed": observed})
    if observed != recorded_hash:
        findings.append("CONTENT_HASH_MISMATCH")
    mime = ((head.get("metadata") or {}).get("v2") or {}).get("mime_type")
    if mime == "image/svg+xml":
        text = data.decode("utf-8", errors="replace")
        try:
            root = ElementTree.fromstring(text)
            structural = root.tag.endswith("svg") and bool(root.get("viewBox"))
            checks.append({"family": "SCHEMA", "check": "root <svg> with viewBox", "passed": structural})
            if not structural:
                findings.append("SVG_STRUCTURE")
        except ElementTree.ParseError as exc:
            checks.append({"family": "SCHEMA", "check": "well-formed XML", "passed": False})
            findings.append(f"SVG_PARSE: {exc}")
        safety = svg_safety(text)
        checks.append({"family": "SECURITY", "check": "svg_safety", "passed": safety.passed, "detail": safety.detail})
        if not safety.passed:
            findings.append("SVG_UNSAFE")
        if palette:
            conformance = palette_conformance(text, palette.values())
            checks.append({"family": "BRAND_CONSISTENCY", "check": "palette_delta_e", "passed": conformance.passed,
                           "detail": conformance.detail})
            if not conformance.passed:
                findings.append("OFF_PALETTE")
        else:
            findings.append("NO_PALETTE_TO_CHECK")
    else:
        # No independent verifier for this media type yet: say so, never pass by default.
        findings.append(f"NO_INDEPENDENT_VERIFIER_FOR:{mime or 'unknown'}")
        return done("INCONCLUSIVE", version, recorded_hash)
    return done("FAILED" if findings else "PASSED", version, recorded_hash)


# --------------------------------------------------------------------------- mission


def run_mission(
    principal: Principal,
    raw_request: str,
    *,
    export_root: Path,
    requested_mode: Optional[ExecutionMode] = None,
    active_project_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    now: Optional[datetime] = None,
    adapter: Optional[StorageAdapter] = None,
    byte_budget: int = DEFAULT_BYTE_BUDGET,
) -> MissionOutcome:
    moment = _now(now)
    intent = compile_intent(raw_request, requested_mode=requested_mode)
    resolution = resolve_project(principal, intent, active_project_id=active_project_id, now=moment)
    base: dict[str, Any] = {"intent": intent, "resolution": resolution, "simulation": intent.mode is ExecutionMode.SIMULATION}
    if resolution.status != "BOUND" or resolution.project_id is None:
        return MissionOutcome(status="NEEDS_CLARIFICATION", reasons=(f"PROJECT_{resolution.status}", *resolution.reasons), **base)
    if intent.deliverable is None:
        return MissionOutcome(status="NEEDS_CLARIFICATION", reasons=("DELIVERABLE_UNKNOWN", *intent.clarifications), **base)

    project_id = resolution.project_id
    store = adapter or LocalStorageAdapter(export_root)
    counts_before = _observed_counts(project_id)
    artifact_type, skill_id = ROUTES[intent.deliverable]
    capsule, memory_receipt = compile_context(tenant_id=principal.tenant_id, project_id=project_id,
                                              subjects={BRAND_SUBJECT: BRAND_AUTHORITY_FLOOR}, thread_id=thread_id,
                                              now=moment, byte_budget=byte_budget,
                                              fingerprint=project_fingerprint(project_id, exclude_types=(artifact_type,)))
    mission_id = "msn-" + canonical_hash({"tenant": principal.tenant_id, "project": project_id, "request": intent.request_hash,
                                          "context": capsule.capsule_hash, "deliverable": intent.deliverable.value,
                                          "mode": intent.mode.value})[:32]
    preds = _predicates(intent.side_effects)
    _set(preds, "P1_PROJECT_BOUND", PredicateState.VERIFIED, evidence=(f"resolution:{resolution.reasons[-1]}",))

    brand: Optional[BrandContextCapsule] = None
    brand_entry = capsule.memory.get(BRAND_SUBJECT)
    if brand_entry is None:
        choice = next(c for c in memory_receipt.choices if c.subject_key == BRAND_SUBJECT)
        _set(preds, "P2_BRAND_CONTEXT", PredicateState.BLOCKED, reasons=(f"BRAND_CONTEXT_{choice.status}",))
    else:
        try:
            body = brand_entry["body"]
            brand = BrandContextCapsule(brand_name=body["brand_name"], palette=body["palette"])
            _set(preds, "P2_BRAND_CONTEXT", PredicateState.VERIFIED, evidence=(f"memory:{brand_entry['memory_id']}",))
        except (KeyError, TypeError, ValidationError) as exc:
            _set(preds, "P2_BRAND_CONTEXT", PredicateState.FAILED, reasons=(f"BRAND_CONTEXT_INVALID:{type(exc).__name__}",))

    mission = MissionContract(
        mission_id=mission_id, tenant_id=principal.tenant_id, project_id=project_id, thread_id=thread_id,
        requested_by=principal.user_id, objective=intent.raw_request, deliverable=intent.deliverable,
        artifact_type=artifact_type, side_effects=intent.side_effects, acceptance_predicates=tuple(preds),
        assumptions=tuple(f for f in intent.facts if f.fact_type.value in {"SAFE_DEFAULT", "AMBIGUOUS_NONCRITICAL"}),
        unknowns=capsule.unknowns, execution_mode=intent.mode, request_hash=intent.request_hash,
        context_hash=capsule.capsule_hash, created_at=moment.isoformat(),
    )
    _event(principal, project_id, ActivityType.WORK_STARTED, mission_id, {
        "intake_version": mission.intake_version, "mission_id": mission_id, "contract_hash": mission.contract_hash,
        "deliverable": intent.deliverable.value, "mode": intent.mode.value, "simulation": intent.mode is ExecutionMode.SIMULATION,
        "context_hash": capsule.capsule_hash,
    })

    def non_actions() -> tuple[NonActionReceipt, ...]:
        after = _observed_counts(project_id)
        receipts = tuple(NonActionReceipt(
            effect=effect, policy_gate="TWO_KEY_EFFECT_REQUIRED: no reviewed live adapter and no human authorization",
            observation="This mission issued no publication, outbox, spend or send call.",
            observed_counts_before=counts_before, observed_counts_after=after,
        ) for effect in intent.side_effects)
        for effect in intent.side_effects:
            _set(preds, f"P6_{effect.value}_AUTHORIZED", PredicateState.NEEDS_HUMAN, reasons=("EXTERNAL_EFFECT_NOT_AUTHORIZED",))
        return receipts

    def finish(status: str, *, reasons=(), execution=None, verification=None, approval=None) -> MissionOutcome:
        denied = non_actions()
        final = mission.model_copy(update={"acceptance_predicates": tuple(preds)})
        if status in {"BLOCKED", "FAILED"} or denied:
            _event(principal, project_id, ActivityType.QA_BLOCKED, mission_id, {
                "mission_id": mission_id, "status": status, "reasons": list(reasons),
                "denied_effects": [d.effect.value for d in denied], "dispatched": False,
            })
        sim = intent.mode is ExecutionMode.SIMULATION
        return MissionOutcome(status=status, memory=memory_receipt, context=capsule, mission=final, execution=execution,
                              verification=verification, approval=approval, non_actions=denied,
                              production_eligible=not sim and verification is not None and verification.status == "PASSED",
                              release_eligible=False, reasons=tuple(reasons), **base)

    if intent.mode is ExecutionMode.SIMULATION:
        for pid in ("P3_ARTIFACT_PRODUCED", "P4_ARTIFACT_VERIFIED", "P5_HUMAN_APPROVED"):
            _set(preds, pid, PredicateState.NOT_EXECUTED, reasons=("SIMULATION_MODE",))
        return finish("SIMULATED", reasons=("SIMULATION_MODE: nothing dispatched; outputs are not production evidence",))

    if brand is None:
        for pid in ("P3_ARTIFACT_PRODUCED", "P4_ARTIFACT_VERIFIED", "P5_HUMAN_APPROVED"):
            _set(preds, pid, PredicateState.BLOCKED, reasons=("UPSTREAM_P2_BRAND_CONTEXT",))
        return finish("BLOCKED", reasons=("BRAND_CONTEXT_NOT_ADMISSIBLE",))

    # ---- real execution through the existing fabric
    from services.langgraph.agency.execution_fabric.consumer import execute_mission
    from services.langgraph.agency.execution_fabric.contracts import ExecutionContext, ExecutionState

    schedule = _plan(project_id, artifact_type, intent.raw_request, moment, _existing_inputs(project_id))
    ctx = ExecutionContext.from_server(tenant_id=principal.tenant_id, project_id=project_id, actor=principal.user_id,
                                       mode="LOCAL", export_root=Path(export_root))
    report = execute_mission(schedule, ctx, brand=brand, skill_overrides={f"work:{artifact_type}": skill_id}, adapter=store)
    execution = report.model_dump(mode="json")
    cell = report.cells.get(f"cell:{artifact_type}")
    if cell is None or cell.state is not ExecutionState.SUCCEEDED or not cell.artifact_ref:
        state = cell.state.value if cell else "NOT_SCHEDULED"
        reasons = (f"EXECUTION_{state}", *(cell.reasons if cell else ()))
        _set(preds, "P3_ARTIFACT_PRODUCED", PredicateState.BLOCKED, reasons=reasons)
        for pid in ("P4_ARTIFACT_VERIFIED", "P5_HUMAN_APPROVED"):
            _set(preds, pid, PredicateState.BLOCKED, reasons=("UPSTREAM_P3_ARTIFACT_PRODUCED",))
        return finish("BLOCKED", reasons=reasons, execution=execution)

    artifact_id, version = cell.artifact_ref.rsplit(":v", 1)
    _set(preds, "P3_ARTIFACT_PRODUCED", PredicateState.VERIFIED, evidence=(cell.artifact_ref, f"run:{report.run_id}"))
    verification = verify_artifact(artifact_id, expected_version=int(version), adapter=store, palette=brand.palette, now=moment)
    _event(principal, project_id, ActivityType.VERIFIED if verification.status == "PASSED" else ActivityType.FAILED,
           f"{artifact_id}:v{version}", {"mission_id": mission_id, "verification": verification.model_dump(mode="json")})
    if verification.status != "PASSED":
        _set(preds, "P4_ARTIFACT_VERIFIED", PredicateState.FAILED if verification.status == "FAILED" else PredicateState.INCONCLUSIVE,
             reasons=verification.findings)
        _set(preds, "P5_HUMAN_APPROVED", PredicateState.BLOCKED, reasons=("UPSTREAM_P4_ARTIFACT_VERIFIED",))
        return finish("FAILED" if verification.status == "FAILED" else "BLOCKED", reasons=verification.findings,
                      execution=execution, verification=verification)
    _set(preds, "P4_ARTIFACT_VERIFIED", PredicateState.VERIFIED, evidence=(f"sha256:{verification.content_hash}",))

    approval = request_release_approval(principal, mission, verification)
    _set(preds, "P5_HUMAN_APPROVED", PredicateState.NEEDS_HUMAN, evidence=(f"approval:{approval['approval_id']}",))
    return finish("AWAITING_APPROVAL", reasons=("WAITING_FOR_HUMAN_APPROVAL",), execution=execution,
                  verification=verification, approval=approval)


# --------------------------------------------------------------------------- approval and release


def mission_run_id(mission_id: str) -> str:
    return approval_run_id(mission_id)


def request_release_approval(principal: Principal, mission: MissionContract, verification: ArtifactVerification) -> dict:
    """Open (or reuse) a pending approval bound to the exact verified artifact hash."""
    if mission.execution_mode is not ExecutionMode.REAL_EXECUTION:
        raise MissionNotReleasable("a simulated mission cannot request a release approval")
    if verification.status != "PASSED" or not verification.content_hash:
        raise MissionNotReleasable("only a verified artifact can be put up for approval")
    return open_artifact_approval(
        principal, tenant_id=mission.tenant_id, project_id=mission.project_id, mission_id=mission.mission_id,
        contract_hash=mission.contract_hash, artifact_id=verification.artifact_id, version=verification.version,
        content_hash=verification.content_hash, run_pipeline=RUN_PIPELINE, policy_version=APPROVAL_POLICY_VERSION,
        subject_type="MISSION_ARTIFACT", reason="Verified mission artifact requires human approval before release",
        metadata={"intake_version": mission.intake_version},
    )


def release_gate(outcome: MissionOutcome, *, approval_id: Optional[str] = None) -> ReleaseVerdict:
    """Fail closed unless a human approved this exact, still-current, verified artifact.

    It never performs a release or any external effect.
    """
    verification = outcome.verification
    mission = outcome.mission
    return artifact_release_verdict(
        simulated=outcome.simulation or bool(mission and mission.execution_mode is ExecutionMode.SIMULATION),
        verification_passed=verification is not None and verification.status == "PASSED",
        artifact_id=verification.artifact_id if verification else None,
        verified_version=verification.version if verification else None,
        verified_hash=verification.content_hash if verification else None,
        approval_id=approval_id or (outcome.approval or {}).get("approval_id"),
        tenant_id=mission.tenant_id if mission else None,
        project_id=mission.project_id if mission else None,
    )


__all__ = [
    "APPROVAL_POLICY_VERSION",
    "BRAND_AUTHORITY_FLOOR",
    "BRAND_SUBJECT",
    "MissionNotReleasable",
    "ROUTES",
    "RUN_PIPELINE",
    "mission_run_id",
    "release_gate",
    "request_release_approval",
    "run_mission",
    "verify_artifact",
]
