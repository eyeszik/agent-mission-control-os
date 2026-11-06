"""Network-free, real HTTP transport-contract tests for ACE provider routing."""
import json

import httpx
import pytest

from services.langgraph.agency.ace_controls import Capability
from services.langgraph.agency.model_router import (
    HttpModelAdapter, ModelRouter, NoEligibleProvider, ToolSpec,
)


def _cap(provider, *, priority=1, complexity=5, rpm=6000):
    return Capability(
        provider_id=provider, model_id="fixture-model",
        capabilities=frozenset({"structured_output", "tool_calls"}),
        complexity_ceiling=complexity, available=True, priority=priority,
        rate_limit_per_minute=rpm, cost_per_million_tokens=0,
    )


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ace_openai_tool_dialect_and_usage_normalization():
    requests = []

    def handler(req):
        requests.append(req)
        assert req.url.host == "api.openai.com"
        assert req.headers["authorization"] == "Bearer test-only-key"
        assert json.loads(req.content)["tools"][0]["function"]["name"] == "search"
        return httpx.Response(200, json={
            "choices": [{"message": {
                "content": "done", "tool_calls": [
                    {"function": {"name": "search", "arguments": '{"query":"x"}'}}
                ],
            }}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        })

    router = ModelRouter(
        capabilities=(_cap("openai"),),
        adapters={"openai": HttpModelAdapter("openai", credential="test-only-key", client=_client(handler))},
    )
    result = router.invoke(
        prompt="research", capability="tool_calls", complexity=2,
        allowed_providers=frozenset({"openai"}), authorization_ref="approval-1",
        tools=(ToolSpec("search", "Lookup", {"type": "object", "properties": {}}),),
    )
    assert result.provider == "openai"
    assert result.text == "done"
    assert result.tool_calls[0].arguments == {"query": "x"}
    assert result.usage == {"input_tokens": 4, "output_tokens": 2}
    assert len(requests) == 1


def test_ace_fallback_respects_allowed_providers_and_capability():
    called = []

    def fail_openai(req):
        called.append("openai")
        return httpx.Response(503)

    def anthropic(req):
        called.append("anthropic")
        assert req.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "secondary"},
                        {"type": "tool_use", "name": "lookup", "input": {"x": 2}}],
            "usage": {"input_tokens": 3, "output_tokens": 1},
        })

    router = ModelRouter(
        capabilities=(_cap("openai", priority=0), _cap("anthropic", priority=1)),
        adapters={
            "openai": HttpModelAdapter("openai", credential="fixture", client=_client(fail_openai)),
            "anthropic": HttpModelAdapter("anthropic", credential="fixture", client=_client(anthropic)),
        }, max_attempts=1,
    )
    answer = router.invoke(
        prompt="ask", capability="structured_output", complexity=3,
        allowed_providers=frozenset({"openai", "anthropic"}), authorization_ref="approval-2",
    )
    assert answer.provider == "anthropic"
    assert answer.route == ("openai", "anthropic")
    assert answer.tool_calls[0].name == "lookup"
    assert called == ["openai", "anthropic"]
    with pytest.raises(NoEligibleProvider):
        router.invoke(prompt="ask", capability="unknown", complexity=5,
                      allowed_providers=frozenset({"openai"}), authorization_ref="approval-2")


def test_ace_ollama_local_loopback_and_authorization_gate():
    seen = []

    def handler(req):
        seen.append(req.url.host)
        assert not req.headers.get("authorization")
        return httpx.Response(200, json={
            "message": {"content": '{"count":1}'},
            "prompt_eval_count": 7, "eval_count": 3,
        })

    router = ModelRouter(
        capabilities=(_cap("ollama"),),
        adapters={"ollama": HttpModelAdapter("ollama", credential=None, client=_client(handler))},
    )
    with pytest.raises(PermissionError):
        router.invoke(prompt="local", capability="structured_output", complexity=1,
                      allowed_providers=frozenset({"ollama"}), authorization_ref="")
    assert seen == []
    reply = router.invoke(prompt="local", capability="structured_output", complexity=1,
                          allowed_providers=frozenset({"ollama"}), authorization_ref="local-approved")
    assert reply.usage["input_tokens"] == 7
    assert seen == ["127.0.0.1"]


def test_ace_429_backoff_jitter_and_bounded_retries():
    counter = {"calls": 0}
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    def handler(req):
        counter["calls"] += 1
        if counter["calls"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        })

    router = ModelRouter(
        capabilities=(_cap("openai"),),
        adapters={"openai": HttpModelAdapter("openai", credential="fixture", client=_client(handler))},
        sleep=sleep, clock=lambda: now[0], jitter=lambda: 0.5,
        max_attempts=2,
    )
    result = router.invoke(prompt="x", capability="structured_output", complexity=1,
                           allowed_providers=frozenset({"openai"}), authorization_ref="approval-3")
    assert result.attempts == 2
    assert counter["calls"] == 2
    assert 0 < sum(sleeps) <= 2


def test_ace_malformed_provider_tool_payload_cannot_be_accepted():
    def handler(req):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "unsafe", "tool_calls": [
                {"function": {"name": "call", "arguments": "not-json"}}
            ]}}],
        })
    router = ModelRouter(
        capabilities=(_cap("openai"),),
        adapters={"openai": HttpModelAdapter("openai", credential="fixture", client=_client(handler))},
        max_attempts=1,
    )
    with pytest.raises(NoEligibleProvider):
        router.invoke(prompt="execute", capability="tool_calls", complexity=1,
                      allowed_providers=frozenset({"openai"}), authorization_ref="approval-4")
