from __future__ import annotations

from fastapi.testclient import TestClient

from services.langgraph.app.main import app

client = TestClient(app)


def test_health_is_pure_liveness_with_no_config_fields():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "service": "agent-mission-control-api"}


def test_ready_is_200_with_valid_local_config():
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["errors"] == []
    assert body["database_backend"] == "sqlite"


def test_ready_is_503_with_invalid_cors_configuration(monkeypatch):
    monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "*")
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert any("wildcard" in error for error in body["errors"])


def test_ready_never_leaks_secret_values(monkeypatch):
    monkeypatch.setenv("AMC_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:super-secret-password@db.example.invalid/postgres")
    response = client.get("/ready")
    assert "super-secret-password" not in response.text


def test_version_reports_app_version_and_null_build_metadata_by_default(monkeypatch):
    monkeypatch.delenv("AMC_BUILD_COMMIT_SHA", raising=False)
    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("AMC_BUILD_TIMESTAMP", raising=False)
    response = client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "0.2.0"
    assert body["commit_sha"] is None
    assert body["build_timestamp"] is None


def test_version_reports_commit_sha_when_provided(monkeypatch):
    monkeypatch.setenv("AMC_BUILD_COMMIT_SHA", "abc1234")
    response = client.get("/version")
    assert response.json()["commit_sha"] == "abc1234"
