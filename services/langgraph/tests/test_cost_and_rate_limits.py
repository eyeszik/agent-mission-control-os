from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.graph.agency import llm
from services.langgraph.persistence.runs import RunLimitExceeded, create_run_record, update_run_status

client = TestClient(app)


# --- provider call bounds and token budget ------------------------------------


class _FakeChat:
    calls: list[dict] = []
    responses: list = []

    def __init__(self, **kwargs):
        _FakeChat.calls.append(kwargs)

    def invoke(self, _prompt):
        response = _FakeChat.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def fake_openai(monkeypatch):
    import langchain_openai

    _FakeChat.calls = []
    _FakeChat.responses = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _FakeChat)
    return _FakeChat


def _ok(total: int = 300) -> SimpleNamespace:
    return SimpleNamespace(content='{"ok": true}', usage_metadata={"input_tokens": total - 100, "output_tokens": 100, "total_tokens": total})


def test_every_provider_call_is_bounded(fake_openai, monkeypatch):
    monkeypatch.setenv("AMC_LLM_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("AMC_LLM_MAX_OUTPUT_TOKENS", "700")
    fake_openai.responses = [_ok()]
    outcome = llm.generate_structured("prompt", {"ok": False})
    assert outcome.mode == "PROVIDER_SUCCESS"
    call = fake_openai.calls[0]
    assert call["timeout"] == 12.0
    assert call["max_tokens"] == 700
    assert call["max_retries"] == 0


def test_usage_is_recorded_in_provenance_including_failed_attempts(fake_openai):
    fake_openai.responses = [SimpleNamespace(content="not json", usage_metadata={"input_tokens": 50, "output_tokens": 20, "total_tokens": 70}), _ok(300)]
    outcome = llm.generate_structured("prompt", {"ok": False})
    assert outcome.attempts == 2
    assert outcome.provenance("task")["usage"] == {"input_tokens": 250, "output_tokens": 120, "total_tokens": 370}


def test_exhausted_run_budget_degrades_without_calling_the_provider(fake_openai, monkeypatch):
    monkeypatch.setenv("AMC_MAX_TOKENS_PER_RUN", "5000")
    fake_openai.responses = [_ok()]
    outcome = llm.generate_structured("prompt", {"ok": False}, run_tokens_spent=4900)
    assert outcome.mode == "FALLBACK_DEGRADED"
    assert outcome.error_class == llm.BUDGET_EXHAUSTED
    assert outcome.attempts == 0
    assert fake_openai.calls == []


def test_retries_debit_the_same_budget(fake_openai, monkeypatch):
    monkeypatch.setenv("AMC_MAX_TOKENS_PER_RUN", "5000")
    monkeypatch.setenv("AMC_LLM_MAX_OUTPUT_TOKENS", "1000")
    expensive_failure = SimpleNamespace(content="not json", usage_metadata={"input_tokens": 1500, "output_tokens": 1000, "total_tokens": 2500})
    fake_openai.responses = [expensive_failure, expensive_failure, _ok()]
    outcome = llm.generate_structured("prompt", {"ok": False})
    # Each failed attempt spends 2500 tokens. After two, nothing is left for a
    # third attempt, so retries stop at the ceiling instead of exceeding it.
    assert outcome.mode == "FALLBACK_DEGRADED"
    assert outcome.error_class == llm.BUDGET_EXHAUSTED
    assert len(fake_openai.calls) == 2
    assert outcome.provenance("task")["usage"]["total_tokens"] == 5000


def test_tokens_spent_sums_run_provenance():
    provenance = [{"usage": {"total_tokens": 120}}, {"usage": {"total_tokens": 80}}, {"mode": "FALLBACK_DEGRADED"}]
    assert llm.tokens_spent(provenance) == 200


def test_pipeline_passes_accumulated_spend_to_each_stage(monkeypatch):
    from services.langgraph.graph.agency.build import build_agency_workflow
    from services.langgraph.tests.test_agency_pipeline import _initial_state, _make_run

    seen: list[int] = []
    real = llm.generate_structured

    def spy(prompt, fallback, **kwargs):
        seen.append(kwargs.get("run_tokens_spent", -1))
        outcome = real(prompt, fallback, **kwargs)
        return outcome.__class__(**{**outcome.__dict__, "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 100}})

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("services.langgraph.graph.agency.nodes.generate_structured", spy)
    run = _make_run()
    build_agency_workflow().invoke(_initial_state(run), config={"configurable": {"thread_id": str(run.id)}})
    assert seen == [0, 100, 200, 300]


# --- per-tenant run limits ------------------------------------------------------


def _create(project_id: str):
    return client.post(
        "/agency/runs",
        json={"project_id": project_id, "brief": {"brand_name": "Northwind", "target_audience": "Makers"}},
        headers={"Idempotency-Key": str(uuid4())},
    )


def test_hourly_run_limit_returns_429(monkeypatch):
    tenant = f"tenant-limit-{uuid4()}"
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", tenant)
    monkeypatch.setenv("AMC_MAX_RUNS_PER_TENANT_PER_HOUR", "2")
    monkeypatch.setenv("AMC_MAX_ACTIVE_RUNS_PER_TENANT", "0")
    project = f"proj-limit-{uuid4()}"
    assert _create(project).status_code == 201
    assert _create(project).status_code == 201
    limited = _create(project)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "300"
    # Other tenants are unaffected.
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", f"tenant-other-{uuid4()}")
    assert _create(f"proj-other-{uuid4()}").status_code == 201


def test_active_run_limit_counts_only_in_progress_runs(monkeypatch):
    tenant = f"tenant-active-{uuid4()}"
    monkeypatch.setenv("AMC_MAX_RUNS_PER_TENANT_PER_HOUR", "0")
    monkeypatch.setenv("AMC_MAX_ACTIVE_RUNS_PER_TENANT", "1")
    project = f"proj-active-{uuid4()}"
    running = f"run-{uuid4()}"
    create_run_record(running, tenant, project, "branding_marketing_agency", "running", {}, enforce_limits=True)
    with pytest.raises(RunLimitExceeded):
        create_run_record(f"run-{uuid4()}", tenant, project, "branding_marketing_agency", "running", {}, enforce_limits=True)
    update_run_status(running, "needs_approval")
    create_run_record(f"run-{uuid4()}", tenant, project, "branding_marketing_agency", "running", {}, enforce_limits=True)


def test_rate_limited_create_leaves_no_run_and_releases_the_idempotency_key(monkeypatch):
    tenant = f"tenant-release-{uuid4()}"
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", tenant)
    monkeypatch.setenv("AMC_MAX_RUNS_PER_TENANT_PER_HOUR", "1")
    project = f"proj-release-{uuid4()}"
    assert _create(project).status_code == 201
    key = str(uuid4())
    body = {"project_id": project, "brief": {"brand_name": "Northwind", "target_audience": "Makers"}}
    first = client.post("/agency/runs", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 429
    # The failed reservation is released, so the same key is not stuck "in progress".
    monkeypatch.setenv("AMC_MAX_RUNS_PER_TENANT_PER_HOUR", "0")
    retry = client.post("/agency/runs", json=body, headers={"Idempotency-Key": key})
    assert retry.status_code in (201, 409)
    assert retry.status_code != 429
