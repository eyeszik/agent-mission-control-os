"""Mock-transport adapter tests. No real provider invocation is claimed."""
import json

import httpx
import pytest

from services.langgraph.agency.innovation import generation as g
from services.langgraph.agency.innovation.contracts import InnovationBrief
from services.langgraph.agency.model_router import HttpModelAdapter, ProviderFailure


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("AMC_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("AMC_OLLAMA_MODEL", "fictional-test-model")
    monkeypatch.delenv("AMC_LLM_DISABLED_PROVIDERS", raising=False)
    brief = InnovationBrief(objective="Fictional prototype: accessible tool sharing", provider="live")
    spec = g.create_spec(brief, "run-test", "art-test", 1, "a" * 64)
    return brief, spec


def cohort(prefix="fixture"):
    return {"ideas": [{"title": f"{prefix} mechanism {i}",
        "mechanism": f"{prefix} input {i} activates a distinct bounded transformation in a fictional test.",
        "lens_ids": [f"L{1+i%12}"], "assumptions": ["Fictional fixture input; relevance unverified"]}
        for i in range(35)]}


def fake_transport(monkeypatch, payload=None, *, transport_error=False, usage=True):
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        assert body["options"]["num_predict"] == 8192 and body["format"] == "json"
        if transport_error:
            raise httpx.ReadTimeout("fictional transport timeout")
        response = {"message": {"content": json.dumps(payload or cohort())}, "done": True}
        if usage:
            response.update(prompt_eval_count=201, eval_count=402)
        return httpx.Response(200, json=response)
    factory = g.HttpModelAdapter
    monkeypatch.setattr(g, "HttpModelAdapter", lambda *args, **kw:
        factory(*args, **kw, client=httpx.Client(transport=httpx.MockTransport(handler))))
    return calls


def test_canonical_router_is_invoked_and_output_remains_hypotheses(local, monkeypatch):
    calls = fake_transport(monkeypatch)
    result = g.invoke_generation(*local, "fixture-only-approved-reference")
    assert len(calls) == 1 and result.state == "GENERATED" and len(result.ideas) == 35
    assert result.evidence_class == "HYPOTHESIS" and result.receipt.cost_usd is None
    assert result.receipt.usage == {"input_tokens": 201, "output_tokens": 402}
    assert all(i.provenance == "MODEL_GENERATED" for i in result.ideas)


def test_two_different_briefs_are_sent_to_model_not_fixture_lookup(local, monkeypatch):
    calls = fake_transport(monkeypatch)
    brief, spec = local
    g.invoke_generation(brief, spec, "fixture-approval")
    other = InnovationBrief(objective="Fictional prototype: low-water rooftop gardens", provider="live")
    second = g.create_spec(other, "run-two", "art-two", 1, "b"*64)
    g.invoke_generation(other, second, "fixture-approval-two")
    assert calls[0]["messages"][0]["content"] != calls[1]["messages"][0]["content"]
    # This proves request conditioning only; independent output relevance is unverified.


def test_missing_authority_or_changed_brief_never_calls(local, monkeypatch):
    calls = fake_transport(monkeypatch)
    with pytest.raises(PermissionError):
        g.invoke_generation(*local, "")
    other = InnovationBrief(objective="A different fictional brief", provider="live")
    with pytest.raises(PermissionError):
        g.invoke_generation(other, local[1], "fixture")
    assert calls == []


def test_revocation_and_remote_cost_policy_fail_closed(local, monkeypatch):
    calls = fake_transport(monkeypatch)
    monkeypatch.setenv("AMC_LLM_DISABLED_PROVIDERS", "ollama")
    assert g.provider_blocker(local[1]) == "CREDENTIALS_UNAVAILABLE_OR_PROVIDER_REVOKED"
    with pytest.raises(PermissionError):
        g.invoke_generation(*local, "fixture")
    monkeypatch.setenv("AMC_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "fictional-test-only")
    remote = g.create_spec(local[0], "r", "a", 1, "c"*64)
    assert g.provider_blocker(remote) == "REMOTE_SPEND_POLICY_GAP"
    assert calls == []


def test_transport_timeout_is_not_automatically_retried(local, monkeypatch):
    calls = fake_transport(monkeypatch, transport_error=True)
    with pytest.raises(ProviderFailure):
        g.invoke_generation(*local, "fixture")
    assert len(calls) == 1


@pytest.mark.parametrize("payload,expected", [({"ideas": []}, "PARTIAL"), ({"ideas": [{}]}, "FAILED"),
    ({"ideas": cohort()["ideas"][:3]}, "PARTIAL")])
def test_invalid_or_partial_output_never_pads_fixtures(local, monkeypatch, payload, expected):
    fake_transport(monkeypatch, payload)
    result = g.invoke_generation(*local, "fixture")
    assert result.state == expected and len(result.ideas) < 35


def test_duplicate_mechanisms_flag_partial_without_claiming_semantic_originality(local, monkeypatch):
    data = cohort()
    data["ideas"][1] = data["ideas"][0].copy()
    fake_transport(monkeypatch, data)
    result = g.invoke_generation(*local, "fixture")
    assert result.state == "PARTIAL" and result.duplicate_groups
    assert "semantic diversity is NOT_VERIFIED" in " ".join(result.limitations)


def test_unknown_usage_stays_unknown(local, monkeypatch):
    fake_transport(monkeypatch, usage=False)
    assert g.invoke_generation(*local, "fixture").receipt.usage is None


def test_ollama_length_stop_is_terminal_truncation():
    client = httpx.Client(transport=httpx.MockTransport(lambda _:
        httpx.Response(200, json={"message": {"content": "{}"}, "done": True, "done_reason": "length"})))
    adapter = HttpModelAdapter("ollama", credential=None, client=client)
    with pytest.raises(ProviderFailure, match="OUTPUT_TRUNCATED"):
        adapter.invoke(model="fixture", prompt="fixture", tools=(), max_output_tokens=20, json_output=True)
    client.close()


def test_persisted_candidate_must_match_exact_prompt_route_and_idea_hash(local, monkeypatch):
    calls = fake_transport(monkeypatch)
    result = g.invoke_generation(*local, "fixture")
    g.validate_generation_result(result, *local)
    result.receipt.profile_hash = "wrong-profile"
    with pytest.raises(ValueError, match="approved request"):
        g.validate_generation_result(result, *local)
    assert len(calls) == 1


def test_qualification_cannot_be_upgraded_from_partial_by_changing_state(local, monkeypatch):
    fake_transport(monkeypatch, {"ideas": cohort()["ideas"][:2]})
    result = g.invoke_generation(*local, "fixture")
    result.state = "GENERATED"
    with pytest.raises(ValueError, match="qualification"):
        g.validate_generation_result(result, *local)
