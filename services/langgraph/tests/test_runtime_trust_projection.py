from fastapi.testclient import TestClient
from uuid import uuid4


def test_runtime_trust_projection_is_tenant_scoped(monkeypatch, tmp_path):
    db_path = tmp_path / "trust.db"
    project_id = f"proj-runtime-{uuid4()}"
    monkeypatch.setenv("AMC_AUTH_MODE", "local")
    monkeypatch.setenv("AMC_LOCAL_USER_ID", "local-user")
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", "tenant_1")
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", project_id)
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", str(db_path))
    monkeypatch.delenv("AMC_HMAC_SECRET", raising=False)

    from importlib import reload
    from services.langgraph.app import main as main_module
    reload(main_module)
    client = TestClient(main_module.app)

    response = client.get(f"/runtime/projects/{project_id}/trust")
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "tenant_1"
    assert payload["project_id"] == project_id
    assert payload["database_backend"] == "sqlite"
    assert payload["compile_blocked"] is False
    assert payload["open_invalidation_obligations"] == 0
    assert payload["hook_gap_count"] == 0
    assert payload["recent_invalidation_obligations"] == []
    assert payload["recent_policy_decisions"] == []
    assert payload["recent_outbox_messages"] == []
    assert payload["recent_recovery_cases"] == []
    assert payload["recent_lineage_remediations"] == []
    assert payload["recent_audit_events"] == []
