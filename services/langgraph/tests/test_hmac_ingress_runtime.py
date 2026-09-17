import hashlib
import hmac
import os

from fastapi.testclient import TestClient


def _sign(body: bytes, secret: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def test_hmac_protected_runtime_ingress_rejects_missing_signature(monkeypatch):
    secret = b"runtime-secret"
    monkeypatch.setenv("AMC_HMAC_SECRET", secret.decode("utf-8"))
    monkeypatch.setenv("AMC_AUTH_MODE", "local")
    monkeypatch.setenv("AMC_LOCAL_USER_ID", "local-user")
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", "tenant_1")
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", "proj_1")
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", "/tmp/amc_hmac_runtime.db")

    from importlib import reload
    from services.langgraph.app import main as main_module
    reload(main_module)
    client = TestClient(main_module.app)

    response = client.post("/runtime/ingest", json={
        "operation_id": "op-1",
        "mission_id": "mission-1",
        "project_id": "proj_1",
        "payload": {"x": 1},
    })
    assert response.status_code == 401


def test_hmac_protected_runtime_ingress_accepts_valid_signature(monkeypatch):
    secret = b"runtime-secret"
    monkeypatch.setenv("AMC_HMAC_SECRET", secret.decode("utf-8"))
    monkeypatch.setenv("AMC_AUTH_MODE", "local")
    monkeypatch.setenv("AMC_LOCAL_USER_ID", "local-user")
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", "tenant_1")
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", "proj_1")
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", "/tmp/amc_hmac_runtime_valid.db")

    from importlib import reload
    from services.langgraph.app import main as main_module
    reload(main_module)
    client = TestClient(main_module.app)

    body = b'{"operation_id":"op-1","mission_id":"mission-1","project_id":"proj_1","payload":{"x":1}}'
    response = client.post(
        "/runtime/ingest",
        content=body,
        headers={"Content-Type": "application/json", "X-AMC-Signature": _sign(body, secret)},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["durable"] is False

