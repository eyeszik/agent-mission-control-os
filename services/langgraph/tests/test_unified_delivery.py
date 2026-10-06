"""Unified delivery: contract critic, pinned workflows and the release handshake.

Covers the v5 patch's required behaviour and mutants U12–U20 that do not
depend on the (absent) v4 MethodRouter, plus the release-readiness bar:
legacy paused runs replay, off mode is unchanged, shadow changes no release
path, enforce blocks the negative cases, the candidate is sealed before
approval, the approved subject is exactly the candidate, the receipt matches
the release, and ProjectOS stays the only invalidator.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.langgraph.agency.delivery import blast_radius as blast_radius_module
from services.langgraph.agency.delivery import crg as crg_module
from services.langgraph.agency.delivery.contract import (
    ContractValidationError,
    DeliveryContract,
    contract_hash,
    validate_contract_for_execution,
)
from services.langgraph.agency.delivery.critic import evaluate_contract, normalize_phrase_text
from services.langgraph.agency.delivery.crg import PIPELINE_INVARIANT, CRGInconsistency, build_crg
from services.langgraph.agency.delivery.release import (
    ArtifactRef,
    ReleaseFacts,
    ReleaseReceiptMismatch,
    ReleaseWitness,
    ReleaseReceipt,
    approval_subject_hash,
    build_candidate_manifest,
    build_release_receipt,
    candidate_manifest_hash,
    evaluate_release_predicate,
    safe_attributes,
)
from services.langgraph.agency.delivery.workflow import (
    CONTRACT_WORKFLOW,
    LEGACY_WORKFLOW,
    WorkflowPinError,
    assert_pin_current,
    graph_fingerprint,
    pin_for_new_run,
    pinned_workflow,
    topology,
)
from services.langgraph.app.main import app
from services.langgraph.graph.agency.llm import GenerationOutcome
from services.langgraph.persistence import agency_kernel
from services.langgraph.persistence.approvals import create_approval_request, get_approval, get_approvals_for_run
from services.langgraph.persistence.events import list_events_for_run
from services.langgraph.persistence.idempotency import reserve_idempotency
from services.langgraph.persistence.runs import create_run_record, get_run_record, update_run_status

client = TestClient(app)
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def provider_success(monkeypatch):
    def fake_generate(prompt: str, fallback: dict, **kwargs):
        now = datetime.now(timezone.utc).isoformat()
        return GenerationOutcome(
            data=fallback,
            mode="PROVIDER_SUCCESS",
            provider="test-provider",
            model="test-model",
            schema_version=kwargs.get("schema_version", "test-v1"),
            prompt_version="test-v1",
            prompt_hash="test-hash",
            attempts=1,
            started_at=now,
            completed_at=now,
            fallback_used=False,
            error_class=None,
        )

    monkeypatch.setattr("services.langgraph.graph.agency.nodes.generate_structured", fake_generate)


def _contract(*requirements: dict) -> dict:
    return {"contract_id": f"c-{uuid4().hex[:8]}", "title": "Launch", "requirements": list(requirements)}


ABSENT_PHRASE = {"requirement_id": "no-guarantees", "kind": "PHRASE_FORBIDDEN", "phrases": ["guaranteed returns"]}
HUMAN = {"requirement_id": "legal-review", "kind": "HUMAN_REVIEW", "description": "Legal signs off"}
# The brand name is always in the generated package, so forbidding it fails.
PRESENT_PHRASE = {"requirement_id": "no-brand", "kind": "PHRASE_FORBIDDEN", "phrases": ["Northwind"]}


def _create(contract: dict | None = None, project: str | None = None):
    body = {
        "project_id": project or f"proj-ud-{uuid4().hex[:10]}",
        "brief": {"brand_name": "Northwind", "target_audience": "Urban professionals"},
    }
    if contract is not None:
        body["delivery_contract"] = contract
    return client.post("/agency/runs", json=body, headers={"Idempotency-Key": str(uuid4())})


def _approve(approval_id: str):
    response = client.post(
        f"/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    return response


def _resume(run_id: str):
    return client.post(f"/agency/runs/{run_id}/resume", headers={"Idempotency-Key": str(uuid4())})


def _gate_events(run_id: str) -> list[dict]:
    return [
        e["safe_payload"]["release_gate"]
        for e in list_events_for_run(run_id)
        if e.get("node_id") == "release_gate"
    ]


# ---------------------------------------------------------------------------
# §2 workflow version pinning
# ---------------------------------------------------------------------------

def test_v2_topology_inserts_contract_check_before_hitl_and_keeps_static_interrupt():
    legacy, v2 = topology(LEGACY_WORKFLOW), topology(CONTRACT_WORKFLOW)
    assert legacy["node_ids"][-2:] == ["hitl_gate", "delivery"]
    assert v2["node_ids"].index("contract_check") == v2["node_ids"].index("hitl_gate") - 1
    assert legacy["interrupt_points"] == v2["interrupt_points"] == ["delivery"]
    assert graph_fingerprint(LEGACY_WORKFLOW) != graph_fingerprint(CONTRACT_WORKFLOW)
    assert graph_fingerprint(CONTRACT_WORKFLOW) == graph_fingerprint(CONTRACT_WORKFLOW)


def test_runs_without_a_pin_are_legacy_and_unknown_pins_are_refused():
    assert pinned_workflow({}).workflow_version == LEGACY_WORKFLOW
    assert pinned_workflow(None).contract_mode == "off"
    with pytest.raises(WorkflowPinError):
        pinned_workflow({"workflow": {"workflow_version": "agency/v9", "contract_mode": "off"}})
    pin = pin_for_new_run("enforce")
    assert (pin.workflow_version, pin.contract_mode) == (CONTRACT_WORKFLOW, "enforce")
    stale = pinned_workflow({"workflow": {**pin.as_metadata(), "graph_fingerprint": "0" * 64}})
    with pytest.raises(WorkflowPinError):
        assert_pin_current(stale)


# ---------------------------------------------------------------------------
# §8 critic semantics, §9 evidence freshness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "evasion",
    [
        "free money",
        "FREE MONEY",
        "free.money",
        "free-money",
        "free money",  # no-break space
        "free money",  # em space
        "ｆｒｅｅ ｍｏｎｅｙ",  # fullwidth, folded by NFKC
        "fr​ee money",  # zero-width space inside the word
        "Free—Money!",
    ],
)
def test_u18_forbidden_phrase_survives_punctuation_and_unicode_separators(evasion):
    contract = DeliveryContract.model_validate(
        _contract({"requirement_id": "p", "kind": "PHRASE_FORBIDDEN", "phrases": ["free money"]})
    )
    result = evaluate_contract(contract, f"Act now: {evasion} today", now=NOW)
    assert result.dod == "FAIL"
    assert result.results[0].matched_phrase_indexes == (0,)


def test_forbidden_phrase_uses_token_boundaries():
    contract = DeliveryContract.model_validate(
        _contract({"requirement_id": "p", "kind": "PHRASE_FORBIDDEN", "phrases": ["cure"]})
    )
    assert evaluate_contract(contract, "a secure, procured plan", now=NOW).dod == "PASS"
    assert normalize_phrase_text("A—B, C") == "a b c"


def _fact(**overrides) -> dict:
    fact = {
        "fact_id": "f1",
        "statement": "Ships in 2 days",
        "verification_ref": "ev-1",
        "evidence_hash": "h-1",
        "verified_at": "2026-10-01T00:00:00+00:00",
    }
    fact.update(overrides)
    return fact


def _fact_req(**overrides) -> dict:
    req = {"requirement_id": "ship", "kind": "FACT_PRESENT", "fact": _fact()}
    req.update(overrides)
    return req


def test_verbatim_fact_is_exact_and_case_sensitive():
    contract = DeliveryContract.model_validate(_contract(_fact_req()))
    resolve = {"ev-1": "h-1"}.get
    assert evaluate_contract(contract, "It  Ships in 2 days.", now=NOW, resolve_evidence=resolve).dod == "PASS"
    assert evaluate_contract(contract, "it ships in 2 days", now=NOW, resolve_evidence=resolve).dod == "FAIL"


def test_non_verbatim_fact_is_not_measured_unless_equivalence_is_declared():
    loose = DeliveryContract.model_validate(_contract(_fact_req(must_appear_verbatim=False)))
    result = evaluate_contract(loose, "ships in 2 days", now=NOW, resolve_evidence={"ev-1": "h-1"}.get)
    assert result.results[0].reason == "EQUIVALENCE_UNSUPPORTED"
    assert result.dod == "ESCALATE"
    declared = DeliveryContract.model_validate(
        _contract(_fact_req(must_appear_verbatim=False, equivalence="normalized_text"))
    )
    assert evaluate_contract(declared, "SHIPS—in 2 days", now=NOW, resolve_evidence={"ev-1": "h-1"}.get).dod == "PASS"


@pytest.mark.parametrize(
    ("fact_overrides", "resolver", "reason"),
    [
        ({"valid_until": "2026-10-02T00:00:00+00:00"}, {"ev-1": "h-1"}.get, "STALE_EVIDENCE:expired"),
        ({}, {"ev-1": "h-2"}.get, "STALE_EVIDENCE:source_changed"),
        ({}, {}.get, "STALE_EVIDENCE:unresolvable"),
        ({"verified_at": "2026-11-01T00:00:00+00:00"}, {"ev-1": "h-1"}.get, "STALE_EVIDENCE:not_yet_verified"),
    ],
)
def test_u15_stale_evidence_behind_a_blocking_fact_escalates(fact_overrides, resolver, reason):
    contract = DeliveryContract.model_validate(_contract(_fact_req(fact=_fact(**fact_overrides))))
    # Even though the text contains the fact, stale evidence never passes.
    result = evaluate_contract(contract, "Ships in 2 days", now=NOW, resolve_evidence=resolver)
    assert result.results[0].verdict == "NOT_MEASURED"
    assert result.results[0].reason == reason
    assert result.dod == "ESCALATE"


def test_human_review_is_never_passed_by_the_critic_and_non_blocking_failures_are_advisory():
    contract = DeliveryContract.model_validate(
        _contract(HUMAN, {**PRESENT_PHRASE, "blocking": False})
    )
    result = evaluate_contract(contract, "Northwind launch", now=NOW)
    assert [r.verdict for r in result.results] == ["NOT_MEASURED", "FAIL"]
    assert result.dod == "NEEDS_HUMAN"


def test_pattern_requirements_are_rejected_without_a_pinned_linear_time_engine():
    contract = DeliveryContract.model_validate(
        _contract({"requirement_id": "re", "kind": "PATTERN", "pattern": "(a+)+$"})
    )
    with pytest.raises(ContractValidationError) as exc:
        validate_contract_for_execution(contract)
    assert exc.value.code == "REJECTED_PATTERN_ENGINE_UNAVAILABLE"


def test_contract_schema_rejects_malformed_requirements_and_hash_is_order_sensitive_only_where_it_matters():
    with pytest.raises(ValidationError):
        DeliveryContract.model_validate(_contract({"requirement_id": "x", "kind": "FACT_PRESENT"}))
    with pytest.raises(ValidationError):
        DeliveryContract.model_validate(_contract(HUMAN, HUMAN))
    with pytest.raises(ValidationError):
        DeliveryContract.model_validate(_contract(_fact_req(fact=_fact(verified_at="2026-10-01T00:00:00"))))
    with pytest.raises(ValidationError):
        DeliveryContract.model_validate(_contract({**ABSENT_PHRASE, "phrases": ["x"] * 201}))
    with pytest.raises(ValidationError):
        DeliveryContract.model_validate(_contract({**ABSENT_PHRASE, "phrases": ["x" * 301]}))
    a = DeliveryContract.model_validate({**_contract(HUMAN), "contract_id": "same"})
    b = DeliveryContract.model_validate({"requirements": [HUMAN], "title": "Launch", "contract_id": "same"})
    assert contract_hash(a) == contract_hash(b)


# ---------------------------------------------------------------------------
# §3/§4 release handshake (pure)
# ---------------------------------------------------------------------------

def _refs(*pairs) -> list[ArtifactRef]:
    return [ArtifactRef(artifact_id=a, version_ref=f"{a}:v{v}", content_hash=f"h-{a}-{v}") for a, v in pairs]


def _candidate(refs=None, result="r1", deps="d1"):
    return build_candidate_manifest(
        run_id="run-1",
        project_id="proj-1",
        contract_hash="c1",
        artifact_refs=refs if refs is not None else _refs(("b", 1), ("a", 2)),
        contract_result_refs=[result],
        dependency_snapshot_hash=deps,
    )


def test_u12_candidate_manifest_cannot_carry_an_approval_decision_or_release_fields():
    manifest = _candidate().model_dump(mode="json")
    for smuggled in ("approval_decision", "approval_status", "human_override", "released_at", "release_receipt", "method_plan_hash"):
        with pytest.raises(ValidationError):
            type(_candidate()).model_validate({**manifest, smuggled: "x"})


def test_candidate_hash_is_canonical_and_subject_binds_exactly_candidate_contract_and_policy():
    first = _candidate(_refs(("b", 1), ("a", 2)))
    second = _candidate(_refs(("a", 2), ("b", 1)))
    assert candidate_manifest_hash(first) == candidate_manifest_hash(second)
    subject = approval_subject_hash(
        candidate_manifest_hash=candidate_manifest_hash(first), contract_hash="c1", policy_version="amc-release/v1"
    )
    assert subject != approval_subject_hash(
        candidate_manifest_hash=candidate_manifest_hash(first), contract_hash="c2", policy_version="amc-release/v1"
    )
    assert set(inspect.signature(approval_subject_hash).parameters) == {
        "candidate_manifest_hash", "contract_hash", "policy_version"
    }


def _facts(**overrides) -> ReleaseFacts:
    sealed = _candidate()
    subject = approval_subject_hash(
        candidate_manifest_hash=candidate_manifest_hash(sealed), contract_hash="c1", policy_version=sealed.policy_version
    )
    values = dict(
        n2_failure_codes=(),
        contract_dod="PASS",
        contract_result_hash="r1",
        approval={"approval_id": "ap-1", "status": "resolved", "decision": "approve", "subject_hash": subject},
        expected_approval_subject_hash=subject,
        sealed_candidate=sealed,
        current_artifact_refs=sealed.artifact_refs,
        current_dependency_snapshot_hash="d1",
        compile_blocked=False,
    )
    values.update(overrides)
    return ReleaseFacts(**values)


def _codes(facts: ReleaseFacts) -> list[str]:
    return [b.code for b in evaluate_release_predicate(facts)]


def test_release_predicate_permits_only_when_every_conjunct_holds():
    assert _codes(_facts()) == []
    assert _codes(_facts(contract_dod="NEEDS_HUMAN")) == []
    assert _codes(_facts(n2_failure_codes=("degraded_release_block",))) == ["N2:degraded_release_block"]
    assert _codes(_facts(contract_dod="FAIL")) == ["CONTRACT_FAILED"]
    assert _codes(_facts(contract_dod="ESCALATE")) == ["CONTRACT_ESCALATED"]
    assert _codes(_facts(contract_dod=None, contract_result_hash=None)) == ["CONTRACT_NOT_EVALUATED"]
    assert _codes(_facts(contract_result_hash="r2")) == ["CONTRACT_RESULT_CHANGED"]
    assert _codes(_facts(approval=None)) == ["APPROVAL_MISSING"]
    stale = {"approval_id": "ap-1", "status": "stale", "subject_hash": _facts().expected_approval_subject_hash}
    assert _codes(_facts(approval=stale)) == ["APPROVAL_STALE"]
    rejected = {**_facts().approval, "decision": "reject"}
    assert _codes(_facts(approval=rejected)) == ["APPROVAL_NOT_APPROVED"]
    assert _codes(_facts(contract_dod="NEEDS_HUMAN", approval=rejected)) == ["CONTRACT_NEEDS_HUMAN", "APPROVAL_NOT_APPROVED"]
    assert _codes(_facts(expected_approval_subject_hash="other")) == ["APPROVAL_SUBJECT_MISMATCH"]
    assert _codes(_facts(current_artifact_refs=tuple(_refs(("a", 3), ("b", 1))))) == ["ARTIFACTS_CHANGED"]
    assert _codes(_facts(current_dependency_snapshot_hash="d2")) == ["DEPENDENCIES_CHANGED"]
    assert _codes(_facts(compile_blocked=True)) == ["COMPILE_BLOCKED"]


def test_u16_receipt_refuses_a_release_that_differs_from_the_candidate():
    sealed = _candidate()
    approval = {"approval_id": "ap-1", "subject_hash": "s", "authority_ref": "human-review"}
    with pytest.raises(ReleaseReceiptMismatch):
        build_release_receipt(
            candidate=sealed,
            approval=approval,
            released_artifact_refs=_refs(("a", 3), ("b", 1)),
            delivery_receipt_ref="outbox-1",
            released_at=NOW.isoformat(),
            execution_lineage_hash="l",
        )
    receipt = build_release_receipt(
        candidate=sealed,
        approval=approval,
        released_artifact_refs=reversed(sealed.artifact_refs),
        delivery_receipt_ref="outbox-1",
        released_at=NOW.isoformat(),
        execution_lineage_hash="l",
    )
    assert receipt.candidate_manifest_hash == candidate_manifest_hash(sealed)
    assert ReleaseWitness is ReleaseReceipt


def test_safe_telemetry_rejects_content_bearing_attributes():
    assert safe_attributes(run_id="r", critic_verdict="PASS", tokens=None) == {"run_id": "r", "critic_verdict": "PASS"}
    for unsafe in ("prompt", "contract_text", "matched_text", "email"):
        with pytest.raises(ValueError):
            safe_attributes(**{unsafe: "x"})


# ---------------------------------------------------------------------------
# §6 CRG and §7 blast radius are derived, never authorities (U17)
# ---------------------------------------------------------------------------

def test_crg_is_derived_and_flags_incomplete_and_inconsistent_inputs():
    contract = DeliveryContract.model_validate(_contract(ABSENT_PHRASE, HUMAN))
    result = evaluate_contract(contract, "launch copy", now=NOW)
    candidate = build_candidate_manifest(
        run_id="run-1", project_id="p", contract_hash=contract_hash(contract),
        artifact_refs=_refs(("a", 1)), contract_result_refs=["r"], dependency_snapshot_hash="d",
    )
    work = [{"stage": "copywriting", "role_id": "copywriter", "justified_by": PIPELINE_INVARIANT}]
    graph = build_crg(contract=contract, result=result, candidate=candidate, work_order_refs=work, dependency_edges=[])
    assert graph["status"] == "COMPLETE" and graph["plan_hash"] is None
    assert graph == build_crg(contract=contract, result=result, candidate=candidate, work_order_refs=work, dependency_edges=[])

    empty = candidate.model_copy(update={"artifact_refs": ()})
    assert build_crg(contract=contract, result=result, candidate=empty, work_order_refs=work, dependency_edges=[])[
        "incomplete_requirements"
    ] == ["no-guarantees"]
    rogue = build_crg(
        contract=contract, result=result, candidate=candidate,
        work_order_refs=[*work, {"stage": "side_quest", "role_id": "x", "justified_by": None}], dependency_edges=[],
    )
    assert rogue["status"] == "PLAN_INCOMPLETE" and rogue["rejected_work_orders"][0]["stage"] == "side_quest"
    with pytest.raises(CRGInconsistency):
        build_crg(
            contract=contract, result=result, candidate=candidate.model_copy(update={"contract_hash": "other"}),
            work_order_refs=work, dependency_edges=[],
        )


@pytest.mark.parametrize("module", [crg_module, blast_radius_module])
def test_u17_derived_projections_cannot_mutate_state(module):
    tree = ast.parse(Path(inspect.getsourcefile(module)).read_text())
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any("persistence" in name or "sqlite" in name or "psycopg" in name for name in imported), imported
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not names & {"transaction", "execute", "open"}


def test_blast_radius_certificate_records_the_projectos_decision():
    tenant, project = "tenant-events-test", f"proj-br-{uuid4().hex[:8]}"
    engagement = f"eng-br-{uuid4().hex[:8]}"
    agency_kernel.create_engagement(engagement, tenant, project, "BR", "blast radius")
    common = dict(engagement_id=engagement, tenant_id=tenant, project_id=project)
    up = agency_kernel.create_artifact(f"art-up-{uuid4().hex[:6]}", artifact_type="brand_core", owner_department="brand", content_hash="h0", **common)
    down = agency_kernel.create_artifact(f"art-dn-{uuid4().hex[:6]}", artifact_type="positioning_statement", owner_department="strategy", content_hash="d0", **common)
    agency_kernel.add_artifact_dependency(down["artifact_id"], up["artifact_id"])
    run_id = f"run-{uuid4()}"
    create_run_record(run_id, tenant, project, "branding_marketing_agency", "needs_approval", {})
    approval = create_approval_request(run_id, tenant, project, "r", None, subject_ref=down["artifact_id"])

    revision = agency_kernel.record_artifact_revision(up["artifact_id"], content_hash="h1")
    cert = revision["certificate"]
    assert cert["before_hash"] == "h0" and cert["after_hash"] == "h1"
    assert cert["affected_nodes"] == [{"artifact_id": down["artifact_id"], "status": "invalidated"}]
    assert cert["preserved_nodes"] == []
    assert cert["reason_edges"][0]["depends_on_artifact_id"] == up["artifact_id"]
    assert len(cert["projectos_decision_refs"]) == 2
    # The certificate mirrors, it does not decide: ProjectOS already staled it.
    assert cert["staled_approval_ids"] == [approval["approval_id"]]
    assert get_approval(approval["approval_id"])["status"] == "stale"
    assert agency_kernel.get_artifact(down["artifact_id"])["status"] == "invalidated"


# ---------------------------------------------------------------------------
# §12 idempotency (U19) reuses the existing primitive
# ---------------------------------------------------------------------------

def test_u19_idempotency_key_reused_with_a_different_payload_conflicts():
    scope, key = f"scope-{uuid4()}", str(uuid4())
    assert reserve_idempotency(scope, key, "hash-a", 60)["state"] == "new"
    assert reserve_idempotency(scope, key, "hash-b", 60)["state"] == "conflict"


# ---------------------------------------------------------------------------
# API: off / shadow / enforce
# ---------------------------------------------------------------------------

def test_off_mode_is_the_legacy_route_and_rejects_contracts(monkeypatch):
    monkeypatch.delenv("AMC_CONTRACT_MODE", raising=False)
    assert _create(_contract(ABSENT_PHRASE)).status_code == 422
    body = _create().json()
    assert "workflow" not in body and "release_candidate" not in body
    record = get_run_record(body["run_id"])
    assert record["metadata"]["workflow"]["workflow_version"] == LEGACY_WORKFLOW
    assert get_approvals_for_run(body["run_id"])[0]["policy_version"] == "amc-approval/v1"


def test_enforce_requires_a_contract_and_rejects_unsupported_patterns(monkeypatch):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    assert _create().status_code == 422
    rejected = _create(_contract({"requirement_id": "re", "kind": "PATTERN", "pattern": "a+"}))
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "REJECTED_PATTERN_ENGINE_UNAVAILABLE"
    monkeypatch.setenv("AMC_CONTRACT_MODE", "sideways")
    assert _create(_contract(ABSENT_PHRASE)).status_code == 503


def test_enforce_seals_candidate_before_approval_and_receipt_matches_release(monkeypatch, provider_success):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    created = _create(_contract(ABSENT_PHRASE, HUMAN))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["workflow"]["workflow_version"] == CONTRACT_WORKFLOW
    assert body["contract_evaluation"]["dod"] == "NEEDS_HUMAN"
    sealed = body["release_candidate"]
    assert sealed["status"] == "SEALED"

    approval = get_approvals_for_run(body["run_id"])[0]
    assert approval["status"] == "pending"
    assert approval["subject_hash"] == sealed["approval_subject_hash"]
    assert approval["policy_version"] == "amc-release/v1"

    blocked = _resume(body["run_id"])
    assert blocked.status_code == 409 and "unresolved approval" in blocked.json()["detail"].lower()

    _approve(approval["approval_id"])
    resumed = _resume(body["run_id"])
    assert resumed.status_code == 200, resumed.text
    receipt = resumed.json()["release_receipt"]
    assert receipt["candidate_manifest_hash"] == sealed["candidate_manifest_hash"]
    assert receipt["approval_subject_hash"] == sealed["approval_subject_hash"]
    assert receipt["released_artifact_refs"] == sealed["manifest"]["artifact_refs"]
    assert receipt["delivery_receipt_ref"] == f"outbox-delivery-{body['run_id']}"
    # The pre-approval resume was stopped by the N2 guard before the gate ran.
    assert [e["authority_result"] for e in _gate_events(body["run_id"])] == ["PERMITTED", "RELEASED"]

    view = client.get(f"/agency/runs/{body['run_id']}/contract").json()
    assert view["crg"]["status"] == "COMPLETE"
    assert view["release_receipt"]["release_receipt_hash"]
    contract_events = [e for e in list_events_for_run(body["run_id"]) if e.get("node_id") == "contract_check"]
    assert contract_events[0]["safe_payload"]["contract_check"]["critic_verdict"] == "NEEDS_HUMAN"


def test_enforce_contract_failure_blocks_delivery_even_when_approved(monkeypatch, provider_success):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    body = _create(_contract(PRESENT_PHRASE)).json()
    assert body["contract_evaluation"]["dod"] == "FAIL"
    _approve(get_approvals_for_run(body["run_id"])[0]["approval_id"])
    response = _resume(body["run_id"])
    assert response.status_code == 409
    assert "CONTRACT_FAILED" in response.json()["detail"]
    assert get_run_record(body["run_id"])["status"] == "needs_approval"


def test_enforce_unverifiable_fact_escalates_and_approval_cannot_override(monkeypatch, provider_success):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    fact = _fact_req(fact=_fact(statement="Northwind", verification_ref=f"missing-{uuid4()}"))
    body = _create(_contract(fact)).json()
    assert body["contract_evaluation"]["dod"] == "ESCALATE"
    _approve(get_approvals_for_run(body["run_id"])[0]["approval_id"])
    response = _resume(body["run_id"])
    assert response.status_code == 409 and "CONTRACT_ESCALATED" in response.json()["detail"]


def test_enforce_fact_backed_by_fresh_kernel_evidence_passes(monkeypatch, provider_success):
    from services.langgraph.persistence.delivery import evidence_record_hash

    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    project = f"proj-ud-{uuid4().hex[:10]}"
    engagement = f"eng-ev-{uuid4().hex[:8]}"
    agency_kernel.create_engagement(engagement, "tenant-events-test", project, "Evidence", "facts")
    evidence = agency_kernel.create_evidence(
        f"ev-{uuid4().hex[:8]}", engagement, "tenant-events-test", project, "source", "Brand is Northwind", "verified", 0.9,
    )
    fact = _fact_req(fact=_fact(statement="Northwind", verification_ref=evidence["evidence_id"], evidence_hash=evidence_record_hash(evidence)))
    body = _create(_contract(fact), project=project).json()
    assert body["contract_evaluation"]["dod"] == "PASS"
    _approve(get_approvals_for_run(body["run_id"])[0]["approval_id"])
    assert _resume(body["run_id"]).status_code == 200


def test_contract_pass_cannot_bypass_the_degraded_release_block(monkeypatch):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    body = _create(_contract(ABSENT_PHRASE)).json()
    assert body["degraded"] is True and body["contract_evaluation"]["dod"] == "PASS"
    _approve(get_approvals_for_run(body["run_id"])[0]["approval_id"])
    response = _resume(body["run_id"])
    assert response.status_code == 409
    assert "degraded provider output" in response.json()["detail"]


def test_shadow_records_a_verdict_without_changing_the_release_path(monkeypatch, provider_success):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "shadow")
    body = _create(_contract(PRESENT_PHRASE)).json()
    assert body["workflow"]["contract_mode"] == "shadow"
    assert body["contract_evaluation"]["dod"] == "FAIL"
    approval = get_approvals_for_run(body["run_id"])[0]
    # Shadow keeps the legacy approval subject.
    assert approval["policy_version"] == "amc-approval/v1"
    assert approval["subject_hash"] != body["release_candidate"]["approval_subject_hash"]
    _approve(approval["approval_id"])
    resumed = _resume(body["run_id"])
    assert resumed.status_code == 200
    assert resumed.json()["release_receipt"] is None
    verdicts = _gate_events(body["run_id"])
    assert verdicts[0]["authority_result"] == "SHADOW_VERDICT"
    assert verdicts[0]["block_codes"] == ["CONTRACT_FAILED"]


def test_u13_resume_uses_the_pinned_workflow_not_the_current_mode(monkeypatch, provider_success):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "shadow")
    shadow_run = _create(_contract(ABSENT_PHRASE)).json()
    monkeypatch.setenv("AMC_CONTRACT_MODE", "off")
    view = client.get(f"/agency/runs/{shadow_run['run_id']}").json()
    assert view["workflow"]["workflow_version"] == CONTRACT_WORKFLOW
    assert view["pending_next_node"] == ["delivery"]
    _approve(get_approvals_for_run(shadow_run["run_id"])[0]["approval_id"])
    assert _resume(shadow_run["run_id"]).status_code == 200

    # Legacy paused run (created off) still resumes as legacy under enforce.
    legacy_run = _create().json()
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    _approve(get_approvals_for_run(legacy_run["run_id"])[0]["approval_id"])
    resumed = _resume(legacy_run["run_id"])
    assert resumed.status_code == 200 and "release_receipt" not in resumed.json()


def test_pre_pinning_run_without_metadata_resumes_as_legacy(monkeypatch, provider_success):
    body = _create().json()
    record = get_run_record(body["run_id"])
    metadata = {k: v for k, v in (record["metadata"] or {}).items() if k != "workflow"}
    from services.langgraph.persistence.database import json_param, table, transaction

    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('runs')} SET metadata = ? WHERE run_id = ?", (json_param(metadata), body["run_id"]))
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    _approve(get_approvals_for_run(body["run_id"])[0]["approval_id"])
    assert _resume(body["run_id"]).status_code == 200


def test_changed_topology_refuses_to_resume_a_pinned_run(monkeypatch, provider_success):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    body = _create(_contract(ABSENT_PHRASE)).json()
    _approve(get_approvals_for_run(body["run_id"])[0]["approval_id"])
    monkeypatch.setattr("services.langgraph.agency.delivery.workflow.graph_fingerprint", lambda version: "changed")
    response = _resume(body["run_id"])
    assert response.status_code == 409 and "topology" in response.json()["detail"]


def test_candidate_drift_after_approval_stales_it(monkeypatch, provider_success):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    body = _create(_contract(ABSENT_PHRASE)).json()
    approval_id = get_approvals_for_run(body["run_id"])[0]["approval_id"]
    _approve(approval_id)
    key = body["artifact_bindings"][0]["artifact_key"]
    rebind = client.post(
        f"/agency/runs/{body['run_id']}/artifacts/rebind",
        json={"artifact_key": key, "revision_note": "tighten headline"},
    )
    assert rebind.status_code == 200
    response = _resume(body["run_id"])
    assert response.status_code == 409
    assert "stale" in response.json()["detail"].lower() or "ARTIFACTS_CHANGED" in response.json()["detail"]
    assert get_approval(approval_id)["status"] == "stale"


def test_u20_method_plan_only_change_keeps_the_approval_valid(monkeypatch, provider_success):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    body = _create(_contract(ABSENT_PHRASE)).json()
    _approve(get_approvals_for_run(body["run_id"])[0]["approval_id"])
    record = get_run_record(body["run_id"])
    agency = dict(record["result"]["agency"])
    agency["method_plan"] = {"plan_hash": "replanned", "nodes": ["research", "draft"]}
    update_run_status(body["run_id"], "needs_approval", {"agency": agency})
    assert _resume(body["run_id"]).status_code == 200


def test_u16_release_that_differs_from_the_candidate_is_blocked(monkeypatch, provider_success):
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    body = _create(_contract(ABSENT_PHRASE)).json()
    _approve(get_approvals_for_run(body["run_id"])[0]["approval_id"])
    monkeypatch.setattr("services.langgraph.api.routes.agency._agency_subject_hash", lambda agency: "tampered")
    response = _resume(body["run_id"])
    assert response.status_code == 409
    assert "differ from the approved candidate" in response.json()["detail"]
    assert get_run_record(body["run_id"])["status"] == "failed"


def test_contract_mode_is_validated_by_production_config(monkeypatch):
    from services.langgraph.app.config import production_config_errors

    monkeypatch.setenv("AMC_ENV", "production")
    monkeypatch.setenv("AMC_CONTRACT_MODE", "maybe")
    assert "AMC_CONTRACT_MODE must be off, shadow or enforce" in production_config_errors()
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    assert "AMC_CONTRACT_MODE must be off, shadow or enforce" not in production_config_errors()
