from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from services.langgraph.agency.design import UnknownStyleError, get_style
from services.langgraph.agency.design.style_composer import DesignStyleSelection
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.exporter import export_idea_workspace
from services.langgraph.agency.execution.models import (
    CompletionCriterionResult,
    CompletionEvaluation,
    CriterionStatus,
    DispatchPermit,
    ExecutionReceipt,
    FailureFingerprint,
    ObservationReceipt,
)
from services.langgraph.agency.kernel.lifecycle import TransitionContext, release_guard_failures
from services.langgraph.agency.reliability import IdempotencyStatus, PolicyEffect
from services.langgraph.app.runtime_support import trust_kernel
from services.langgraph.graph.agency.build import AGENCY_PIPELINE_STAGES, build_agency_workflow
from services.langgraph.graph.models import AgentRun
from services.langgraph.persistence.agency_kernel import (
    create_engagement,
    create_or_revise_artifact,
    create_or_revise_protected_run_artifact,
    ensure_artifact_dependency,
    get_engagement,
)
from services.langgraph.persistence.analytics import emit_lifecycle_event
from services.langgraph.persistence.approvals import bind_approval_subject, get_approvals_for_run, mark_approval_stale
from services.langgraph.persistence.events import record_event
from services.langgraph.persistence.idempotency import (
    complete_idempotency,
    fail_idempotency,
    hash_payload,
    reserve_idempotency,
)
from services.langgraph.persistence.invalidation import discharge_run_obligations, run_compile_gate
from services.langgraph.persistence.proofs import (
    get_run_proof_bundle,
    put_completion_evaluation,
    put_dispatch_permit,
    put_execution_receipt,
    put_failure_fingerprint,
    put_observation_receipt,
)
from services.langgraph.persistence.runs import (
    compare_and_set_run_status,
    create_run_record,
    get_run_record,
    update_run_status,
)
from services.langgraph.security.auth import Principal, authorize_project, authorize_resource, get_principal
from services.langgraph.security.pii import quarantine_payload
from services.langgraph.security.preprocess import sanitize_deep

router = APIRouter()

PIPELINE_NAME = "branding_marketing_agency"
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


class CampaignBriefRequest(BaseModel):
    brand_name: str
    industry: Optional[str] = None
    business_idea: Optional[str] = None
    offer_summary: Optional[str] = None
    product_type: Optional[str] = None
    goals: List[str] = Field(default_factory=list)
    target_audience: str
    tone: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    business_model: Optional[str] = None
    affiliate_model: Optional[bool] = None
    workflow_idea: Optional[str] = None
    differentiators: List[str] = Field(default_factory=list)
    brand_style_notes: List[str] = Field(default_factory=list)
    style_selection: Optional[DesignStyleSelection] = None

    @field_validator("style_selection")
    @classmethod
    def _styles_exist(cls, value: Optional[DesignStyleSelection]) -> Optional[DesignStyleSelection]:
        # Reject unknown styles at the boundary; the design_brief node still
        # handles a style that disappears from the catalog before it runs.
        if value is not None:
            for layer in value.selections:
                try:
                    get_style(layer.style_id)
                except UnknownStyleError as exc:
                    raise ValueError(f"unknown style {layer.style_id!r}") from exc
        return value


class CreateAgencyRunRequest(BaseModel):
    tenant_id: Optional[str] = None
    project_id: str
    brief: CampaignBriefRequest


