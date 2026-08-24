from fastapi.testclient import TestClient


def test_runtime_trust_projection_is_tenant_scoped(monkeypatch, tmp_path):
    db_path = tmp_path / "trust.db"
    monkeypatch.setenv("AMC_AUTH_MODE", "local")
    monkeypatch.setenv("AMC_LOCAL_USER_ID", "local-user")
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", "tenant_1")
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", "proj_1")
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", str(db_path))
    monkeypatch.delenv("AMC_HMAC_SECRET", raising=False)

    from importlib import reload
    from services.langgraph.app import main as main_module
    reload(main_module)
    client = TestClient(main_module.app)

    response = client.get("/runtime/projects/proj_1/trust")
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "tenant_1"
    assert payload["project_id"] == "proj_1"
    assert payload["database_backend"] == "sqlite"
