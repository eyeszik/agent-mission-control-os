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


def test_runtime_trust_projection_mirrors_backend_compile_gate_for_hook_gap(monkeypatch, tmp_path):
    db_path = tmp_path / "trust-hook-gap.db"
    project_id = f"proj-runtime-gap-{uuid4()}"
    run_id = f"run-runtime-gap-{uuid4()}"
    monkeypatch.setenv("AMC_AUTH_MODE", "local")
    monkeypatch.setenv("AMC_LOCAL_USER_ID", "local-user")
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", "tenant_1")
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", project_id)
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", str(db_path))
    monkeypatch.delenv("AMC_HMAC_SECRET", raising=False)

    import services.langgraph.persistence.sqlite_db as sqlite_db
    from importlib import reload
    from services.langgraph.app import main as main_module
    from services.langgraph.persistence.invalidation import run_compile_gate
    from services.langgraph.persistence.runs import create_run_record, update_run_status

    sqlite_db.init_db()
    create_run_record(run_id, "tenant_1", project_id, "branding_marketing_agency", "running", {})
    update_run_status(
        run_id,
        "needs_approval",
        {
            "agency": {
                "campaign_package": {"brief": {"brand_name": "Gap"}},
                "qa_report": {"brand_safety_passed": True},
                "generation_provenance": [],
                "degraded": False,
            }
        },
    )

    backend_gate = run_compile_gate(run_id)
    assert backend_gate["compile_blocked"] is True
    assert any(item["state"] == "HOOK_GAP" for item in backend_gate["open_obligations"])

    reload(main_module)
    client = TestClient(main_module.app)
    response = client.get(f"/runtime/projects/{project_id}/trust")
    assert response.status_code == 200
    payload = response.json()
    assert payload["compile_blocked"] is True
    assert payload["hook_gap_count"] >= 1
    assert any(item["run_id"] == run_id and item["state"] == "HOOK_GAP" for item in payload["recent_invalidation_obligations"])
