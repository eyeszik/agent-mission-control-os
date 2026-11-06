"""Governed intake slice: intent -> project -> memory/context -> execution -> verification -> approval.

Scenario letters refer to the execution contract's critical scenarios. Every
"real" claim here runs the actual execution fabric, writes real Project OS
rows and storage objects, and re-reads them; nothing is mocked except where a
test says so.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from services.langgraph.agency.compiled.backchain import DeliverableSpec
from services.langgraph.agency.compiled.ontology import ARTIFACT_STAGE
from services.langgraph.agency.compiled.planner import CompiledAgencyRequest, compile_agency_plan
from services.langgraph.agency.execution_fabric.skills import FABRIC_SKILLS
from services.langgraph.agency.intake import (
    Deliverable,
    ExecutionMode,
    MissionNotReleasable,
    SideEffect,
    compile_context,
    compile_intent,
    release_gate,
    request_release_approval,
    resolve_project,
    run_mission,
    verify_artifact,
)
from services.langgraph.agency.intake.runner import BRAND_SUBJECT, mission_run_id
from services.langgraph.agency.intake.planning import PlanningInputs
from services.langgraph.agency.kernel.ontology import ArtifactType
from services.langgraph.agency.project_os.storage import LocalStorageAdapter
from services.langgraph.persistence.agency_kernel import get_artifact
from services.langgraph.persistence.approvals import get_approval, get_approvals_for_run
from services.langgraph.persistence.project_knowledge import write_memory
from services.langgraph.persistence.projects import (
    create_project_artifact,
    create_project_workspace,
    list_project_events,
    revise_project_artifact,
    transition_project,
)
from services.langgraph.security.auth import Principal

from services.langgraph.tests._project_os_support import as_user, client, headers

PALETTE = {"primary": "#5b1a22", "secondary": "#665d52", "surface": "#ece6da", "text": "#121212"}
UPSTREAM = ("brand_core", "brand_platform", "positioning_statement")
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def _tenant() -> str:
    return f"tenant-intake-{uuid4().hex[:8]}"


def _principal(tenant: str, *projects: str, user: str = "alice", role: str = "admin") -> Principal:
    return Principal(user_id=user, tenant_id=tenant, role=role, allowed_project_ids=frozenset(projects or ("*",)))


def _project(tenant: str, name: str, *, brand: str | None = None, upstream: bool = True, canon: bool = True,
             export_root=None) -> str:
    project_id = f"prj-{uuid4().hex[:12]}"
    create_project_workspace(tenant_id=tenant, project_id=project_id, actor="alice", display_name=name,
                             slug=f"{name.lower().replace(' ', '-')}-{project_id[-6:]}", brand_name=brand, export_root=export_root)
    adapter = LocalStorageAdapter(export_root)
    if upstream:
        for kind in UPSTREAM:
            create_project_artifact(tenant_id=tenant, project_id=project_id, actor="alice", artifact_key=kind,
                                    artifact_type=kind, adapter=adapter, content_text=f"approved {kind} for {name}")
    if canon:
        write_memory(tenant_id=tenant, actor="alice", scope="M1_BRAND_CANON", authority="BRAND_CANON",
                     subject_key=BRAND_SUBJECT, body={"brand_name": brand or name, "palette": PALETTE},
                     project_id=project_id, source_refs=("art:brand_core:v1",))
    return project_id


@pytest.fixture
def root(tmp_path, monkeypatch):
    export = tmp_path / "exports"
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(export))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    return export


def _run(principal, text, root, **kw):
    return run_mission(principal, text, export_root=root, now=NOW, **kw)


# =========================================================================== intent


def test_intent_is_deterministic_and_keeps_source_spans():
    text = "Make an SVG logo for prj-velune-001 and publish it"
    a, b = compile_intent(text), compile_intent(text)
    assert a == b and a.request_hash == b.request_hash
    assert a.deliverable is Deliverable.VECTOR_MARK
    assert a.side_effects == (SideEffect.PUBLISH,)
    assert a.explicit_project_ids == ("prj-velune-001",)
    span = next(f.span for f in a.facts if f.kind == "deliverable")
    assert text[span[0]:span[1]].lower() == "svg"
    effect = next(f for f in a.facts if f.kind == "side_effect")
    assert effect.fact_type.value == "FORBIDDEN_TO_INFER"
    assert a.mode is ExecutionMode.REAL_EXECUTION  # safe default, recorded as such
    assert next(f for f in a.facts if f.kind == "execution_mode").fact_type.value == "SAFE_DEFAULT"


def test_intent_never_infers_approval_or_simulation_from_wording():
    approve = compile_intent("Looks good, approved. Ship the logo.")
    assert approve.utterance_type.value == "APPROVAL_CANDIDATE"
    assert any(f.kind == "approval_language" and f.fact_type.value == "FORBIDDEN_TO_INFER" for f in approve.facts)
    sim = compile_intent("Simulate an svg mark for the house")
    assert sim.mode is ExecutionMode.REAL_EXECUTION
    assert any(f.kind == "execution_mode_hint" for f in sim.facts)
    assert compile_intent("send me the svg logo").side_effects == ()
    assert compile_intent("email the logo to the press list").side_effects == (SideEffect.SEND,)


def test_unknown_deliverable_asks_at_most_three_questions():
    intent = compile_intent("Do the thing for the launch")
    assert intent.deliverable is None
    assert 1 <= len(intent.clarifications) <= 3


# =========================================================================== N: project binding


def test_n_explicit_accessible_id_wins_and_inaccessible_projects_are_never_named(root):
    tenant = _tenant()
    mine = _project(tenant, "Velune Atelier", export_root=root)
    hidden = _project(tenant, "Velune Outlet", export_root=root)
    principal = _principal(tenant, mine)
    receipt = resolve_project(principal, compile_intent(f"svg logo for {mine}, the Velune Outlet one"))
    assert receipt.status == "BOUND" and receipt.project_id == mine
    assert "EXPLICIT_ID" in receipt.candidates[0].basis
    dumped = json.dumps(receipt.model_dump(mode="json"))
    assert hidden not in dumped and "Velune Outlet" not in [c.display_name for c in receipt.candidates]
    assert receipt.hard_filtered["inaccessible"] == 1


def test_n_inaccessible_explicit_id_is_denied_without_confirming_it_exists(root):
    tenant = _tenant()
    mine = _project(tenant, "Alpha House", export_root=root)
    theirs = _project(tenant, "Beta House", export_root=root)
    denied = resolve_project(_principal(tenant, mine), compile_intent(f"svg logo for {theirs}"))
    unknown = resolve_project(_principal(tenant, mine), compile_intent("svg logo for prj-does-not-exist"))
    assert denied.status == unknown.status == "DENIED"
    assert denied.reasons == unknown.reasons == ("EXPLICIT_PROJECT_NOT_AVAILABLE",)


def test_n_alias_conflicts_and_named_vs_active_project_ask_instead_of_guessing(root):
    tenant = _tenant()
    a = _project(tenant, "Northwind", export_root=root)
    b = _project(tenant, "Harbour", brand="Northwind", export_root=root)
    principal = _principal(tenant)
    tie = resolve_project(principal, compile_intent("svg logo for Northwind"))
    assert tie.status == "AMBIGUOUS" and tie.needs_confirmation and tie.project_id is None
    assert {c.project_id for c in tie.candidates} == {a, b}
    other = _project(tenant, "Lantern", export_root=root)
    differs = resolve_project(principal, compile_intent("svg logo for Lantern"), active_project_id=a)
    assert differs.status == "AMBIGUOUS" and "NAMED_PROJECT_DIFFERS_FROM_ACTIVE_PROJECT" in differs.reasons
    active = resolve_project(principal, compile_intent("make the svg logo"), active_project_id=other)
    assert active.status == "BOUND" and active.project_id == other


def test_n_archived_projects_cannot_receive_new_work(root):
    tenant = _tenant()
    archived = _project(tenant, "Old Season", export_root=root)
    transition_project(archived, "ARCHIVED", "alice")
    receipt = resolve_project(_principal(tenant), compile_intent(f"svg logo for {archived}"))
    assert receipt.status == "DENIED" and receipt.hard_filtered["archived"] == 1


def test_ambiguous_project_pauses_before_any_write(root):
    tenant = _tenant()
    _project(tenant, "Twin", export_root=root)
    _project(tenant, "Twin", export_root=root)
    outcome = _run(_principal(tenant), "svg logo for Twin", root)
    assert outcome.status == "NEEDS_CLARIFICATION" and outcome.mission is None and outcome.execution is None


# =========================================================================== L, M, K, P: memory and context


def test_l_conversation_cannot_mint_brand_canon_and_lower_authority_is_quarantined(root):
    tenant = _tenant()
    project = _project(tenant, "Canon House", export_root=root)
    from services.langgraph.agency.project_os.memory import MemoryPolicyError

    with pytest.raises(MemoryPolicyError):
        write_memory(tenant_id=tenant, actor="chat", scope="M3_CONVERSATION", authority="BRAND_CANON",
                     subject_key=BRAND_SUBJECT, body={"brand_name": "X", "palette": PALETTE}, project_id=project, thread_id="t1")
    lower = write_memory(tenant_id=tenant, actor="chat", scope="M2_PROJECT", authority="WORKING_CONTEXT",
                         subject_key=BRAND_SUBJECT, body={"brand_name": "Override", "palette": PALETTE}, project_id=project)
    assert lower["status"] == "QUARANTINED"
    capsule, receipt = compile_context(tenant_id=tenant, project_id=project, subjects={BRAND_SUBJECT: "APPROVED_PROJECT_DECISION"})
    assert capsule.memory[BRAND_SUBJECT]["body"]["brand_name"] == "Canon House"
    assert receipt.choices[0].authority == "BRAND_CANON"


def test_l_working_context_alone_is_below_the_brand_authority_floor_and_blocks(root):
    tenant = _tenant()
    project = _project(tenant, "Floor House", canon=False, export_root=root)
    write_memory(tenant_id=tenant, actor="chat", scope="M2_PROJECT", authority="WORKING_CONTEXT",
                 subject_key=BRAND_SUBJECT, body={"brand_name": "Floor House", "palette": PALETTE}, project_id=project)
    outcome = _run(_principal(tenant), f"svg logo for {project}", root)
    assert outcome.status == "BLOCKED" and outcome.execution is None
    p2 = next(p for p in outcome.mission.acceptance_predicates if p.predicate_id == "P2_BRAND_CONTEXT")
    assert p2.state.value == "BLOCKED" and p2.reasons == ("BRAND_CONTEXT_BELOW_AUTHORITY_FLOOR",)


def test_m_all_stale_memory_is_unresolved_stale_not_invented(root):
    tenant = _tenant()
    project = _project(tenant, "Stale House", canon=False, export_root=root)
    write_memory(tenant_id=tenant, actor="alice", scope="M1_BRAND_CANON", authority="BRAND_CANON", subject_key=BRAND_SUBJECT,
                 body={"brand_name": "Stale House", "palette": PALETTE}, project_id=project, source_refs=("art:brand_core:v1",),
                 fresh_until=(NOW - timedelta(days=1)).isoformat())
    capsule, receipt = compile_context(tenant_id=tenant, project_id=project, subjects={BRAND_SUBJECT: "BRAND_CANON"}, now=NOW)
    assert receipt.choices[0].status == "UNRESOLVED_STALE" and BRAND_SUBJECT in capsule.unknowns
    assert BRAND_SUBJECT not in capsule.memory


def test_k_other_projects_private_memory_never_enters_the_capsule(root):
    tenant = _tenant()
    mine = _project(tenant, "Mine", canon=False, export_root=root)
    other = _project(tenant, "Other", export_root=root)  # has brand canon for the same subject key
    capsule, receipt = compile_context(tenant_id=tenant, project_id=mine, subjects={BRAND_SUBJECT: "APPROVED_PROJECT_DECISION"})
    assert BRAND_SUBJECT not in capsule.memory and receipt.choices[0].status == "UNRESOLVED"
    assert other not in json.dumps(capsule.model_dump(mode="json")) + json.dumps(receipt.model_dump(mode="json"))


def test_p_capsule_hash_is_deterministic_and_tracks_selected_memory_and_budget(root):
    tenant = _tenant()
    project = _project(tenant, "Hash House", export_root=root)
    args = dict(tenant_id=tenant, project_id=project, subjects={BRAND_SUBJECT: "APPROVED_PROJECT_DECISION"}, now=NOW)
    first, _ = compile_context(**args)
    second, _ = compile_context(**args)
    assert first.capsule_hash == second.capsule_hash
    write_memory(tenant_id=tenant, actor="alice", scope="M1_BRAND_CANON", authority="BRAND_CANON", subject_key=BRAND_SUBJECT,
                 body={"brand_name": "Hash House", "palette": {**PALETTE, "primary": "#121212"}}, project_id=project,
                 source_refs=("art:brand_core:v2",))
    changed, _ = compile_context(**args)
    assert changed.capsule_hash != first.capsule_hash
    tiny, receipt = compile_context(**args, byte_budget=10)
    assert receipt.choices[0].status == "EXCLUDED_BUDGET" and tiny.byte_size <= 10 and BRAND_SUBJECT not in tiny.memory


def test_conversation_memory_from_another_thread_is_excluded(root):
    tenant = _tenant()
    project = _project(tenant, "Thread House", canon=False, export_root=root)
    note = write_memory(tenant_id=tenant, actor="chat", scope="M3_CONVERSATION", authority="WORKING_CONTEXT",
                        subject_key="tone", body={"tone": "playful"}, project_id=project, thread_id="thread-a")
    _, receipt = compile_context(tenant_id=tenant, project_id=project, subjects={"tone": "WORKING_CONTEXT"}, thread_id="thread-b")
    assert receipt.choices[0].excluded_other_thread == (note["memory"].memory_id,)
    assert receipt.choices[0].status == "UNRESOLVED"


# =========================================================================== A, R, V: real vector path to approval


def test_a_real_local_vector_mission_reaches_human_approval_with_independent_verification(root):
    tenant = _tenant()
    project = _project(tenant, "Maison Velune", export_root=root)
    outcome = _run(_principal(tenant, project), f"Make the SVG brand mark for {project}", root)

    assert outcome.status == "AWAITING_APPROVAL", outcome.reasons
    assert not outcome.simulation and outcome.production_eligible and not outcome.release_eligible
    cell = outcome.execution["cells"]["cell:media_asset"]
    assert cell["state"] == "SUCCEEDED" and cell["skill_id"] == "brand_logo_svg"

    v = outcome.verification
    assert v.status == "PASSED" and v.basis == "DETERMINISTIC"
    assert {c["family"] for c in v.checks} == {"FILE_INTEGRITY", "SCHEMA", "SECURITY", "BRAND_CONSISTENCY"}
    # Independently re-read the stored bytes here as well.
    head = get_artifact(v.artifact_id)
    data = LocalStorageAdapter(root).get_bytes(head["content_location"])
    assert hashlib.sha256(data).hexdigest() == v.content_hash == head["content_hash"]
    assert data.lstrip().startswith(b"<svg") and b"viewBox" in data

    approval = outcome.approval
    assert approval["status"] == "pending" and approval["subject_hash"] == v.content_hash
    assert approval["subject_type"] == "MISSION_ARTIFACT" and approval["subject_version_ref"] == str(v.version)
    states = {p.predicate_id: p.state.value for p in outcome.mission.acceptance_predicates}
    assert states == {"P1_PROJECT_BOUND": "VERIFIED", "P2_BRAND_CONTEXT": "VERIFIED", "P3_ARTIFACT_PRODUCED": "VERIFIED",
                      "P4_ARTIFACT_VERIFIED": "VERIFIED", "P5_HUMAN_APPROVED": "NEEDS_HUMAN"}
    events = [e.event_type.value for e in list_project_events(project, limit=500)]
    assert {"WORK_STARTED", "VERIFIED", "APPROVAL_REQUIRED"} <= set(events)
    verdict = release_gate(outcome)
    assert not verdict.allowed and "APPROVAL_PENDING" in verdict.reasons and verdict.external_effects == "none"


def test_v_release_needs_a_different_human_through_the_existing_route_and_binds_the_exact_hash(root, monkeypatch):
    tenant = _tenant()
    project = _project(tenant, "Bound House", export_root=root)
    outcome = _run(_principal(tenant, project, user="alice"), f"svg logo for {project}", root)
    approval_id = outcome.approval["approval_id"]

    # The initiator cannot approve their own mission (separation of duties, existing route).
    as_user(monkeypatch, "alice", role="admin", tenant=tenant, projects=project)
    refused = client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=headers())
    assert refused.status_code == 403, refused.text

    as_user(monkeypatch, "bob", role="admin", tenant=tenant, projects=project)
    decided = client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=headers())
    assert decided.status_code == 200, decided.text
    verdict = release_gate(outcome)
    assert verdict.allowed, verdict.reasons
    assert verdict.artifact_hash == outcome.verification.content_hash and verdict.external_effects == "none"

    # Any later change to the artifact invalidates both the verification and the approval binding.
    revise_project_artifact(project_id=project, artifact_id=outcome.verification.artifact_id, actor="mallory",
                            expected_version=outcome.verification.version, adapter=LocalStorageAdapter(root),
                            content_text="<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'/>")
    after = release_gate(outcome)
    assert not after.allowed
    assert "SUBJECT_HASH_MISMATCH" in after.reasons
    assert any(r.startswith("VERIFICATION_STALE") for r in after.reasons)


def test_v_rejected_and_missing_approvals_never_release(root, monkeypatch):
    tenant = _tenant()
    project = _project(tenant, "Reject House", export_root=root)
    outcome = _run(_principal(tenant, project, user="alice"), f"svg logo for {project}", root)
    as_user(monkeypatch, "bob", role="admin", tenant=tenant, projects=project)
    client.post(f"/approvals/{outcome.approval['approval_id']}/decide", json={"decision": "reject"}, headers=headers())
    assert "APPROVAL_REJECTED" in release_gate(outcome).reasons
    without = outcome.model_copy(update={"approval": None})
    assert "NO_APPROVAL" in release_gate(without).reasons


def test_r_review_fails_on_tampered_bytes_and_missing_artifacts(root):
    tenant = _tenant()
    project = _project(tenant, "Tamper House", export_root=root)
    outcome = _run(_principal(tenant, project), f"svg logo for {project}", root)
    v = outcome.verification
    head = get_artifact(v.artifact_id)
    path = root / "projects"
    stored = next(p for p in path.rglob(head["content_hash"]) if p.is_file())
    stored.write_bytes(stored.read_bytes().replace(b"</svg>", b"<script>x()</script></svg>"))
    tampered = verify_artifact(v.artifact_id, expected_version=v.version, adapter=LocalStorageAdapter(root), palette=PALETTE)
    assert tampered.status == "FAILED" and any(f.startswith("READ_BACK_FAILED") for f in tampered.findings)
    missing = verify_artifact("art-nope", expected_version=1, adapter=LocalStorageAdapter(root), palette=PALETTE)
    assert missing.status == "FAILED" and missing.findings == ("ARTIFACT_MISSING",)


def test_r_off_palette_svg_fails_brand_consistency(root):
    tenant = _tenant()
    project = _project(tenant, "Palette House", export_root=root)
    outcome = _run(_principal(tenant, project), f"svg logo for {project}", root)
    other = {"primary": "#00ff00", "secondary": "#0000ff", "surface": "#ffffff", "text": "#000000"}
    v = verify_artifact(outcome.verification.artifact_id, expected_version=outcome.verification.version,
                        adapter=LocalStorageAdapter(root), palette=other)
    assert v.status == "FAILED" and "OFF_PALETTE" in v.findings


def test_replaying_the_same_mission_is_idempotent(root):
    from services.langgraph.agency.execution.canonical import canonical_hash

    tenant = _tenant()
    project = _project(tenant, "Replay House", export_root=root)
    principal = _principal(tenant, project)
    first = _run(principal, f"svg logo for {project}", root)
    second = _run(principal, f"svg logo for {project}", root)
    assert first.mission.mission_id == second.mission.mission_id
    legacy = first.mission.model_dump(mode="json")
    for key in ("created_at", "acceptance_predicates", "planning_inputs_hash", "planning_source_refs"):
        legacy.pop(key)
    assert first.mission.contract_hash == canonical_hash(legacy)
    assert first.verification.version == second.verification.version == 1
    assert first.approval["approval_id"] == second.approval["approval_id"]
    assert len(get_approvals_for_run(mission_run_id(first.mission.mission_id))) == 1


# =========================================================================== O: correction


def test_o_brand_correction_changes_context_supersedes_the_old_approval_and_keeps_audit(root):
    tenant = _tenant()
    project = _project(tenant, "Correct House", export_root=root)
    principal = _principal(tenant, project)
    first = _run(principal, f"svg logo for {project}", root)
    write_memory(tenant_id=tenant, actor="alice", scope="M1_BRAND_CANON", authority="BRAND_CANON", subject_key=BRAND_SUBJECT,
                 body={"brand_name": "Correct House", "palette": {**PALETTE, "primary": "#121212", "text": "#5b1a22"}},
                 project_id=project, source_refs=("art:brand_core:v2",))
    second = _run(principal, f"svg logo for {project}", root)
    assert second.context.capsule_hash != first.context.capsule_hash
    assert second.mission.mission_id != first.mission.mission_id
    assert second.verification.artifact_id == first.verification.artifact_id
    assert second.verification.version == first.verification.version + 1
    assert get_approval(first.approval["approval_id"])["status"] == "stale"
    assert "SUBJECT_HASH_MISMATCH" in release_gate(first).reasons
    verified = [e for e in list_project_events(project, limit=500) if e.event_type.value == "VERIFIED"]
    assert len(verified) == 2  # the first verification stays in the audit trail


# =========================================================================== B, C, G, I, S: blocked paths


def test_b_image_request_without_a_provider_is_blocked_with_no_placeholder(root):
    tenant = _tenant()
    project = _project(tenant, "Image House", export_root=root)
    outcome = _run(_principal(tenant, project), f"Create a campaign photo for {project}", root)
    assert outcome.status == "BLOCKED" and outcome.verification is None and outcome.approval is None
    cell = outcome.execution["cells"]["cell:media_asset"]
    assert cell["state"] == "PROVIDER_GAP" and cell["reasons"] == ["PROVIDER_GAP:t2i"]
    assert get_artifact(f"art-{project}-media_asset") is None  # nothing was substituted
    assert not outcome.production_eligible and not release_gate(outcome).allowed


def test_c_explicit_simulation_is_marked_persisted_and_never_eligible(root):
    tenant = _tenant()
    project = _project(tenant, "Sim House", export_root=root)
    outcome = _run(_principal(tenant, project), f"svg logo for {project}", root, requested_mode=ExecutionMode.SIMULATION)
    assert outcome.status == "SIMULATED" and outcome.simulation
    assert not outcome.production_eligible and not outcome.release_eligible and outcome.execution is None
    assert all(p.state.value == "NOT_EXECUTED" for p in outcome.mission.acceptance_predicates
               if p.predicate_id in {"P3_ARTIFACT_PRODUCED", "P4_ARTIFACT_VERIFIED", "P5_HUMAN_APPROVED"})
    started = next(e for e in list_project_events(project, limit=500) if e.event_type.value == "WORK_STARTED")
    assert started.payload["simulation"] is True and started.payload["mode"] == "SIMULATION"
    assert get_artifact(f"art-{project}-media_asset") is None


def test_g_simulated_missions_cannot_request_approval_or_release(root):
    tenant = _tenant()
    project = _project(tenant, "Contam House", export_root=root)
    principal = _principal(tenant, project)
    real = _run(principal, f"svg logo for {project}", root)
    sim = _run(principal, f"svg logo for {project}", root, requested_mode=ExecutionMode.SIMULATION)
    with pytest.raises(MissionNotReleasable):
        request_release_approval(principal, sim.mission, real.verification)
    # Grafting a real verification and approval onto a simulated outcome still cannot release.
    grafted = sim.model_copy(update={"verification": real.verification, "approval": real.approval})
    assert "SIMULATION_NOT_RELEASABLE" in release_gate(grafted).reasons


def test_i_s_publish_spend_and_send_are_never_dispatched_and_say_what_was_observed(root):
    tenant = _tenant()
    project = _project(tenant, "Effect House", export_root=root)
    outcome = _run(_principal(tenant, project), f"Make the svg logo for {project}, publish it, boost it and email the list", root)
    assert outcome.status == "AWAITING_APPROVAL"  # the safe local work still proceeds
    effects = {r.effect for r in outcome.non_actions}
    assert effects == {SideEffect.PUBLISH, SideEffect.SPEND, SideEffect.SEND}
    for receipt in outcome.non_actions:
        assert receipt.dispatched is False and receipt.policy_gate.startswith("TWO_KEY_EFFECT_REQUIRED")
        assert receipt.observed_counts_before == receipt.observed_counts_after
        assert "does not prove that no other system acted" in receipt.limits
    states = {p.predicate_id: p.state.value for p in outcome.mission.acceptance_predicates}
    assert states["P6_PUBLISH_AUTHORIZED"] == states["P6_SPEND_AUTHORIZED"] == states["P6_SEND_AUTHORIZED"] == "NEEDS_HUMAN"
    blocked = [e for e in list_project_events(project, limit=500) if e.event_type.value == "QA_BLOCKED"]
    assert blocked and blocked[-1].payload["dispatched"] is False


def test_missing_upstream_inputs_plan_as_blocked_work_not_fake_success(root):
    tenant = _tenant()
    project = _project(tenant, "Bare House", upstream=False, export_root=root)
    outcome = _run(_principal(tenant, project), f"svg logo for {project}", root)
    assert outcome.status == "BLOCKED" and outcome.verification is None
    cells = outcome.execution["cells"]
    # The fabric's own precedence: brand_core is held for a human, so the mark is NEEDS_HUMAN, not a fake success.
    assert cells["cell:media_asset"]["state"] == "NEEDS_HUMAN"
    assert "UPSTREAM_HELD:cell:brand_core" in cells["cell:media_asset"]["reasons"]
    assert cells["cell:research_brief"]["reasons"] == ["PROVIDER_GAP:llm_drafting"]
    assert get_artifact(f"art-{project}-media_asset") is None


# =========================================================================== T: planner regression


def test_t_every_n1_artifact_type_has_a_planner_stage():
    assert set(ArtifactType) <= set(ARTIFACT_STAGE), set(ArtifactType) - set(ARTIFACT_STAGE)


def test_t_media_asset_plans_to_the_creative_director_and_the_logo_skill_matches():
    existing = {k: "b" * 64 for k in UPSTREAM}
    spec = DeliverableSpec(id="mark", requested_outcome="mark", output_contract="media_asset",
                           acceptance_criteria=("svg",), domains=("BRAND",))
    from pathlib import Path

    from services.langgraph.agency.execution_fabric.schedule import from_compiled_agency_plan
    from services.langgraph.agency.role_os import RoleOSRegistry

    registry = RoleOSRegistry(Path(__file__).resolve().parents[3] / "runtime" / "role_os")
    schedule = from_compiled_agency_plan(compile_agency_plan(
        CompiledAgencyRequest(project_id="p", as_of="2026-10-09T00:00:00Z", deliverables=(spec,), existing_artifacts=existing),
        registry=registry))
    cell = schedule.cells["cell:media_asset"]
    assert cell.n3_role_id == "creative_director"
    assert FABRIC_SKILLS["brand_logo_svg"].produces.value == "media_asset"


def test_types_without_an_independent_verifier_are_inconclusive_never_passed(root):
    tenant = _tenant()
    project = _project(tenant, "Token House", export_root=root)
    # A real persisted non-SVG artifact: the verifier has no independent check for it, so it must not pass.
    meta = create_project_artifact(tenant_id=tenant, project_id=project, actor="alice", artifact_key="notes",
                                   artifact_type="research_brief", adapter=LocalStorageAdapter(root), content_text="plain notes",
                                   v2={"mime_type": "text/plain"})
    v = verify_artifact(meta.artifact_id, expected_version=1, adapter=LocalStorageAdapter(root), palette=PALETTE)
    assert v.status == "INCONCLUSIVE" and v.findings == ("NO_INDEPENDENT_VERIFIER_FOR:text/plain",)


def test_design_tokens_route_but_block_on_unmet_upstream_planning_gates(root):
    tenant = _tenant()
    project = _project(tenant, "Token Plan House", export_root=root)
    outcome = _run(_principal(tenant, project), f"compile the design tokens for {project}", root)
    assert outcome.intent.deliverable is Deliverable.DESIGN_TOKENS
    assert outcome.status == "BLOCKED" and outcome.verification is None and outcome.approval is None
    assert outcome.execution["cells"]["cell:design_token_set"]["state"] != "SUCCEEDED"
    assert not release_gate(outcome).allowed


def _planning_inputs(tenant, project, **changes):
    """Fictional server-verified records, not defaults for a real brand."""
    body = {
        "tenant_id": tenant, "project_id": project, "source_refs": ("fixture:sections-1-3",),
        "evidence": tuple({"ref": f"fixture:identity:{i}", "supports": ("identity_guidelines",), "verified": True}
                          for i in (1, 2)),
        "decisions": ({"id": "fixture:direction", "kind": "creative_direction", "question": "Which direction?",
                       "alternatives": ("direction-a", "direction-b"), "selected_option": "direction-a",
                       "owner": "creative-lead", "approved_by": "human-reviewer", "status": "ACCEPTED"},),
        "volatile_constraints": ({"key": "accessibility.standard", "source_ref": "https://www.w3.org/TR/WCAG22/",
                                  "retrieved_at": "2026-10-01T00:00:00Z", "value": "WCAG 2.2 AA",
                                  "verification_status": "VERIFIED", "expires_or_recheck_at": "2027-10-01T00:00:00Z"},),
    }
    return PlanningInputs.model_validate({**body, **changes})


def test_supplied_planning_evidence_unblocks_the_design_token_plan(root):
    from services.langgraph.agency.intake.runner import _existing_inputs, _plan

    tenant = _tenant()
    project = _project(tenant, "Ready Plan House", export_root=root)
    schedule = _plan(project, "design_token_set", "Compile design tokens", NOW, _existing_inputs(project),
                     planning_inputs=_planning_inputs(tenant, project))
    for kind in ("identity_guidelines", "creative_concept", "design_token_set"):
        cell = schedule.cells[f"cell:{kind}"]
        assert cell.execution_ready and not cell.blockers
        assert f"cell:{kind}" not in schedule.wave_plan.held


def test_ready_design_token_mission_verifies_real_bytes_and_waits_for_approval(root):
    tenant = _tenant()
    project = _project(tenant, "Ready Token House", export_root=root)
    for kind in ("identity_guidelines", "creative_concept"):
        create_project_artifact(tenant_id=tenant, project_id=project, actor="alice", artifact_key=kind,
                                artifact_type=kind, adapter=LocalStorageAdapter(root), content_text=f"approved {kind}")
    write_memory(tenant_id=tenant, actor="alice", scope="M1_BRAND_CANON", authority="BRAND_CANON",
                 subject_key=BRAND_SUBJECT, project_id=project,
                 body={"brand_name": "Ready Token House", "palette": PALETTE,
                       "heading_font": "Georgia", "body_font": "Atkinson Hyperlegible"},
                 source_refs=("fixture:ratified-brand-values",))
    outcome = _run(_principal(tenant, project), f"compile design tokens for {project}", root,
                   planning_inputs=_planning_inputs(tenant, project))
    assert outcome.status == "AWAITING_APPROVAL", outcome.reasons
    assert outcome.execution["cells"]["cell:design_token_set"]["state"] == "SUCCEEDED"
    assert outcome.verification.status == "PASSED" and outcome.approval is not None
    head = get_artifact(outcome.verification.artifact_id)
    body = json.loads(LocalStorageAdapter(root).get_bytes(head["content_location"]))
    assert body["document"]["primitive"]["font"]["heading"]["$value"][0] == "Georgia"
    assert body["document"]["primitive"]["font"]["body"]["$value"][0] == "Atkinson Hyperlegible"
    assert not release_gate(outcome).allowed


@pytest.mark.parametrize("missing", ("evidence", "decisions", "volatile_constraints", "unverified_evidence",
                                     "expired_wcag", "unverified_wcag", "proposed_direction",
                                     "expired_offset", "malformed_wcag", "future_wcag"))
def test_planning_inputs_preserve_each_unmet_design_gate(root, missing):
    from services.langgraph.agency.intake.runner import _existing_inputs, _plan

    tenant = _tenant()
    project = _project(tenant, "Incomplete Plan", export_root=root)
    body = _planning_inputs(tenant, project).model_dump(mode="json")
    if missing == "unverified_evidence":
        for evidence in body["evidence"]:
            evidence["verified"] = False
    elif missing == "expired_wcag":
        body["volatile_constraints"][0]["expires_or_recheck_at"] = "2026-10-08T00:00:00Z"
    elif missing == "unverified_wcag":
        body["volatile_constraints"][0]["verification_status"] = "UNVERIFIED"
    elif missing == "expired_offset":
        body["volatile_constraints"][0]["expires_or_recheck_at"] = "2026-10-09T13:00:00+02:00"
    elif missing == "malformed_wcag":
        body["volatile_constraints"][0]["expires_or_recheck_at"] = "tomorrow"
    elif missing == "future_wcag":
        body["volatile_constraints"][0]["retrieved_at"] = "2026-10-10T00:00:00Z"
    elif missing == "proposed_direction":
        body["decisions"][0]["status"] = "PROPOSED"
        body["decisions"][0]["approved_by"] = None
    else:
        body[missing] = []
    schedule = _plan(project, "design_token_set", "Compile design tokens", NOW, _existing_inputs(project),
                     planning_inputs=PlanningInputs.model_validate(body))
    cell = schedule.cells["cell:design_token_set"]
    assert not cell.execution_ready or cell.blockers or "cell:design_token_set" in schedule.wave_plan.held
    if missing in ("evidence", "unverified_evidence"):
        assert schedule.graph.nodes["evidence:identity_guidelines"].status.value == "BLOCKED"
    elif missing in ("decisions", "proposed_direction"):
        assert schedule.graph.nodes["decision:creative_direction"].status.value == "AWAITING_HUMAN"
    else:
        assert any("VOLATILE_" in blocker for blocker in cell.blockers)


def test_planning_inputs_cannot_supply_missing_brand_artifacts(root):
    tenant = _tenant()
    project = _project(tenant, "Missing Foundations", upstream=False, export_root=root)
    outcome = _run(_principal(tenant, project), f"compile design tokens for {project}", root,
                   planning_inputs=_planning_inputs(tenant, project))
    assert outcome.status == "BLOCKED" and outcome.verification is None
    assert outcome.execution["cells"]["cell:design_token_set"]["state"] != "SUCCEEDED"


@pytest.mark.parametrize("scope", ("tenant_id", "project_id"))
def test_planning_inputs_from_another_scope_block_before_writing(root, scope):
    tenant = _tenant()
    project = _project(tenant, "Scoped Plan", export_root=root)
    inputs = _planning_inputs(tenant, project, **{scope: "not-this-scope"})
    before = list_project_events(project, limit=500)
    outcome = _run(_principal(tenant, project), f"compile design tokens for {project}", root, planning_inputs=inputs)
    assert outcome.status == "BLOCKED" and outcome.reasons == ("PLANNING_INPUT_SCOPE_MISMATCH",)
    assert outcome.execution is None and list_project_events(project, limit=500) == before


def test_planning_evidence_changes_mission_identity_without_creating_authority(root):
    tenant = _tenant()
    project = _project(tenant, "Changed Planning Evidence", export_root=root)
    inputs = _planning_inputs(tenant, project)
    kw = {"requested_mode": ExecutionMode.SIMULATION}
    first = _run(_principal(tenant, project), f"compile design tokens for {project}", root, planning_inputs=inputs, **kw)
    repeat = _run(_principal(tenant, project), f"compile design tokens for {project}", root, planning_inputs=inputs, **kw)
    changed = _run(_principal(tenant, project), f"compile design tokens for {project}", root,
                   planning_inputs=_planning_inputs(tenant, project, source_refs=("fixture:sections-1-3:v2",)), **kw)
    assert first.mission.mission_id == repeat.mission.mission_id != changed.mission.mission_id
    assert first.mission.contract_hash != changed.mission.contract_hash
    assert first.mission.planning_inputs_hash == inputs.content_hash
    assert first.mission.planning_source_refs == inputs.source_refs
    started = next(e for e in list_project_events(project, limit=500)
                   if e.event_type.value == "WORK_STARTED" and e.payload["mission_id"] == first.mission.mission_id)
    assert started.payload["planning_inputs_hash"] == inputs.content_hash
    assert started.payload["planning_source_refs"] == list(inputs.source_refs)
    assert not release_gate(first).allowed and first.execution is None


def test_planning_input_claims_cannot_forge_accepted_decisions_or_duplicate_evidence():
    from pydantic import ValidationError

    body = _planning_inputs("tenant", "project").model_dump(mode="json")
    body["decisions"][0]["approved_by"] = body["decisions"][0]["owner"]
    with pytest.raises(ValidationError, match="independent approver"):
        PlanningInputs.model_validate(body)
    body = _planning_inputs("tenant", "project").model_dump(mode="json")
    body["evidence"] = [body["evidence"][0], body["evidence"][0]]
    with pytest.raises(ValidationError, match="unique"):
        PlanningInputs.model_validate(body)


@pytest.mark.parametrize("status", ("ACCEPTED", "PROPOSED", "REJECTED"))
@pytest.mark.parametrize("reverse", (False, True))
def test_planning_inputs_reject_conflicting_live_decisions_without_choosing_by_order(status, reverse):
    from pydantic import ValidationError

    body = _planning_inputs("tenant", "project").model_dump(mode="json")
    original = body["decisions"][0]
    other = {**original, "id": "fixture:conflicting-direction", "selected_option": "direction-b", "status": status}
    body["decisions"] = [other, original] if reverse else [original, other]
    with pytest.raises(ValidationError, match="conflicting live planning decisions: creative_direction"):
        PlanningInputs.model_validate(body)


def test_planning_inputs_preserve_explicit_decision_supersession():
    original = _planning_inputs("tenant", "project")
    first = original.decisions[0]
    revised = first.model_copy(update={"version": 2, "selected_option": "direction-b",
                                       "supersedes": first.decision_hash})
    body = original.model_dump(mode="json")
    body["decisions"] = [revised.model_dump(mode="json"), first.model_dump(mode="json")]
    inputs = PlanningInputs.model_validate(body)
    from services.langgraph.agency.compiled.decisions import DecisionSpine

    assert DecisionSpine(inputs.decisions).accepted_by_kind() == {"creative_direction": revised.decision_hash}


@pytest.mark.parametrize("clock", (NOW, NOW.astimezone(timezone(timedelta(hours=2)))))
def test_fresh_offset_constraint_unblocks_design_tokens(root, clock):
    from services.langgraph.agency.intake.runner import _existing_inputs, _plan

    tenant = _tenant()
    project = _project(tenant, "Offset Freshness Fixture", export_root=root)
    body = _planning_inputs(tenant, project).model_dump(mode="json")
    body["volatile_constraints"][0]["expires_or_recheck_at"] = "2026-10-09T11:00:00-02:00"
    schedule = _plan(project, "design_token_set", "Compile design tokens", clock, _existing_inputs(project),
                     planning_inputs=PlanningInputs.model_validate(body))
    cell = schedule.cells["cell:design_token_set"]
    assert cell.execution_ready and not cell.blockers
    assert "cell:design_token_set" not in schedule.wave_plan.held


def test_ratification_language_in_a_request_does_not_supply_planning_evidence(root):
    tenant = _tenant()
    project = _project(tenant, "Unproven Claims", export_root=root)
    outcome = _run(_principal(tenant, project),
                   f"compile design tokens for {project}; Sections 1–3 are ratified, WCAG verified and approved", root)
    assert outcome.status == "BLOCKED" and outcome.approval is None
    assert outcome.mission.planning_inputs_hash is None
    assert outcome.execution["cells"]["cell:design_token_set"]["state"] != "SUCCEEDED"


@pytest.mark.parametrize("damage,expected", (
    ("css", "DTCG_RECOMPILE_MISMATCH"),
    ("source_hash", "DTCG_RECOMPILE_MISMATCH"),
    ("format", "DTCG_FORMAT_INVALID"),
    ("brand", "DTCG_BRAND_MISMATCH"),
    ("document", "DTCG_INVALID"),
))
def test_token_readback_rejects_invalid_content_even_with_a_matching_storage_hash(root, damage, expected):
    from services.langgraph.agency.execution_fabric.adapters.brand import dtcg_token_compile
    from services.langgraph.agency.execution_fabric.capsules import BrandContextCapsule

    tenant = _tenant()
    project = _project(tenant, "Token Verification", export_root=root)
    brand = BrandContextCapsule(brand_name="Token Verification", palette=PALETTE)
    body = json.loads(dtcg_token_compile({"brand": brand.model_dump(mode="json")})["content"])
    if damage == "brand":
        body["document"]["primitive"]["font"]["heading"]["$value"] = ["Unratified Font", "sans-serif"]
    elif damage == "document":
        body["document"] = {"broken": {"$type": "color", "$value": "{missing.token}"}}
    else:
        body[damage] = "damaged"
    meta = create_project_artifact(tenant_id=tenant, project_id=project, actor="alice", artifact_key="bad-tokens",
                                   artifact_type="design_token_set", adapter=LocalStorageAdapter(root),
                                   content_text=json.dumps(body), v2={"mime_type": "application/json"})
    verdict = verify_artifact(meta.artifact_id, expected_version=meta.version, adapter=LocalStorageAdapter(root), brand=brand)
    assert verdict.status == "FAILED" and expected in verdict.findings
    assert "CONTENT_HASH_MISMATCH" not in verdict.findings  # format/content checks did the work
