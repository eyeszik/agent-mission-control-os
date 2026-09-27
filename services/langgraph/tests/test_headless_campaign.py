import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("headless", ROOT / "scripts/run_campaign_headless.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_dry_run_removes_provider_and_production_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-key")
    monkeypatch.setenv("DATABASE_URL", "postgres://not-production")
    env = module.runtime_env(tmp_path, "dry-run")
    assert "OPENAI_API_KEY" not in env and "DATABASE_URL" not in env
    assert env["AMC_PUBLICATION_MODE"] == env["AMC_PAID_MEDIA_MODE"] == "disabled"
    assert env["AMC_AUTH_MODE"] == "local"


def test_live_requires_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        module.runtime_env(tmp_path, "live")


def test_degraded_is_not_deliverable():
    assert module.classify({"status": "needs_approval", "degraded": True}, "dry-run") == "DEGRADED_DRY_RUN_NOT_DELIVERABLE"


@pytest.mark.parametrize("result", [{"status": "completed"}, {"status": "needs_approval", "degraded": True}, {"status": "needs_approval", "generation_provenance": []}])
def test_live_rejects_unsafe_or_unproven_results(result):
    with pytest.raises(ValueError):
        module.classify(result, "live")


def test_live_stops_for_review():
    result = {"status": "needs_approval", "degraded": False, "generation_provenance": [{"mode": "PROVIDER_SUCCESS"}]}
    assert module.classify(result, "live") == "GENERATED_AWAITING_HUMAN_REVIEW"