class RebindArtifactRequest(BaseModel):
    artifact_key: str
    revision_note: str = Field(min_length=1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _agency_payload(state: dict) -> dict:
    return (state.get("extracted_data") or {}).get("agency", {}) if state else {}


def _safe_brief(req: CreateAgencyRunRequest) -> dict:
    return quarantine_payload(sanitize_deep(req.brief.model_dump()))


def _agency_subject_hash(agency_data: dict) -> str:
    return hash_payload(
        {
            "campaign_package": agency_data.get("campaign_package"),
            "qa_report": agency_data.get("qa_report"),
            "generation_provenance": agency_data.get("generation_provenance", []),
            "degraded": bool(agency_data.get("degraded")),
        }
    )


def _materialize_workspace_export(*, run_id: str, agency_data: dict) -> dict | None:
    package = agency_data.get("campaign_package")
    if not isinstance(package, dict):
        return None
    brief = package.get("brief") or {}
    brand_name = brief.get("brand_name")
    if not isinstance(brand_name, str) or not brand_name.strip():
        return None
    workspace_export = export_idea_workspace(
        brand_name=brand_name,
        run_id=run_id,
        package=package,
    )
    package["workspace_export"] = workspace_export
    agency_data["campaign_package"] = package
    return workspace_export


def _workspace_artifact_specs(*, run_id: str, workspace_export: dict, package: dict) -> list[dict]:
    root_folder = workspace_export["root_folder"]
    business_workspace = package.get("business_workspace") or {}
    branding_workspace = package.get("branding_workspace") or {}
    design_system = package.get("design_system") or {}
    asset_execution = package.get("asset_execution") or {}
    return [
        {
            "artifact_key": "business_model_spec",
            "artifact_type": "business_model_spec",
            "owner_department": "strategy",
            "content_location": f"{root_folder}/business",
            "payload": {
                "overview": business_workspace.get("overview"),
                "internal_docs": business_workspace.get("internal_docs", []),
                "production_docs": business_workspace.get("production_docs", []),
            },
            "depends_on": [],
        },
        {
            "artifact_key": "brand_core",
            "artifact_type": "brand_core",
            "owner_department": "brand",
            "content_location": f"{root_folder}/branding/raw",
            "payload": {
                "raw_brand_data": branding_workspace.get("raw_brand_data"),
                "internal_assets": branding_workspace.get("internal_assets", []),
                "external_assets": branding_workspace.get("external_assets", []),
            },
            "depends_on": ["business_model_spec"],
        },
        {
            "artifact_key": "asset_prompt_set",
            "artifact_type": "asset_prompt_set",
            "owner_department": "creative",
            "content_location": f"{root_folder}/branding/prompts",
            "payload": {
                "visual_asset_prompts": branding_workspace.get("visual_asset_prompts", []),
            },
            "depends_on": ["brand_core"],
        },
        {
            "artifact_key": "design_token_set",
            "artifact_type": "design_token_set",
            "owner_department": "design",
            "content_location": f"{root_folder}/branding/design-system/tokens.json",
            "payload": {
                "tokens_json": design_system.get("tokens_json"),
                "tailwind_config": design_system.get("tailwind_config"),
                "global_tokens_css": design_system.get("global_tokens_css"),
            },
            "depends_on": ["brand_core"],
        },
        {
            "artifact_key": "design_system_spec",
            "artifact_type": "design_system_spec",
            "owner_department": "design",
            "content_location": f"{root_folder}/branding/design-system",
            "payload": {
                "component_scaffolds": design_system.get("component_scaffolds", []),
                "asset_recipes": design_system.get("asset_recipes", []),
                "validation_notes": design_system.get("validation_notes", []),
            },
            "depends_on": ["design_token_set", "asset_prompt_set"],
        },
        {
            "artifact_key": "website_lockup_spec",
            "artifact_type": "website_lockup_spec",
            "owner_department": "design",
            "content_location": f"{root_folder}/branding/rendered",
            "payload": {
                "rendered_assets": asset_execution.get("rendered_assets", []),
                "review_queue": asset_execution.get("review_queue"),
                "publishing_adapters": asset_execution.get("publishing_adapters", []),
            },
            "depends_on": ["design_system_spec", "asset_prompt_set"],
        },
        {
            "artifact_key": "campaign_package",
            "artifact_type": "campaign_package",
            "owner_department": "growth",
            "content_location": f"{root_folder}/workspace-package.json",
            "payload": {
                "brief": package.get("brief"),
                "strategy": package.get("strategy"),
                "concepts": package.get("concepts", []),
                "copy_variants": package.get("copy_variants", []),
                "design_brief": package.get("design_brief"),
                "workspace_export": workspace_export,
            },
            "depends_on": [
                "business_model_spec",
                "brand_core",
                "asset_prompt_set",
                "design_token_set",
                "design_system_spec",
                "website_lockup_spec",
            ],
        },
    ]


def _bind_workspace_export_artifacts(
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    package: dict,
    workspace_export: dict | None,
) -> list[dict]:
    if workspace_export is None:
        return []
    engagement_id = f"eng-workspace-{run_id}"
    if not get_engagement(engagement_id):
        create_engagement(
            engagement_id,
            tenant_id,
            project_id,
            "Workspace export artifact graph",
            "Canonical artifact bindings for user-visible business, branding, design-system, and rendered outputs",
            status="active",
        )
    artifact_specs = _workspace_artifact_specs(run_id=run_id, workspace_export=workspace_export, package=package)
    revisions_by_key: dict[str, dict] = {}
    bindings: list[dict] = []
    for spec in artifact_specs:
        artifact_id = f"art-{run_id}-{spec['artifact_key']}"
        payload = spec["payload"]
        content_hash = hash_payload(payload)
        revision = create_or_revise_artifact(
            artifact_id=artifact_id,
            engagement_id=engagement_id,
            tenant_id=tenant_id,
            project_id=project_id,
            artifact_type=spec["artifact_type"],
            owner_department=spec["owner_department"],
            content_hash=content_hash,
            content_location=spec["content_location"],
            semantic_fingerprint=canonical_hash(payload),
            metadata={
                "run_id": run_id,
                "artifact_key": spec["artifact_key"],
                "export_root": workspace_export["root_folder"],
                "canonical_workspace_export_artifact": True,
            },
        )
        revisions_by_key[spec["artifact_key"]] = revision
        artifact = revision["artifact"]
        bindings.append(
            {
                "artifact_key": spec["artifact_key"],
                "artifact_id": artifact["artifact_id"],
                "artifact_type": artifact["artifact_type"],
                "owner_department": artifact["owner_department"],
                "version": artifact["version"],
                "version_ref": f"{artifact['artifact_id']}:v{artifact['version']}",
                "content_location": artifact.get("content_location"),
                "content_hash": artifact.get("content_hash"),
                "changed": revision["changed"],
                "created": revision["created"],
            }
        )
    for spec in artifact_specs:
        artifact_id = revisions_by_key[spec["artifact_key"]]["artifact"]["artifact_id"]
        for dependency_key in spec["depends_on"]:
            upstream_id = revisions_by_key[dependency_key]["artifact"]["artifact_id"]
            ensure_artifact_dependency(artifact_id, upstream_id)
    return bindings


def _ensure_protected_run_artifact(
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    approval_id: str | None,
    subject_hash: str,
) -> tuple[str, str]:
    revision = create_or_revise_protected_run_artifact(
        run_id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        approval_id=approval_id,
        content_hash=subject_hash,
    )
    artifact = revision["artifact"]
    if not artifact:
        raise RuntimeError("Protected run artifact could not be materialized")
    artifact_id = artifact["artifact_id"]
    return artifact_id, f"{artifact_id}:v{artifact['version']}"


def _project_snapshot_hash(*, run_id: str, project_id: str, phase: str, status: str, subject_hash: str | None = None) -> str:
    return canonical_hash(
        {
            "run_id": run_id,
            "project_id": project_id,
            "phase": phase,
            "status": status,
            "subject_hash": subject_hash,
        }
    )


def _apply_artifact_revision_note(*, agency_data: dict, artifact_key: str, revision_note: str) -> None:
    package = agency_data.get("campaign_package")
    if not isinstance(package, dict):
      raise HTTPException(status_code=409, detail="Run does not have a compiled campaign package")

    note = revision_note.strip()
    if not note:
      raise HTTPException(status_code=422, detail="revision_note must not be empty")

    if artifact_key == "asset_prompt_set":
        branding_workspace = package.setdefault("branding_workspace", {})
        prompts = branding_workspace.setdefault("visual_asset_prompts", [])
        if prompts:
            prompts[0]["body"] = f"{prompts[0].get('body', '').rstrip()}\n{note}"
        else:
            prompts.append(
                {
                    "path": "branding/prompts/revision-note.md",
                    "title": "Revision note",
                    "kind": "prompt",
                    "body": note,
                    "metadata": {"source": "artifact_rebind"},
                }
            )
    elif artifact_key == "brand_core":
        branding_workspace = package.setdefault("branding_workspace", {})
        raw_brand_data = branding_workspace.setdefault("raw_brand_data", {})
        notes = raw_brand_data.setdefault("revision_notes", [])
        if isinstance(notes, list):
            notes.append(note)
        else:
            raw_brand_data["revision_notes"] = [str(notes), note]
    elif artifact_key == "business_model_spec":
        business_workspace = package.setdefault("business_workspace", {})
        internal_docs = business_workspace.setdefault("internal_docs", [])
        if internal_docs:
            internal_docs[0]["body"] = f"{internal_docs[0].get('body', '').rstrip()}\n{note}"
        else:
            internal_docs.append(
                {
                    "path": "business/internal/revision-note.md",
                    "title": "Revision note",
                    "kind": "internal_doc",
                    "body": note,
                    "metadata": {"source": "artifact_rebind"},
                }
            )
    elif artifact_key == "design_token_set":
        design_system = package.setdefault("design_system", {})
        validation_notes = design_system.setdefault("validation_notes", [])
        validation_notes.append(note)
    elif artifact_key == "design_system_spec":
        design_system = package.setdefault("design_system", {})
        scaffolds = design_system.setdefault("component_scaffolds", [])
        if scaffolds:
            scaffolds[0]["body"] = f"{scaffolds[0].get('body', '').rstrip()}\n{note}"
        else:
            scaffolds.append(
                {
                    "path": "branding/design-system/components/revision-note.tsx",
                    "title": "Revision note",
                    "kind": "component_scaffold",
                    "body": note,
                    "metadata": {"source": "artifact_rebind"},
                }
            )
    elif artifact_key == "website_lockup_spec":
        copy_variants = package.setdefault("copy_variants", [])
        if copy_variants:
            copy_variants[0]["body"] = f"{copy_variants[0].get('body', '').rstrip()}\n{note}"
        else:
            raise HTTPException(status_code=409, detail="Run does not have a website lockup payload to revise")
    elif artifact_key == "campaign_package":
        package.setdefault("revision_notes", []).append(note)
    else:
        raise HTTPException(status_code=404, detail=f"Unsupported artifact binding: {artifact_key}")
    agency_data["campaign_package"] = package


def _issue_dispatch_permit(
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    phase: str,
    subject_hash: str | None = None,
    approval_refs: tuple[str, ...] = (),
    authority_refs: tuple[str, ...] = (),
) -> dict:
    permit = DispatchPermit(
        permit_id=str(uuid4()),
        work_order_id=run_id,
        project_snapshot_hash=_project_snapshot_hash(
            run_id=run_id,
            project_id=project_id,
            phase=phase,
            status="dispatch_ready",
            subject_hash=subject_hash,
        ),
        causal_epoch=0,
        approval_refs=approval_refs,
        authority_refs=authority_refs,
        tool_contract_refs=("amc.agency.workflow/v1",),
        eligibility_policy_version="amc-dispatch/v1",
    )
    return put_dispatch_permit(run_id, tenant_id, project_id, permit)


def _record_execution_phase(
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    operation_id: str,
    actor_role_id: str,
    args_payload: dict,
    started_at: datetime,
    ended_at: datetime,
    returned_state: str,
    result_ref: str | None,
) -> dict:
    receipt = ExecutionReceipt(
        operation_id=operation_id,
        work_order_id=run_id,
        actor_role_id=actor_role_id,
        tool="langgraph.workflow",
        tool_contract_ref="amc.agency.workflow/v1",
        args_hash=hash_payload(args_payload),
        target=run_id,
        idempotency_key=hash_payload({"operation_id": operation_id, "run_id": run_id}),
        attempt=1,
        started_at=started_at,
        ended_at=ended_at,
        returned_state=returned_state,
        result_ref=result_ref,
    )
    return put_execution_receipt(run_id, tenant_id, project_id, receipt)


def _record_observation_phase(
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    operation_id: str,
    expected_postcondition: dict,
    observed_postcondition: dict,
    evidence_refs: tuple[str, ...] = (),
) -> dict:
    matches = expected_postcondition == observed_postcondition
    receipt = ObservationReceipt(
        operation_id=operation_id,
        target=run_id,
        expected_postcondition=expected_postcondition,
        observed_postcondition=observed_postcondition,
        observation_method="run_state_projection",
        evidence_refs=evidence_refs,
        matches=matches,
    )
    return put_observation_receipt(run_id, tenant_id, project_id, receipt)


def _record_failure(
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    operation_id: str,
    args_payload: dict,
    error_class: str,
    observed_postcondition: dict | None = None,
) -> dict:
    payload_hash = hash_payload(args_payload)
    fingerprint = FailureFingerprint(
        fingerprint=canonical_hash(
            {
                "run_id": run_id,
                "operation_id": operation_id,
                "error_class": error_class,
                "payload_hash": payload_hash,
            }
        ),
        failure_class="EXECUTION_FAILURE",
        causal_node=operation_id,
        work_order_input_hash=payload_hash,
        dependency_snapshot_hash=canonical_hash({"run_id": run_id, "project_id": project_id}),
        tool_contract_hash=canonical_hash("amc.agency.workflow/v1"),
        environment_signature=PIPELINE_NAME,
        error_class=error_class,
        observed_postcondition=observed_postcondition,
    )
    return put_failure_fingerprint(run_id, tenant_id, project_id, operation_id, fingerprint)


def _record_completion(
    *,
    run_id: str,
    tenant_id: str,
    project_id: str,
    terminal_candidate: str,
    proof_coverage: float,
    confidence: float,
    criteria: list[CompletionCriterionResult],
) -> dict:
    evaluation = CompletionEvaluation(
        terminal_candidate=terminal_candidate,  # type: ignore[arg-type]
        criteria=tuple(criteria),
        proof_coverage=proof_coverage,
        evidence_score=proof_coverage,
        quality_score=proof_coverage,
        confidence=confidence,
    )
    return put_completion_evaluation(run_id, tenant_id, project_id, evaluation)


def _run_and_record_events(graph, input_state, config: dict, run: AgentRun) -> dict:
    """
    Execute synchronously and persist causally honest completion observations.

    The current execution API does not expose a pre-node callback from this
    wrapper, so we intentionally do NOT fabricate node_start timestamps. Each
    event records the point at which a completed node update was observed.
    """

    for step in graph.stream(input_state, config=config, stream_mode="updates"):
        for node_id, _delta in step.items():
            if node_id == "__interrupt__":
                continue
            completed_at = _now()
            record_event(
                str(run.id),
                run.tenant_id,
                run.project_id,
                node_id,
                "node_complete",
                observed_at=completed_at,
                completed_at=completed_at,
            )

    snapshot = graph.get_state(config)
    return dict(snapshot.values) if snapshot and snapshot.values else {}


def _delivery_context(stored_agency: dict, approval: Optional[dict]) -> TransitionContext:
    """Build the N2 guard context from the run's persisted facts.

    ``brand_safety_advisory`` is True because this route's established policy is
    that the HITL gate is the authority: a reviewer may approve a campaign whose
    brand-safety heuristic flagged terms. Degraded provider output is *not*
    discharged that way and remains a hard block.
    """
    qa_report = stored_agency.get("qa_report") or {}
    return TransitionContext(
        # release_blocked is set by brand_safety_qa when any generation stage
        # fell back, so it is the persisted form of degraded provenance.
        generation_mode="FALLBACK_DEGRADED" if qa_report.get("release_blocked") else "PROVIDER_SUCCESS",
        approval_exists=approval is not None,
        approval_resolved=bool(approval and approval.get("status") == "resolved"),
        approval_decision=(approval or {}).get("decision"),
        brand_safety_passed=bool(qa_report.get("brand_safety_passed")),
        brand_safety_advisory=True,
    )


# Guard codes that represent a substantive release block worth recording in
# lifecycle analytics, as opposed to a run simply awaiting its approval
# decision. Matches the pre-refactor emission behavior.
_ANALYTICS_REPORTED_BLOCKS = frozenset({"degraded_release_block", "brand_safety_failed", "spend_unauthorized"})

_DELIVERY_BLOCK_DETAIL = {
    "degraded_release_block": lambda _approval: (
        "Run contains degraded provider output and cannot be delivered; "
        "rerun with a configured provider"
    ),
    "approval_missing": lambda _approval: "No approval found for this run",
    "approval_pending": lambda _approval: "Run still has an unresolved approval",
    "approval_not_approved": lambda approval: (
        f"Run was not approved (decision={(approval or {}).get('decision')})"
    ),
    "brand_safety_failed": lambda _approval: (
        "Run failed brand-safety review and cannot be delivered"
    ),
    "spend_unauthorized": lambda _approval: (
        "Delivery requires an explicit spend/publication authorization"
    ),
}


def _authorize_run(principal: Principal, record: dict) -> None:
    authorize_resource(principal, record["tenant_id"], record["project_id"])


def _idempotency_scope(principal: Principal, operation: str, resource: str) -> str:
    return f"{principal.tenant_id}:{principal.user_id}:{operation}:{resource}"


def _reserve_or_replay(scope: str, key: str, request_hash: str) -> Optional[dict]:
    reservation = reserve_idempotency(scope, key, request_hash, IDEMPOTENCY_TTL_SECONDS)
    state = reservation["state"]
    if state == "replay":
        return reservation["record"]["result"]
    if state == "in_progress":
        raise HTTPException(status_code=409, detail="Equivalent request is already executing")
    if state == "conflict":
        raise HTTPException(status_code=409, detail="Idempotency-Key was reused with different input")
    return None


@router.post("/runs", status_code=201)
def create_agency_run(
    req: CreateAgencyRunRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    authorize_project(principal, req.project_id)
    if req.tenant_id is not None and req.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="tenant_id does not match authenticated principal")

    safe_brief = _safe_brief(req)
    scope = _idempotency_scope(principal, "agency.create", req.project_id)
    request_hash = hash_payload({"project_id": req.project_id, "brief": safe_brief})
    replay = _reserve_or_replay(scope, idempotency_key, request_hash)
    if replay is not None:
        return replay

    run_id = str(uuid4())
    trust = trust_kernel()
    trust.bind_project(tenant_id=principal.tenant_id, project_id=req.project_id)
    trust.record_policy_decision(
        tenant_id=principal.tenant_id,
        project_id=req.project_id,
        decision_id=f"policy-agency-create-{run_id}",
        subject_ref=run_id,
        action="agency.create",
        target="campaign_package",
        policy_version="amc-trust/v1",
        policy_input={"project_id": req.project_id, "brief": safe_brief},
        effect=PolicyEffect.ALLOW,
    )
    trust.claim_idempotency(
        tenant_id=principal.tenant_id,
        project_id=req.project_id,
        idempotency_key=idempotency_key,
        operation_id=f"agency.create:{req.project_id}",
        request={"project_id": req.project_id, "brief": safe_brief},
    )
    now = datetime.now(timezone.utc)
    metadata = {"input_data": {"brief": safe_brief}}
    run = AgentRun(
        id=run_id,
        tenant_id=principal.tenant_id,
        project_id=req.project_id,
        status="running",
        created_at=now,
        updated_at=now,
        metadata=metadata,
    )
    create_run_record(run_id, principal.tenant_id, req.project_id, PIPELINE_NAME, "running", metadata)
    emit_lifecycle_event(
        principal.tenant_id,
        req.project_id,
        "agency_run_created",
        {"pipeline": PIPELINE_NAME, "status": "running"},
        run_id,
    )

    graph = build_agency_workflow()
    config = _run_config(run_id)
    _issue_dispatch_permit(
        run_id=run_id,
        tenant_id=principal.tenant_id,
        project_id=req.project_id,
        phase="generation",
    )
    initial_state = {
        "run": run,
        "current_node": "start",
        "messages": [],
        "extracted_data": {},
        "validation_status": "pending",
    }
    started_at = datetime.now(timezone.utc)
    try:
        state = _run_and_record_events(graph, initial_state, config, run)
    except Exception as exc:
        ended_at = datetime.now(timezone.utc)
        _record_execution_phase(
            run_id=run_id,
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            operation_id=f"agency.create:{run_id}",
            actor_role_id="agency-orchestrator",
            args_payload={"project_id": req.project_id, "brief": safe_brief},
            started_at=started_at,
            ended_at=ended_at,
            returned_state="FAILED",
            result_ref=None,
        )
        _record_failure(
            run_id=run_id,
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            operation_id=f"agency.create:{run_id}",
            args_payload={"project_id": req.project_id, "brief": safe_brief},
            error_class=type(exc).__name__,
        )
        _record_completion(
            run_id=run_id,
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            terminal_candidate="BLOCKED",
            proof_coverage=0.25,
            confidence=0.25,
            criteria=[CompletionCriterionResult(criterion_ref="execution", status=CriterionStatus.BLOCKED)],
        )
        update_run_status(run_id, "failed", {"error": type(exc).__name__})
        trust.open_recovery_case(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            operation_id=f"agency.create:{run_id}",
            reason="EXECUTION_WITHOUT_OBSERVATION",
            execution_ref=run_id,
            idempotency_key=idempotency_key,
            evidence_refs=(type(exc).__name__,),
        )
        record_event(run_id, run.tenant_id, run.project_id, "pipeline", "node_error", safe_payload={"error_class": type(exc).__name__})
        emit_lifecycle_event(
            run.tenant_id,
            run.project_id,
            "agency_run_failed",
            {"pipeline": PIPELINE_NAME, "phase": "generation", "error_class": type(exc).__name__},
            run_id,
        )
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=run_id, status=IdempotencyStatus.FAILED)
        raise HTTPException(status_code=500, detail="Agency pipeline failed") from exc

    ended_at = datetime.now(timezone.utc)
    _record_execution_phase(
        run_id=run_id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        operation_id=f"agency.create:{run_id}",
        actor_role_id="agency-orchestrator",
        args_payload={"project_id": req.project_id, "brief": safe_brief},
        started_at=started_at,
        ended_at=ended_at,
        returned_state="NEEDS_APPROVAL",
        result_ref=run_id,
    )
    agency_data = _agency_payload(state)
    workspace_export = _materialize_workspace_export(run_id=run_id, agency_data=agency_data)
    agency_data["artifact_bindings"] = _bind_workspace_export_artifacts(
        run_id=run_id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        package=agency_data.get("campaign_package") or {},
        workspace_export=workspace_export,
    )
    record = update_run_status(run_id, "needs_approval", {"agency": agency_data})
    run_approvals = get_approvals_for_run(run_id)
    subject_hash = _agency_subject_hash(agency_data)
    _record_observation_phase(
        run_id=run_id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        operation_id=f"agency.create:{run_id}",
        expected_postcondition={"status": "needs_approval", "campaign_package": True},
        observed_postcondition={"status": record["status"], "campaign_package": bool(agency_data.get("campaign_package"))},
        evidence_refs=(subject_hash,),
    )
    if run_approvals:
        protected_artifact_id, protected_version_ref = _ensure_protected_run_artifact(
            run_id=run_id,
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            approval_id=run_approvals[0]["approval_id"],
            subject_hash=subject_hash,
        )
        bind_approval_subject(
            run_approvals[0]["approval_id"],
            subject_hash=subject_hash,
            subject_ref=protected_artifact_id,
            subject_version_ref=protected_version_ref,
            authority_ref="human-review",
            policy_version="amc-approval/v1",
        )
        run_approvals = get_approvals_for_run(run_id)
        record_event(
            run_id,
            principal.tenant_id,
            req.project_id,
            "hitl_gate",
            "approval_requested",
            safe_payload={
                "approval_id": run_approvals[0]["approval_id"],
                "status": run_approvals[0]["status"],
                "reason": run_approvals[0]["reason"],
                "confidence": run_approvals[0]["confidence"],
            },
        )
    release_blocked = bool((agency_data.get("qa_report") or {}).get("release_blocked"))
    emit_lifecycle_event(
        principal.tenant_id,
        req.project_id,
        "agency_run_needs_approval",
        {
            "pipeline": PIPELINE_NAME,
            "status": record["status"],
            "degraded": bool(agency_data.get("degraded")),
            "release_blocked": release_blocked,
        },
        run_id,
    )
    response = {
        "run_id": run_id,
        "project_id": req.project_id,
        "status": record["status"],
        "pipeline": PIPELINE_NAME,
        "stages": AGENCY_PIPELINE_STAGES,
        "campaign_package": agency_data.get("campaign_package"),
        "workspace_export": agency_data.get("campaign_package", {}).get("workspace_export"),
        "artifact_bindings": agency_data.get("artifact_bindings", []),
        "qa_report": agency_data.get("qa_report"),
        "pending_approval": run_approvals[0] if run_approvals else None,
        "degraded": bool(agency_data.get("degraded")),
        "generation_provenance": agency_data.get("generation_provenance", []),
        }
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize idempotency record")
    _record_completion(
        run_id=run_id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        terminal_candidate="BLOCKED",
        proof_coverage=0.67,
        confidence=0.72,
        criteria=[
            CompletionCriterionResult(criterion_ref="execution", status=CriterionStatus.SATISFIED),
            CompletionCriterionResult(criterion_ref="observation", status=CriterionStatus.SATISFIED),
            CompletionCriterionResult(criterion_ref="approval", status=CriterionStatus.BLOCKED),
        ],
    )
    trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=run_id)
    response["proof"] = get_run_proof_bundle(run_id)
    return response


