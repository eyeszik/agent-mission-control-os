from __future__ import annotations

import importlib

import pytest


def test_production_config_accepts_fail_closed_fixture(monkeypatch):
    monkeypatch.setenv("AMC_ENV", "production")
    monkeypatch.setenv("AMC_AUTH_MODE", "supabase")
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/postgres")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "https://mission.example.com")
    monkeypatch.setenv("AMC_PUBLICATION_MODE", "disabled")
    monkeypatch.setenv("AMC_PAID_MEDIA_MODE", "disabled")

    from services.langgraph.app.config import production_config_errors

    assert production_config_errors() == []


def test_production_config_rejects_live_external_mutations(monkeypatch):
    monkeypatch.setenv("AMC_ENV", "production")
    monkeypatch.setenv("AMC_AUTH_MODE", "supabase")
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/postgres")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "https://mission.example.com")
    monkeypatch.setenv("AMC_PUBLICATION_MODE", "live")
    monkeypatch.setenv("AMC_PAID_MEDIA_MODE", "live")

    from services.langgraph.app.config import production_config_errors

    errors = production_config_errors()
    assert any("AMC_PUBLICATION_MODE" in item for item in errors)
    assert any("AMC_PAID_MEDIA_MODE" in item for item in errors)


def test_paid_media_has_no_execution_capability(monkeypatch):
    monkeypatch.setenv("AMC_PAID_MEDIA_MODE", "live")
    from services.langgraph.integrations.paid_media import spend_execution_available

    assert spend_execution_available() is False


def test_publication_live_mode_has_no_provider_executor(monkeypatch, tmp_path):
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", str(tmp_path / "publication.db"))
    monkeypatch.setenv("AMC_PUBLICATION_MODE", "live")

    import services.langgraph.persistence.sqlite_db as sqlite_db
    sqlite_db.DB_PATH = str(tmp_path / "publication.db")
    sqlite_db.init_db()

    from services.langgraph.integrations.publication import prepare_publication

    with pytest.raises(RuntimeError, match="Live publication is intentionally unavailable"):
        prepare_publication("run", "tenant", "project", "provider", {"message": "preview"}, "idem")


def test_first_party_analytics_persists_locally(monkeypatch, tmp_path):
    db_path = str(tmp_path / "analytics.db")
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", db_path)

    import services.langgraph.persistence.sqlite_db as sqlite_db
    sqlite_db.DB_PATH = db_path
    sqlite_db.init_db()

    import services.langgraph.persistence.analytics as analytics
    importlib.reload(analytics)

    event = analytics.record_analytics_event(
        "tenant_1",
        "proj_1",
        "production_foundation_test",
        {"source": "pytest"},
    )
    assert event["source"] == "amc_first_party"
    assert event["event_name"] == "production_foundation_test"
    assert event["properties"] == {"source": "pytest"}
