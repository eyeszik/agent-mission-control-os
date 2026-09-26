from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.agency.execution.models import (
    CompletionCriterionResult,
    CompletionEvaluation,
    CriterionStatus,
    DispatchPermit,
    ExecutionReceipt,
    FailureFingerprint,
    ObservationReceipt,
)
from services.langgraph.app.main import app
from services.langgraph.graph.agency.llm import GenerationOutcome
from services.langgraph.persistence.proofs import (
    get_run_proof_bundle,
    put_completion_evaluation,
    put_dispatch_permit,
    put_execution_receipt,
    put_failure_fingerprint,
    put_observation_receipt,
)

client = TestClient(app)


def test_proof_bundle_round_trip():
    run_id = str(uuid4())
    tenant_id = "tenant_1"
    project_id = "proj_1"
    now = datetime.now(timezone.utc)

    put_dispatch_permit(
        run_id,
        tenant_id,
        project_id,
        DispatchPermit(
            permit_id=str(uuid4()),
            work_order_id=run_id,
            project_snapshot_hash="a" * 64,
            causal_epoch=0,
            eligibility_policy_version="amc-dispatch/v1",
        ),
    )
    put_execution_receipt(
        run_id,
        tenant_id,
        project_id,
        ExecutionReceipt(
            operation_id=f"op:{run_id}",
            work_order_id=run_id,
            actor_role_id="agency-orchestrator",
            tool="langgraph.workflow",
            tool_contract_ref="amc.agency.workflow/v1",
            args_hash="b" * 64,
            target=run_id,
            idempotency_key="idem-test",
            attempt=1,
            started_at=now,
            ended_at=now,
            returned_state="SUCCEEDED",
            result_ref=run_id,
        ),
    )
    put_observation_receipt(
        run_id,
        tenant_id,
        project_id,
        ObservationReceipt(
            operation_id=f"op:{run_id}",
            target=run_id,
            expected_postcondition={"status": "completed"},
            observed_postcondition={"status": "completed"},
            observation_method="test",
            matches=True,
        ),
    )
    put_failure_fingerprint(
        run_id,
        tenant_id,
        project_id,
        f"op:{run_id}:failed",
        FailureFingerprint(
            fingerprint="c" * 64,
            failure_class="EXECUTION_FAILURE",
            causal_node="delivery",
            work_order_input_hash="d" * 64,
            dependency_snapshot_hash="e" * 64,
            tool_contract_hash="f" * 64,
            environment_signature="test",
            error_class="SyntheticError",
        ),
    )
    put_completion_evaluation(
        run_id,
        tenant_id,
        project_id,
        CompletionEvaluation(
            terminal_candidate="COMPLETE",
            criteria=(CompletionCriterionResult(criterion_ref="execution", status=CriterionStatus.SATISFIED),),
            proof_coverage=1.0,
            evidence_score=1.0,
            quality_score=1.0,
            confidence=0.95,
        ),
    )

    bundle = get_run_proof_bundle(run_id)
    assert bundle["summary"]["dispatch_count"] == 1
    assert bundle["summary"]["execution_count"] == 1
    assert bundle["summary"]["observation_count"] == 1
    assert bundle["summary"]["matched_observation_count"] == 1
    assert bundle["summary"]["failure_count"] == 1
    assert bundle["summary"]["latest_terminal_candidate"] == "COMPLETE"


def test_create_and_resume_agency_run_emits_proof_bundle(monkeypatch):
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

    create = client.post(
        "/agency/runs",
        json={
            "project_id": f"proj-proof-{uuid4()}",
            "brief": {"brand_name": "Northwind", "target_audience": "Urban professionals"},
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert create.status_code == 201
    created = create.json()
    assert created["proof"]["summary"]["dispatch_count"] == 1
    assert created["proof"]["summary"]["execution_count"] == 1
    assert created["proof"]["summary"]["observation_count"] == 1
    assert created["proof"]["summary"]["latest_terminal_candidate"] == "BLOCKED"

    approval_id = created["pending_approval"]["approval_id"]
    decide = client.post(
        f"/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert decide.status_code == 200

    resume = client.post(
        f"/agency/runs/{created['run_id']}/resume",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert resume.status_code == 200
    resumed = resume.json()
    assert resumed["status"] == "completed"
    assert resumed["delivery"]
    assert resumed["proof"]["summary"]["latest_terminal_candidate"] == "COMPLETE"
    assert resumed["proof"]["summary"]["proof_coverage"] == 1.0

    trust = client.get(f"/runtime/projects/{created['project_id']}/trust")
    assert trust.status_code == 200
    trust_payload = trust.json()
    assert trust_payload["compile_blocked"] is False
    # Non-applicable MEMORY_WRITE / CLOCK_WINDOW_ADVANCE gaps remain observable,
    # but are not demanded for this pipeline and therefore cannot authorize/block release.
    assert trust_payload["hook_gap_count"] >= 1
    assert trust_payload["policy_decisions"] >= 1
    assert trust_payload["delivered_outbox"] >= 1
    assert trust_payload["pending_outbox"] == 0
    assert trust_payload["open_recovery_cases"] == 0
    assert trust_payload["recent_policy_decisions"][0]["action"] in {"agency.resume", "approval.decide", "agency.create"}