@router.get("/runs/{run_id}")
def get_agency_run(run_id: str, principal: Principal = Depends(get_principal)):
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    _authorize_run(principal, record)

    graph = build_agency_workflow()
    snapshot = graph.get_state(_run_config(run_id))
    agency_data = _agency_payload(dict(snapshot.values)) if snapshot and snapshot.values else {}
    stored_agency = (record.get("result") or {}).get("agency", {})
    if stored_agency:
        merged_package = {
            **((stored_agency.get("campaign_package") or {}) if isinstance(stored_agency.get("campaign_package"), dict) else {}),
            **((agency_data.get("campaign_package") or {}) if isinstance(agency_data.get("campaign_package"), dict) else {}),
        }
        agency_data = {**stored_agency, **agency_data}
        if merged_package:
            agency_data["campaign_package"] = merged_package
    return {
        "run_id": run_id,
        "project_id": record["project_id"],
        "status": record["status"],
        "pipeline": record["pipeline"],
        "stages": AGENCY_PIPELINE_STAGES,
        "pending_next_node": list(snapshot.next) if snapshot else [],
        "campaign_package": agency_data.get("campaign_package"),
        "workspace_export": agency_data.get("campaign_package", {}).get("workspace_export"),
        "artifact_bindings": agency_data.get("artifact_bindings", []),
        "qa_report": agency_data.get("qa_report"),
        "delivery": agency_data.get("delivery"),
        "approvals": get_approvals_for_run(run_id),
        "degraded": bool(agency_data.get("degraded")),
        "generation_provenance": agency_data.get("generation_provenance", []),
        "proof": get_run_proof_bundle(run_id),
    }


