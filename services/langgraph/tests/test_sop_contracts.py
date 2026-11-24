"""Ordered SOP contracts: registry structure, binding to live code, runtime guard, recovery paths."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.langgraph.agency.sop import (
    REGISTRY_FILE,
    SopContractViolation,
    SopRegistry,
    guard_stage,
    load_registry,
    structural_problems,
    verify_against_code,
)
from services.langgraph.app.main import app
from services.langgraph.graph.agency.llm import GenerationOutcome
from services.langgraph.graph.agency.nodes import AGENCY_PIPELINE_STAGES, copywriting_node
from services.langgraph.persistence.approvals import get_approvals_for_run, resolve_approval
from services.langgraph.persistence.runs import get_run_record, update_run_status

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages/shared/tests/fixtures/sop-registry.json"
client = TestClient(app)


def _raw() -> dict:
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def test_registry_loads_and_agrees_with_the_running_code():
    registry = load_registry()
    assert structural_problems(registry) == []
    assert verify_against_code(registry) == []


def test_every_live_stage_and_both_topologies_are_covered_in_order():
    registry = load_registry()
    legacy = [s.stage_name for s in registry.ordered("PIPELINE.agency/v1-legacy")]
    contract = [s.stage_name for s in registry.ordered("PIPELINE.agency/v2-contract")]
    assert legacy == AGENCY_PIPELINE_STAGES
    assert contract[:7] == legacy[:7] and contract[7] == "contract_check" and contract[8:] == legacy[7:]


def test_recovery_paths_are_declared_and_never_pass_silently():
    registry = load_registry()
    recovery = {p.procedure_id for p in registry.procedures if p.kind == "recovery"}
    assert recovery == {
        "RECOVERY.degraded_non_delivery",
        "RECOVERY.stale_edit_conflict",
        "RECOVERY.crash_reconciliation",
        "RECOVERY.approval_rejected",
    }
    assert {s.failure_disposition for s in registry.steps} <= {"FALLBACK_DEGRADED", "BLOCKED"}


def test_a_gap_in_sequence_index_is_rejected():
    raw = _raw()
    raw["procedures"][0]["steps"][3]["sequence_index"] = 7
    with pytest.raises(ValueError, match="contiguous"):
        SopRegistry.model_validate(raw)


def test_a_repeated_step_is_rejected_as_a_cycle():
    raw = _raw()
    steps = raw["procedures"][0]["steps"]
    steps.append({"sequence_index": len(steps) + 1, "sop_id": steps[0]["sop_id"]})
    with pytest.raises(ValueError, match="cyclic"):
        SopRegistry.model_validate(raw)


def test_a_step_that_reads_state_no_earlier_step_produces_is_rejected():
    raw = _raw()
    # Swap brand_strategy and copywriting: copywriting would read brand_strategy before it exists.
    steps = raw["procedures"][0]["steps"]
    steps[1]["sop_id"], steps[3]["sop_id"] = steps[3]["sop_id"], steps[1]["sop_id"]
    with pytest.raises(ValueError, match="requires brand_strategy before"):
        SopRegistry.model_validate(raw)


def test_an_unresolved_enforcer_is_reported():
    raw = _raw()
    raw["steps"][0]["enforced_by"] = ["services/langgraph/graph/agency/nodes.py::no_such_symbol"]
    problems = verify_against_code(SopRegistry.model_validate(raw))
    assert problems == ["SOP-AGY-01: unresolved reference services/langgraph/graph/agency/nodes.py::no_such_symbol"]


def test_guard_refuses_a_stage_invoked_out_of_order():
    guarded = guard_stage("copywriting", copywriting_node)
    state = {"extracted_data": {"agency": {"brief": {"brand_name": "X"}}}}
    with pytest.raises(SopContractViolation, match="entry precondition missing"):
        guarded(state)


def test_guard_refuses_a_stage_that_drops_its_declared_output():
    guarded = guard_stage("hitl_gate", lambda state: {"extracted_data": {"agency": {}}})
    state = {"extracted_data": {"agency": {"campaign_package": {}, "qa_report": {}}}}
    with pytest.raises(SopContractViolation, match="exit postcondition missing"):
        guarded(state)


def test_guard_refuses_a_stage_without_an_sop_step():
    with pytest.raises(SopContractViolation, match="has no SOP step"):
        guard_stage("unregistered_stage", lambda state: state)


def test_the_typescript_fixture_is_the_canonical_registry():
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1":
        FIXTURE.write_text(json.dumps(_raw(), indent=2) + "\n", encoding="utf-8")
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == _raw()


@pytest.fixture
def provider_success(monkeypatch):
    def fake_generate(prompt: str, fallback: dict, **kwargs):
        now = datetime.now(timezone.utc).isoformat()
        return GenerationOutcome(
            data=fallback, mode="PROVIDER_SUCCESS", provider="test-provider", model="test-model",
            schema_version=kwargs.get("schema_version", "test-v1"), prompt_version="test-v1",
            prompt_hash="test-hash", attempts=1, started_at=now, completed_at=now,
            fallback_used=False, error_class=None,
        )

    monkeypatch.setattr("services.langgraph.graph.agency.nodes.generate_structured", fake_generate)


def test_resume_after_the_run_output_changed_is_a_409_and_stales_the_approval(provider_success):
    created = client.post(
        "/agency/runs",
        json={"project_id": "proj-sop-stale", "brief": {"brand_name": "Northwind", "target_audience": "Urban"}},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]
    approval = get_approvals_for_run(run_id)[0]
    assert approval.get("subject_hash"), "the HITL approval must bind the run output hash"
    resolve_approval(approval["approval_id"], reviewer="independent-reviewer", decision="approve")

    record = get_run_record(run_id)
    tampered = json.loads(json.dumps(record["result"]))
    tampered["agency"]["campaign_package"]["edited_after_approval"] = True
    update_run_status(run_id, record["status"], tampered)

    response = client.post(f"/agency/runs/{run_id}/resume", headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 409
    assert "protected run output changed" in response.json()["detail"]
    assert get_approvals_for_run(run_id)[0]["status"] == "stale"
    assert get_run_record(run_id)["status"] == "needs_approval"
