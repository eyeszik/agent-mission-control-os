"""AMC I03: agency generation through pinned model profiles and the canonical router.

Network-free: every provider exchange runs through the real adapter dialects
against ``httpx.MockTransport`` (``provider_http`` fixture). Response shapes
follow the providers' official SDK types.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from services.langgraph.agency.model_profiles import (
    LEGACY_OPENAI_MODEL,
    ModelProfile,
    ModelRoute,
    ProfileError,
    deployment_profile,
    pin_metadata,
    pinned_profile,
    resolve_profile,
)
from services.langgraph.app.main import app
from services.langgraph.graph.agency import llm
from services.langgraph.persistence.runs import get_run_record
from services.langgraph.tests.provider_fakes import anthropic_reply, gemini_reply, openai_reply

client = TestClient(app)
GEMINI_MODEL = "gemini-fixture-model"  # a fixture id, not a claim about a real model name


def _gemini_only(monkeypatch, *, key_env="GEMINI_API_KEY"):
    monkeypatch.setenv("AMC_LLM_PROVIDER", "gemini")
    monkeypatch.setenv(key_env, "test-gemini-key")
    monkeypatch.setenv("AMC_GEMINI_MODEL", GEMINI_MODEL)


# --- Gemini-only and OpenAI regression -------------------------------------------------


def test_gemini_only_configuration_works_without_openai_key(provider_http, monkeypatch):
    _gemini_only(monkeypatch)
    provider_http.responses = [gemini_reply('{"ok": true}', prompt_tokens=40, candidate_tokens=10,
                                            thought_tokens=5, thought="private thought summary")]
    outcome = llm.generate_structured("prompt", {"ok": False})
    assert outcome.mode == "PROVIDER_SUCCESS"
    assert (outcome.provider, outcome.model, outcome.data) == ("gemini", GEMINI_MODEL, {"ok": True})
    request = provider_http.requests[0]
    assert request.url.host == "generativelanguage.googleapis.com"
    assert request.url.path == f"/v1beta/models/{GEMINI_MODEL}:generateContent"
    assert request.headers["x-goog-api-key"] == "test-gemini-key"
    assert "authorization" not in request.headers
    body = provider_http.bodies()[0]
    assert body["contents"][0]["parts"][0]["text"].startswith("prompt")
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["maxOutputTokens"] == llm.max_output_tokens()
    # Thinking tokens count as output so budgets stay conservative.
    assert outcome.usage == {"input_tokens": 40, "output_tokens": 15, "total_tokens": 55}
    assert outcome.usage_reported is True


def test_google_api_key_takes_precedence_like_the_official_sdk(provider_http, monkeypatch):
    _gemini_only(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key-wins")
    provider_http.responses = [gemini_reply('{"ok": 1}')]
    llm.generate_structured("prompt", {})
    assert provider_http.requests[0].headers["x-goog-api-key"] == "google-key-wins"


def test_openai_default_is_unchanged(provider_http, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    provider_http.responses = [openai_reply('{"ok": true}', prompt_tokens=7, completion_tokens=3)]
    outcome = llm.generate_structured("prompt", {})
    assert (outcome.provider, outcome.model) == ("openai", LEGACY_OPENAI_MODEL)
    request = provider_http.requests[0]
    assert request.url.host == "api.openai.com"
    assert request.headers["authorization"] == "Bearer test-openai-key"
    body = provider_http.bodies()[0]
    assert body["model"] == LEGACY_OPENAI_MODEL and body["temperature"] == 0.4
    assert "response_format" not in body  # OpenAI request shape is unchanged
    assert outcome.usage == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}


def test_anthropic_profile_routes_to_anthropic(provider_http, monkeypatch):
    monkeypatch.setenv("AMC_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("AMC_ANTHROPIC_MODEL", "anthropic-fixture-model")
    provider_http.responses = [anthropic_reply('{"ok": true}', input_tokens=3, output_tokens=2)]
    outcome = llm.generate_structured("prompt", {})
    assert (outcome.provider, outcome.mode) == ("anthropic", "PROVIDER_SUCCESS")
    assert provider_http.hosts() == ["api.anthropic.com"]


# --- explicit selections fail clearly, never switch provider ---------------------------


@pytest.mark.parametrize("env,error", [
    ({"AMC_LLM_PROVIDER": "not-a-provider"}, "InvalidProviderSelection"),
    ({"AMC_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "k"}, "ModelNotConfigured"),
    ({"AMC_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "AMC_GEMINI_MODEL": "../../v1/files"}, "InvalidModelId"),
    ({"AMC_LLM_PROVIDER": "gemini", "AMC_GEMINI_MODEL": GEMINI_MODEL}, "ProviderNotConfigured"),
])
def test_invalid_or_unusable_selection_degrades_without_any_request(provider_http, monkeypatch, env, error):
    monkeypatch.setenv("OPENAI_API_KEY", "present-but-not-selected")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    outcome = llm.generate_structured("prompt", {"fallback": True})
    assert outcome.mode == "FALLBACK_DEGRADED" and outcome.degraded
    assert outcome.error_class == error
    assert outcome.data == {"fallback": True}
    assert provider_http.requests == []  # no silent switch to the configured OpenAI key


def test_gemini_dialect_refuses_a_model_id_it_cannot_address(provider_http, monkeypatch):
    _gemini_only(monkeypatch)
    monkeypatch.setenv("AMC_GEMINI_MODEL", "tuned:model")  # valid for some providers, not as a Gemini path
    outcome = llm.generate_structured("prompt", {})
    assert outcome.error_class == "InvalidModelInvocation"
    assert provider_http.requests == []


# --- truncation, refusal and unknown usage ----------------------------------------------


@pytest.mark.parametrize("reply,error", [
    (gemini_reply('{"partial": ', finish_reason="MAX_TOKENS"), "OutputTruncated"),
    (gemini_reply("", finish_reason="SAFETY"), "OutputRefused"),
    (httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}), "OutputRefused"),
])
def test_truncated_or_refused_output_is_not_retried(provider_http, monkeypatch, reply, error):
    _gemini_only(monkeypatch)
    provider_http.responses = [reply, gemini_reply('{"ok": true}')]
    outcome = llm.generate_structured("prompt", {"fallback": True})
    assert outcome.mode == "FALLBACK_DEGRADED"
    assert outcome.error_class == error
    assert len(provider_http.requests) == 1
    # The provider may still have billed the call: usage is unknown, never zero.
    assert outcome.usage_reported is False
    assert outcome.unreported_token_estimate > 0
    assert llm.tokens_spent([outcome.provenance("t")]) == outcome.unreported_token_estimate


def test_openai_truncation_and_refusal_are_recognised(provider_http, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    provider_http.responses = [openai_reply('{"a":', finish_reason="length")]
    assert llm.generate_structured("p", {}).error_class == "OutputTruncated"
    provider_http.responses = [openai_reply("", refusal="I can't help with that.")]
    assert llm.generate_structured("p", {}).error_class == "OutputRefused"


def test_missing_usage_is_unknown_not_zero(provider_http, monkeypatch):
    _gemini_only(monkeypatch)
    provider_http.responses = [gemini_reply('{"ok": true}', usage=False)]
    outcome = llm.generate_structured("prompt", {})
    assert outcome.mode == "PROVIDER_SUCCESS"
    assert outcome.usage_reported is False
    provenance = outcome.provenance("task")
    assert provenance["usage_reported"] is False
    assert llm.tokens_spent([provenance]) == outcome.unreported_token_estimate > 0


# --- fallback only when explicitly allowed ---------------------------------------------


def test_no_fallback_unless_configured(provider_http, monkeypatch):
    _gemini_only(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    provider_http.responses = [httpx.Response(503)] * 3
    outcome = llm.generate_structured("prompt", {})
    assert outcome.mode == "FALLBACK_DEGRADED"
    assert set(provider_http.hosts()) == {"generativelanguage.googleapis.com"}


def test_configured_fallback_is_used_and_recorded(provider_http, monkeypatch):
    _gemini_only(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("AMC_LLM_FALLBACK_PROVIDERS", "openai")
    provider_http.responses = [httpx.Response(503), openai_reply('{"ok": true}', prompt_tokens=5, completion_tokens=5)]
    outcome = llm.generate_structured("prompt", {})
    assert (outcome.mode, outcome.provider) == ("PROVIDER_SUCCESS", "openai")
    assert outcome.route == ("gemini", "openai")
    assert provider_http.hosts() == ["generativelanguage.googleapis.com", "api.openai.com"]
    assert outcome.usage_reported is False  # the failed Gemini call's usage is unknown


# --- precedence, pinning and revocation -------------------------------------------------


def test_selection_precedence_is_run_project_tenant_deployment():
    deployment = ModelProfile(source="deployment", primary=ModelRoute(provider="openai", model="a"))
    tenant = ModelProfile(source="deployment", primary=ModelRoute(provider="gemini", model="t"))
    project = ModelProfile(source="deployment", primary=ModelRoute(provider="anthropic", model="p"))
    run = ModelProfile(source="deployment", primary=ModelRoute(provider="ollama", model="r"))
    assert resolve_profile(deployment=deployment).source == "deployment"
    assert resolve_profile(deployment=deployment, tenant=tenant).primary.model == "t"
    picked = resolve_profile(deployment=deployment, tenant=tenant, project=project)
    assert (picked.source, picked.primary.model) == ("project", "p")
    picked = resolve_profile(deployment=deployment, tenant=tenant, project=project, run=run)
    assert (picked.source, picked.primary.model) == ("run", "r")


def test_pinned_profile_survives_a_config_change(provider_http, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    metadata = {"model_profile": pin_metadata()}
    _gemini_only(monkeypatch)  # the deployment default changes after the run was created
    provider_http.responses = [openai_reply('{"ok": true}')]
    outcome = llm.generate_structured("prompt", {}, run_metadata=metadata)
    assert outcome.provider == "openai"
    assert outcome.profile_hash == metadata["model_profile"]["profile_hash"]


def test_tampered_or_errored_pins_fail_clearly(provider_http, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    pin = pin_metadata()
    tampered = {**pin, "primary": {"provider": "openai", "model": "other-model"}}
    assert llm.generate_structured("p", {}, run_metadata={"model_profile": tampered}).error_class == "ProfilePinMismatch"
    errored = {"model_profile": {"schema_version": "amc.model-profile/v1", "error": "MODEL_NOT_CONFIGURED"}}
    assert llm.generate_structured("p", {}, run_metadata=errored).error_class == "ModelNotConfigured"
    with pytest.raises(ProfileError):
        pinned_profile({"model_profile": "not-a-mapping"})
    assert provider_http.requests == []


def test_revoked_credential_or_disabled_provider_stops_a_pinned_run(provider_http, monkeypatch):
    _gemini_only(monkeypatch)
    metadata = {"model_profile": pin_metadata()}
    monkeypatch.setenv("AMC_LLM_DISABLED_PROVIDERS", "gemini")
    assert llm.generate_structured("p", {}, run_metadata=metadata).error_class == "ProviderNotConfigured"
    monkeypatch.delenv("AMC_LLM_DISABLED_PROVIDERS")
    monkeypatch.delenv("GEMINI_API_KEY")
    assert llm.generate_structured("p", {}, run_metadata=metadata).error_class == "ProviderNotConfigured"
    assert provider_http.requests == []


def test_deployment_fallbacks_need_their_own_model_and_drop_duplicates(monkeypatch):
    env = {"AMC_LLM_PROVIDER": "gemini", "AMC_GEMINI_MODEL": "g", "AMC_LLM_FALLBACK_PROVIDERS": "gemini, openai ,openai"}
    profile = deployment_profile(env)
    assert [r.provider for r in profile.routes] == ["gemini", "openai"]
    with pytest.raises(ProfileError) as exc:
        deployment_profile({**env, "AMC_LLM_FALLBACK_PROVIDERS": "anthropic"})
    assert exc.value.code == "MODEL_NOT_CONFIGURED"


# --- the agency run pins its profile and every stage uses it ----------------------------


def _create_run(project_id: str):
    response = client.post(
        "/agency/runs",
        json={"project_id": project_id, "brief": {"brand_name": "Northwind", "target_audience": "Makers"}},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_agency_run_pins_profile_and_every_stage_reports_it(provider_http, monkeypatch):
    _gemini_only(monkeypatch)
    # Every stage gets a JSON object it may not fully use; what matters is the route.
    provider_http.responses = [gemini_reply('{"note": "fixture"}', prompt_tokens=1, candidate_tokens=1)] * 4
    body = _create_run(f"proj-i03-{uuid4()}")
    record = get_run_record(body["run_id"])
    pin = record["metadata"]["model_profile"]
    assert pin["primary"] == {"provider": "gemini", "model": GEMINI_MODEL}
    assert pinned_profile(record["metadata"]).profile_hash == pin["profile_hash"]
    assert set(provider_http.hosts()) == {"generativelanguage.googleapis.com"}
    assert len(provider_http.requests) == 4
    provenance = record["result"]["agency"]["generation_provenance"]
    assert [p["mode"] for p in provenance] == ["PROVIDER_SUCCESS"] * 4
    assert {p["provider"] for p in provenance} == {"gemini"}
    assert {p["profile_hash"] for p in provenance} == {pin["profile_hash"]}
    # A Gemini-only run is not degraded, so the provider no longer blocks its release.
    assert body["degraded"] is False


def test_invalid_deployment_selection_is_pinned_and_blocks_generation(provider_http, monkeypatch):
    monkeypatch.setenv("AMC_LLM_PROVIDER", "not-a-provider")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    body = _create_run(f"proj-i03-{uuid4()}")
    record = get_run_record(body["run_id"])
    assert record["metadata"]["model_profile"]["error"] == "INVALID_PROVIDER_SELECTION"
    assert provider_http.requests == []
    assert json.dumps(record["metadata"]).count("test-gemini-key") == 0