@router.post("/runs/{run_id}/artifacts/rebind")
def rebind_agency_run_artifact(
    run_id: str,
    req: RebindArtifactRequest,
    principal: Principal = Depends(get_principal),
):
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    _authorize_run(principal, record)

    stored_agency = (record.get("result") or {}).get("agency", {})
    if not isinstance(stored_agency, dict) or not stored_agency.get("campaign_package"):
        raise HTTPException(status_code=409, detail="Run has no compiled agency payload")

    agency_data = {**stored_agency}
    package = dict(stored_agency.get("campaign_package") or {})
    agency_data["campaign_package"] = package
    _apply_artifact_revision_note(
        agency_data=agency_data,
        artifact_key=req.artifact_key,
        revision_note=req.revision_note,
    )
    workspace_export = _materialize_workspace_export(run_id=run_id, agency_data=agency_data)
    agency_data["artifact_bindings"] = _bind_workspace_export_artifacts(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        package=agency_data.get("campaign_package") or {},
        workspace_export=workspace_export,
    )
    updated = update_run_status(run_id, record["status"], {"agency": agency_data})
    binding = next(
        (item for item in agency_data.get("artifact_bindings", []) if item["artifact_key"] == req.artifact_key),
        None,
    )
    record_event(
        run_id,
        record["tenant_id"],
        record["project_id"],
        "campaign_assembly",
        "artifact_generated",
        safe_payload={
            "artifact_key": req.artifact_key,
            "version": binding["version"] if binding else None,
            "changed": binding["changed"] if binding else None,
            "created": binding["created"] if binding else None,
        },
    )
    return {
        "run_id": run_id,
        "project_id": record["project_id"],
        "status": updated["status"],
        "pipeline": record["pipeline"],
        "stages": AGENCY_PIPELINE_STAGES,
        "campaign_package": agency_data.get("campaign_package"),
        "workspace_export": agency_data.get("campaign_package", {}).get("workspace_export"),
        "artifact_bindings": agency_data.get("artifact_bindings", []),
        "qa_report": agency_data.get("qa_report"),
        "pending_approval": None,
        "degraded": bool(agency_data.get("degraded")),
        "generation_provenance": agency_data.get("generation_provenance", []),
        "proof": get_run_proof_bundle(run_id),
    }


