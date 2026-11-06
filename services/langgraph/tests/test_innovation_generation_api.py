"""Network-free v3 invocation integration. Provider responses and actors are fixtures.

Passing these tests proves adapter wiring/recovery, never an actual live model call.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.innovation import generation as generator
from services.langgraph.agency.innovation import generation_service as gs
from services.langgraph.persistence import durable_runs
from services.langgraph.persistence.database import transaction, table
from services.langgraph.tests._project_os_support import as_user, client, new_project


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    tenant = "generation-fixture-" + uuid4().hex[:12]
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path / "exports"))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("AMC_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("AMC_OLLAMA_MODEL", "fixture-only-model")
    monkeypatch.delenv("AMC_LLM_FALLBACK_PROVIDERS", raising=False)
    monkeypatch.delenv("AMC_LLM_DISABLED_PROVIDERS", raising=False)
    as_user(monkeypatch, "fictional-author", tenant=tenant)
    project = new_project("Generation fixture")["project_id"]
    response = client.post(f"/innovation/projects/{project}/runs", headers={"Idempotency-Key": uuid4().hex},
        json={"objective": "Fixture: library tool sharing with no claimed market demand", "provider": "live"})
    assert response.status_code == 201, response.text
    base = f"/innovation/projects/{project}/runs/{response.json()['run']['run_id']}/generation"
    created = client.post(base, json={"expected_version": 1})
    assert created.status_code == 200, created.text
    return tenant, project, base, created.json()


def approve(prepared, monkeypatch):
    tenant, _, _, stage = prepared
    as_user(monkeypatch, "fictional-independent-reviewer", tenant=tenant)
    response = client.post(f"/approvals/{stage['approval']['approval_id']}/decide",
        headers={"Idempotency-Key": uuid4().hex}, json={"decision": "approve"})
    assert response.status_code == 200, response.text
    return stage


def install_fixture_invocation(monkeypatch, calls):
    def fixture_invoke(brief, spec, authorization_ref):
        calls.append(authorization_ref)
        receipt = generator.ProviderInvocationReceipt(provider="ollama", model="fixture-only-model",
            prompt_hash=canonical_hash(generator._prompt(brief, spec)), profile_hash=spec.profile_hash,
            started_at=datetime.now(timezone.utc).isoformat(), completed_at=datetime.now(timezone.utc).isoformat(),
            usage=None, outcome="OUTPUT_VALIDATED")
        return generator._qualify(generator.RawCohort(ideas=[]), spec, receipt)
    monkeypatch.setattr(gs, "invoke_generation", fixture_invoke)
    monkeypatch.setattr(gs, "provider_blocker", lambda spec: None)


def test_prepare_pins_exact_plan_and_never_self_approves(prepared):
    _, _, base, stage = prepared
    assert stage["output"] is None and stage["spec"]["max_calls"] == 1
    assert stage["approval"]["subject_type"] == "INNOVATION_GENERATION"
    assert stage["approval"]["subject_hash"] == stage["content_hash"]
    assert stage["approval"]["status"] == "pending"
    repeated = client.post(base, json={"expected_version": 1})
    assert repeated.status_code == 200 and repeated.json() == stage
    assert client.get(base).json() == stage


def test_pending_approval_cannot_invoke_even_with_provider(prepared, monkeypatch):
    calls = []
    install_fixture_invocation(monkeypatch, calls)
    response = client.post(prepared[2] + "/tick", json={"expected_version": 1})
    assert response.status_code == 200 and response.json()["status"] == "BLOCKED"
    assert not calls and not durable_runs.list_intents(prepared[3]["job_id"])


def test_self_approval_is_denied(prepared):
    response = client.post(f"/approvals/{prepared[3]['approval']['approval_id']}/decide",
        headers={"Idempotency-Key": uuid4().hex}, json={"decision": "approve"})
    assert response.status_code == 403


def test_approved_mock_invocation_is_persisted_and_replay_never_calls_again(prepared, monkeypatch):
    approve(prepared, monkeypatch)
    calls = []
    install_fixture_invocation(monkeypatch, calls)
    response = client.post(prepared[2] + "/tick", json={"expected_version": 1})
    assert response.status_code == 200, response.text
    stage = response.json()
    assert stage["status"] == "PARTIAL" and stage["output"]["receipt"]["provider"] == "ollama"
    assert stage["output"]["ideas"] == []
    assert client.get(prepared[2]).json() == stage
    assert client.post(prepared[2] + "/tick", json={"expected_version": 1}).json() == stage
    assert len(calls) == 1
    intents = durable_runs.list_intents(stage["job_id"])
    assert len(intents) == 1 and intents[0]["status"] == "COMMITTED" and intents[0]["retry_class"] == "NON_RETRYABLE"


@pytest.mark.parametrize("operation", ["prepare", "read", "tick"])
def test_cross_tenant_is_denied_before_generation(prepared, monkeypatch, operation):
    as_user(monkeypatch, "foreign-fixture", tenant="foreign-tenant")
    base = prepared[2]
    response = client.get(base) if operation == "read" else client.post(base + ("/tick" if operation == "tick" else ""), json={"expected_version": 1})
    assert response.status_code == 403


def test_source_version_and_fixture_provenance_cannot_be_upgraded(prepared):
    base = prepared[2]
    source = base.removesuffix("/generation")
    paused = client.post(source + "/control", json={"expected_version": 1, "action": "pause"})
    assert paused.status_code == 200
    assert "SOURCE_VERSION_STALE" in client.get(base).json()["reasons"]
    response = client.post(base + "/tick", json={"expected_version": 1})
    assert response.status_code == 200 and response.json()["status"] == "BLOCKED"
    project = prepared[1]
    fixture = client.post(f"/innovation/projects/{project}/runs", headers={"Idempotency-Key": uuid4().hex},
                         json={"objective": "Fixture regression must stay simulated"}).json()
    response = client.post(f"/innovation/projects/{project}/runs/{fixture['run']['run_id']}/generation", json={"expected_version": 1})
    assert response.status_code == 409


def test_provider_gap_blocks_even_after_human_approval(prepared, monkeypatch):
    approve(prepared, monkeypatch)
    monkeypatch.setattr(gs, "provider_blocker", lambda spec: "CREDENTIALS_UNAVAILABLE")
    response = client.post(prepared[2] + "/tick", json={"expected_version": 1})
    assert response.status_code == 200 and "CREDENTIALS_UNAVAILABLE" in response.json()["reasons"]
    assert not durable_runs.list_intents(prepared[3]["job_id"])


def test_unknown_invocation_outcome_never_blindly_retries(prepared, monkeypatch):
    approve(prepared, monkeypatch)
    calls = []
    def uncertain(*args, **kwargs):
        calls.append("fixture-call")
        raise TimeoutError("Fixture unknown provider outcome")
    monkeypatch.setattr(gs, "invoke_generation", uncertain)
    monkeypatch.setattr(gs, "provider_blocker", lambda spec: None)
    response = client.post(prepared[2] + "/tick", json={"expected_version": 1})
    assert response.status_code == 200 and response.json()["status"] == "RECONCILING"
    job_id = prepared[3]["job_id"]
    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('durable_jobs')} SET lease_expires_at = ? WHERE job_id = ?", ("2000-01-01T00:00:00Z", job_id))
    response = client.post(prepared[2] + "/tick", json={"expected_version": 1})
    assert response.status_code == 200 and response.json()["status"] == "RECONCILING"
    assert calls == ["fixture-call"]
    assert durable_runs.list_intents(job_id)[0]["status"] == "UNCONFIRMED"


def test_plan_version_conflict_and_client_authority_fields_refused(prepared):
    assert client.post(prepared[2] + "/tick", json={"expected_version": 2}).status_code == 409
    assert client.post(prepared[2], json={"expected_version": 1, "approved": True}).status_code == 422


def test_current_plan_bytes_are_checked_independently(prepared, monkeypatch):
    from services.langgraph.api.routes import innovation
    original = innovation.storage_adapter()
    class CorruptAdapter:
        def get_bytes(self, uri):
            data = original.get_bytes(uri)
            return data + b" "
    monkeypatch.setattr(innovation, "storage_adapter", lambda: CorruptAdapter())
    assert client.get(prepared[2]).status_code == 409


def test_local_self_approval_override_cannot_authorize_generation(prepared, monkeypatch):
    monkeypatch.setenv("AMC_ALLOW_SELF_APPROVAL", "1")
    response = client.post(f"/approvals/{prepared[3]['approval']['approval_id']}/decide",
        headers={"Idempotency-Key": uuid4().hex}, json={"decision": "approve"})
    assert response.status_code == 403
