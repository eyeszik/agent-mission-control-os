"""Tests for the fail-closed zo.computer integration.

No test in this module performs a real network call. httpx.post is patched
in every path that would otherwise reach the network, so these tests are
safe to run without ZO_API_KEY ever being set in the environment.
"""

from __future__ import annotations

import httpx
import pytest

from services.langgraph.integrations import zo


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AMC_ZO_MODE", raising=False)
    monkeypatch.delenv("ZO_API_KEY", raising=False)
    assert zo.zo_available() is False


def test_unavailable_without_api_key_even_when_live(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.delenv("ZO_API_KEY", raising=False)
    assert zo.zo_available() is False


def test_available_only_when_live_and_keyed(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_test_only")
    assert zo.zo_available() is True


def test_ask_zo_raises_when_disabled(monkeypatch):
    monkeypatch.delenv("AMC_ZO_MODE", raising=False)
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_test_only")
    with pytest.raises(zo.ZoIntegrationError, match="disabled"):
        zo.ask_zo("hello")


def test_ask_zo_raises_when_live_but_unkeyed(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.delenv("ZO_API_KEY", raising=False)
    with pytest.raises(zo.ZoIntegrationError, match="ZO_API_KEY"):
        zo.ask_zo("hello")


def test_ask_zo_rejects_empty_prompt(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_test_only")
    with pytest.raises(ValueError):
        zo.ask_zo("   ")


def test_ask_zo_sends_bearer_header_and_returns_json(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_test_only")

    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return httpx.Response(200, json={"answer": "ok"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(zo.httpx, "post", fake_post)

    result = zo.ask_zo("what is zo.computer", timeout_seconds=5.0)

    assert result == {"answer": "ok"}
    assert captured["url"] == f"{zo.ZO_API_BASE}/zo/ask"
    assert captured["headers"]["Authorization"] == "Bearer zo_sk_test_only"
    assert captured["json"] == {"prompt": "what is zo.computer"}
    assert captured["timeout"] == 5.0


def test_ask_zo_never_leaks_api_key_in_error_message(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_super_secret_value")

    def fake_post(url, *, headers, json, timeout):
        return httpx.Response(500, text="upstream error", request=httpx.Request("POST", url))

    monkeypatch.setattr(zo.httpx, "post", fake_post)

    with pytest.raises(zo.ZoIntegrationError) as excinfo:
        zo.ask_zo("hello")
    assert "zo_sk_super_secret_value" not in str(excinfo.value)


def test_ask_zo_wraps_transport_failure(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_test_only")

    def fake_post(url, *, headers, json, timeout):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(zo.httpx, "post", fake_post)

    with pytest.raises(zo.ZoIntegrationError, match="request failed"):
        zo.ask_zo("hello")


def test_ask_zo_rejects_non_json_response(monkeypatch):
    monkeypatch.setenv("AMC_ZO_MODE", "live")
    monkeypatch.setenv("ZO_API_KEY", "zo_sk_test_only")

    def fake_post(url, *, headers, json, timeout):
        return httpx.Response(200, text="not json", request=httpx.Request("POST", url))

    monkeypatch.setattr(zo.httpx, "post", fake_post)

    with pytest.raises(zo.ZoIntegrationError, match="non-JSON"):
        zo.ask_zo("hello")