@router.post("/runs/{run_id}/resume")
def resume_agency_run(
    run_id: str,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal: Principal = Depends(get_principal),
):
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="Run not found")
    _authorize_run(principal, record)

    scope = _idempotency_scope(principal, "agency.resume", run_id)
    replay = _reserve_or_replay(scope, idempotency_key, hash_payload({"run_id": run_id}))
    if replay is not None:
        return replay
    trust = trust_kernel()
    trust.claim_idempotency(
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        idempotency_key=idempotency_key,
        operation_id=f"agency.resume:{run_id}",
        request={"run_id": run_id},
    )

    if record["status"] == "completed":
        stored_agency = (record["result"] or {}).get("agency", {})
        response = {
            "run_id": run_id,
            "project_id": record["project_id"],
            "status": "completed",
            "delivery": stored_agency.get("delivery"),
            "campaign_package": stored_agency.get("campaign_package"),
            "workspace_export": (stored_agency.get("campaign_package") or {}).get("workspace_export"),
            "artifact_bindings": stored_agency.get("artifact_bindings", []),
        }
        complete_idempotency(scope, idempotency_key, response)
        trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=run_id)
        return response

    if record["status"] != "needs_approval":
        fail_idempotency(scope, idempotency_key, f"invalid_status:{record['status']}")
        raise HTTPException(status_code=409, detail=f"Run is not awaiting delivery (status={record['status']})")

    stored_agency = (record.get("result") or {}).get("agency", {})
    run_approvals = get_approvals_for_run(run_id)
    latest = run_approvals[0] if run_approvals else None
    current_subject_hash = _agency_subject_hash(stored_agency)
    if latest and latest.get("subject_hash") and latest["subject_hash"] != current_subject_hash:
        mark_approval_stale(latest["approval_id"], "run_result_hash_changed")
        trust_kernel().open_recovery_case(
            tenant_id=record["tenant_id"],
            project_id=record["project_id"],
            operation_id=f"agency.resume:{run_id}",
            reason="OBSERVATION_MISMATCH",
            observation_ref=run_id,
            evidence_refs=(latest["subject_hash"], current_subject_hash),
        )
        fail_idempotency(scope, idempotency_key, "approval_stale")
        raise HTTPException(status_code=409, detail="Approval is stale because the protected run output changed")

    compile_gate = run_compile_gate(run_id)
    if compile_gate["compile_blocked"]:
        fail_idempotency(scope, idempotency_key, "compile_blocked")
        raise HTTPException(
            status_code=409,
            detail="Run delivery is blocked by open invalidation obligations or stale approvals",
        )

    # Delivery is gated by the declared N2 release guards rather than by ad-hoc
    # checks, so the transition matrix stays the single authority on what may
    # reach a client. The guard codes map onto this route's existing error
    # contract below; behavior is unchanged.
    failures = release_guard_failures(_delivery_context(stored_agency, latest))
    if failures:
        blocker = failures[0]
        # A run blocked on its own approval state is an ordinary interaction —
        # someone resumed before deciding — so it stays out of the lifecycle
        # analytics stream. Only a substantive release block is recorded.
        if blocker.code in _ANALYTICS_REPORTED_BLOCKS:
            emit_lifecycle_event(
                record["tenant_id"],
                record["project_id"],
                "agency_run_delivery_blocked",
                {"pipeline": record["pipeline"], "reason": blocker.code},
                run_id,
            )
        fail_idempotency(scope, idempotency_key, blocker.code)
        raise HTTPException(status_code=409, detail=_DELIVERY_BLOCK_DETAIL[blocker.code](latest))

    trust.record_policy_decision(
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        decision_id=f"policy-agency-resume-{run_id}-{idempotency_key}",
        subject_ref=run_id,
        action="agency.resume",
        target="delivery",
        policy_version="amc-trust/v1",
        policy_input={"run_id": run_id, "approval_id": latest["approval_id"] if latest else None},
        effect=PolicyEffect.ALLOW,
        required_authority_refs=("human-review",),
        evidence_refs=(latest["approval_id"],) if latest else (),
    )

    if not compare_and_set_run_status(run_id, "needs_approval", "delivering"):
        fail_idempotency(scope, idempotency_key, "resume_race_lost")
        current = get_run_record(run_id)
        if current and current["status"] == "completed":
            return {
                "run_id": run_id,
                "status": "completed",
                "delivery": (current["result"] or {}).get("agency", {}).get("delivery"),
            }
        raise HTTPException(status_code=409, detail="Run delivery is already being processed")

    emit_lifecycle_event(
        record["tenant_id"],
        record["project_id"],
        "agency_run_delivery_started",
        {"pipeline": record["pipeline"], "status": "delivering"},
        run_id,
    )
    _issue_dispatch_permit(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        phase="delivery",
        subject_hash=current_subject_hash,
        approval_refs=(latest["approval_id"],) if latest else (),
        authority_refs=("human-review",),
    )

    graph = build_agency_workflow()
    config = _run_config(run_id)
    run_model = AgentRun(
        id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        status=record["status"],
        created_at=datetime.fromisoformat(record["created_at"]),
        updated_at=datetime.fromisoformat(record["updated_at"]),
        metadata=record.get("metadata"),
    )
    started_at = datetime.now(timezone.utc)
    try:
        state = _run_and_record_events(graph, None, config, run_model)
    except Exception as exc:
        ended_at = datetime.now(timezone.utc)
        _record_execution_phase(
            run_id=run_id,
            tenant_id=record["tenant_id"],
            project_id=record["project_id"],
            operation_id=f"agency.resume:{run_id}",
            actor_role_id="delivery-orchestrator",
            args_payload={"run_id": run_id, "approval_id": latest["approval_id"] if latest else None},
            started_at=started_at,
            ended_at=ended_at,
            returned_state="FAILED",
            result_ref=None,
        )
        _record_failure(
            run_id=run_id,
            tenant_id=record["tenant_id"],
            project_id=record["project_id"],
            operation_id=f"agency.resume:{run_id}",
            args_payload={"run_id": run_id, "approval_id": latest["approval_id"] if latest else None},
            error_class=type(exc).__name__,
        )
        trust.open_recovery_case(
            tenant_id=record["tenant_id"],
            project_id=record["project_id"],
            operation_id=f"agency.resume:{run_id}",
            reason="EXECUTION_WITHOUT_OBSERVATION",
            execution_ref=run_id,
            idempotency_key=idempotency_key,
            evidence_refs=(type(exc).__name__,),
        )
        update_run_status(run_id, "failed", {"error": type(exc).__name__})
        record_event(run_id, record["tenant_id"], record["project_id"], "delivery", "node_error", safe_payload={"error_class": type(exc).__name__})
        emit_lifecycle_event(
            record["tenant_id"],
            record["project_id"],
            "agency_run_failed",
            {"pipeline": record["pipeline"], "phase": "delivery", "error_class": type(exc).__name__},
            run_id,
        )
        fail_idempotency(scope, idempotency_key, type(exc).__name__)
        trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=run_id, status=IdempotencyStatus.FAILED)
        raise HTTPException(status_code=500, detail="Delivery failed") from exc

    ended_at = datetime.now(timezone.utc)
    _record_execution_phase(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        operation_id=f"agency.resume:{run_id}",
        actor_role_id="delivery-orchestrator",
        args_payload={"run_id": run_id, "approval_id": latest["approval_id"] if latest else None},
        started_at=started_at,
        ended_at=ended_at,
        returned_state="COMPLETED",
        result_ref=run_id,
    )
    agency_data = _agency_payload(state)
    completed = update_run_status(run_id, "completed", {"agency": agency_data})
    _record_observation_phase(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        operation_id=f"agency.resume:{run_id}",
        expected_postcondition={"status": "completed", "delivery": True},
        observed_postcondition={"status": completed["status"], "delivery": bool(agency_data.get("delivery"))},
        evidence_refs=(latest["approval_id"],) if latest else (),
    )
    emit_lifecycle_event(
        record["tenant_id"],
        record["project_id"],
        "agency_run_completed",
        {"pipeline": record["pipeline"], "status": "completed"},
        run_id,
    )
    discharge_run_obligations(run_id=run_id, artifact_branch=f"art-protected-{run_id}")
    outbox_message = trust.enqueue_outbox(
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        message_id=f"outbox-delivery-{run_id}",
        topic="agency.delivery.completed",
        payload={
            "run_id": run_id,
            "approval_id": latest["approval_id"] if latest else None,
            "delivery": agency_data.get("delivery"),
            "status": "completed",
        },
        payload_ref=run_id,
        idempotency_key=idempotency_key,
    )
    trust.claim_outbox(message_id=outbox_message.message_id, worker_id="agency.resume")
    trust.mark_outbox_delivered(message_id=outbox_message.message_id)
    response = {"run_id": run_id, "status": "completed", "delivery": agency_data.get("delivery")}
    response["project_id"] = record["project_id"]
    if not complete_idempotency(scope, idempotency_key, response):
        raise HTTPException(status_code=500, detail="Failed to finalize idempotency record")
    _record_completion(
        run_id=run_id,
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        terminal_candidate="COMPLETE",
        proof_coverage=1.0,
        confidence=0.96,
        criteria=[
            CompletionCriterionResult(criterion_ref="execution", status=CriterionStatus.SATISFIED),
            CompletionCriterionResult(criterion_ref="observation", status=CriterionStatus.SATISFIED),
            CompletionCriterionResult(criterion_ref="approval", status=CriterionStatus.SATISFIED),
        ],
    )
    trust.complete_idempotency(idempotency_key=idempotency_key, result_ref=run_id)
    response["proof"] = get_run_proof_bundle(run_id)
    return response
