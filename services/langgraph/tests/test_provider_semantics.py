from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.graph.agency.llm import generate_structured
from services.langgraph.quality.evaluator import evaluate_quality
from services.langgraph.tests.provider_fakes import openai_reply

client = TestClient(app)


def test_provider_absence_is_explicitly_degraded(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    outcome = generate_structured("return data", {"value": "fallback"})
    assert outcome.mode == "FALLBACK_DEGRADED"
    assert outcome.fallback_used is True
    assert outcome.error_class == "ProviderNotConfigured"
    assert outcome.data == {"value": "fallback"}


def test_malformed_provider_output_retries_three_times_then_degrades(provider_http, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    provider_http.responses = [openai_reply("not-json") for _ in range(3)]
    outcome = generate_structured("return data", {"value": "fallback"})
    assert len(provider_http.requests) == 3
    assert outcome.mode == "FALLBACK_DEGRADED"
    assert outcome.attempts == 3
    assert outcome.error_class in {"JSONDecodeError", "ValueError"}


def test_local_quality_evaluator_does_not_invent_grounded_metrics():
    result = evaluate_quality("This is a sufficiently long deterministic local heuristic sample for testing.")
    assert result["evaluation_mode"] == "heuristic"
    assert result["faithfulness"] == "NOT_MEASURED"
    assert result["hallucination_rate"] == "NOT_MEASURED"
    assert result["output_relevance"] == "NOT_MEASURED"


def test_degraded_agency_run_cannot_be_delivered(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create = client.post(
        "/agency/runs",
        json={
            "project_id": "proj-provider-test",
            "brief": {"brand_name": "Acme", "target_audience": "Developers"},
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert create.status_code == 201
    body = create.json()
    approval_id = body["pending_approval"]["approval_id"]

    decision = client.post(
        f"/approvals/{approval_id}/decide",
        json={"decision": "approve"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert decision.status_code == 200

    resume = client.post(
        f"/agency/runs/{body['run_id']}/resume",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert resume.status_code == 409
    assert "degraded provider output" in resume.json()["detail"].lower()
