from __future__ import annotations

from services.langgraph.app.config import load_runtime_config


def _set_valid_production_env(monkeypatch, **overrides):
    values = {
        "AMC_ENV": "production",
        "AMC_AUTH_MODE": "supabase",
        "AMC_DATABASE_BACKEND": "postgres",
        "DATABASE_URL": "postgresql://example.invalid/postgres",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
        "AMC_CORS_ALLOWED_ORIGINS": "https://mission.example.com",
        "AMC_PUBLICATION_MODE": "disabled",
        "AMC_PAID_MEDIA_MODE": "disabled",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


class TestCorsDefaults:
    def test_local_environment_defaults_to_localhost_origins(self, monkeypatch):
        monkeypatch.delenv("AMC_CORS_ALLOWED_ORIGINS", raising=False)
        monkeypatch.delenv("AMC_ENV", raising=False)
        config = load_runtime_config()
        assert config.cors.allowed_origins == ("http://localhost:3000", "http://127.0.0.1:3000")
        assert config.cors.errors == ()

    def test_explicit_origins_are_normalized_and_deduplicated(self, monkeypatch):
        monkeypatch.setenv(
            "AMC_CORS_ALLOWED_ORIGINS",
            "https://Mission.Example.com, https://mission.example.com/, https://app.example.com:443",
        )
        config = load_runtime_config()
        assert "https://mission.example.com" in config.cors.allowed_origins
        assert "https://app.example.com:443" in config.cors.allowed_origins
        assert any("duplicate" in error for error in config.cors.errors)


class TestCorsRejections:
    def test_rejects_wildcard(self, monkeypatch):
        monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "*")
        config = load_runtime_config()
        assert config.cors.allowed_origins == ()
        assert any("wildcard" in error for error in config.cors.errors)

    def test_rejects_origin_with_path(self, monkeypatch):
        monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "https://mission.example.com/app")
        config = load_runtime_config()
        assert config.cors.allowed_origins == ()
        assert any("path" in error for error in config.cors.errors)

    def test_rejects_origin_with_query_string(self, monkeypatch):
        monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "https://mission.example.com?x=1")
        config = load_runtime_config()
        assert config.cors.allowed_origins == ()
        assert any("query" in error for error in config.cors.errors)

    def test_rejects_origin_with_fragment(self, monkeypatch):
        monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "https://mission.example.com#section")
        config = load_runtime_config()
        assert config.cors.allowed_origins == ()
        assert any("fragment" in error for error in config.cors.errors)

    def test_rejects_invalid_scheme(self, monkeypatch):
        monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "ftp://mission.example.com")
        config = load_runtime_config()
        assert config.cors.allowed_origins == ()
        assert any("http or https" in error for error in config.cors.errors)

    def test_rejects_malformed_origin(self, monkeypatch):
        monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "not-a-url")
        config = load_runtime_config()
        assert config.cors.allowed_origins == ()
        assert config.cors.errors

    def test_rejects_origin_with_embedded_credentials(self, monkeypatch):
        monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "https://user:pass@mission.example.com")
        config = load_runtime_config()
        assert config.cors.allowed_origins == ()
        assert any("credentials" in error for error in config.cors.errors)

    def test_rejects_loopback_in_production(self, monkeypatch):
        _set_valid_production_env(monkeypatch, AMC_CORS_ALLOWED_ORIGINS="http://localhost:3000")
        config = load_runtime_config()
        assert config.cors.allowed_origins == ()
        assert any("loopback" in error for error in config.cors.errors)
        assert config.errors

    def test_allows_loopback_outside_production(self, monkeypatch):
        monkeypatch.delenv("AMC_ENV", raising=False)
        monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "http://localhost:5173")
        config = load_runtime_config()
        assert config.cors.allowed_origins == ("http://localhost:5173",)
        assert config.cors.errors == ()

    def test_rejects_empty_origins_in_production(self, monkeypatch):
        _set_valid_production_env(monkeypatch, AMC_CORS_ALLOWED_ORIGINS="")
        config = load_runtime_config()
        assert config.cors.allowed_origins == ()
        assert config.cors.errors
        assert config.errors


class TestProductionGate:
    def test_valid_production_fixture_has_no_errors(self, monkeypatch):
        _set_valid_production_env(monkeypatch)
        config = load_runtime_config()
        assert config.errors == ()

    def test_non_production_never_produces_errors(self, monkeypatch):
        monkeypatch.delenv("AMC_ENV", raising=False)
        monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "*")
        config = load_runtime_config()
        assert config.errors == ()

    def test_config_never_stores_secret_values(self, monkeypatch):
        _set_valid_production_env(monkeypatch)
        config = load_runtime_config()
        rendered = repr(config)
        assert "postgresql://example.invalid/postgres" not in rendered
        assert "sb_publishable_test" not in rendered


class TestReadinessErrors:
    def test_readiness_surfaces_cors_errors_outside_production(self, monkeypatch):
        from services.langgraph.app.config import readiness_errors

        monkeypatch.delenv("AMC_ENV", raising=False)
        monkeypatch.setenv("AMC_CORS_ALLOWED_ORIGINS", "*")
        errors = readiness_errors()
        assert any("wildcard" in error for error in errors)
