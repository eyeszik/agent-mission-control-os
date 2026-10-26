import os

# Tests run with an explicit loopback-only server principal. Production auth is
# intentionally not synthesized by the test harness.
os.environ.setdefault("AMC_AUTH_MODE", "local")
os.environ.setdefault("AMC_LOCAL_USER_ID", "test-operator")
os.environ.setdefault("AMC_LOCAL_TENANT_ID", "tenant-events-test")
os.environ.setdefault("AMC_LOCAL_PROJECT_IDS", "*")
# The single test principal both starts and decides runs, which separation of
# duties forbids; the local-only self-approval switch keeps those flows testable.
# tests/test_approval_authority.py exercises the enforced behaviour explicitly.
os.environ.setdefault("AMC_LOCAL_ROLE", "admin")
os.environ.setdefault("AMC_ALLOW_SELF_APPROVAL", "1")
# One tenant creates hundreds of runs across the suite; limits are exercised
# explicitly in tests/test_cost_and_rate_limits.py.
os.environ.setdefault("AMC_MAX_RUNS_PER_TENANT_PER_HOUR", "0")
os.environ.setdefault("AMC_MAX_ACTIVE_RUNS_PER_TENANT", "0")

import httpx  # noqa: E402
import pytest  # noqa: E402

LLM_ENV = ("AMC_LLM_PROVIDER", "AMC_LLM_FALLBACK_PROVIDERS", "AMC_LLM_DISABLED_PROVIDERS", "OPENAI_API_KEY",
           "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "AMC_OPENAI_MODEL", "AMC_ANTHROPIC_MODEL",
           "AMC_GEMINI_MODEL", "AMC_OLLAMA_MODEL")


@pytest.fixture
def provider_http(monkeypatch):
    """Agency generation against a network-free fake provider (see provider_fakes)."""
    from services.langgraph.graph.agency import llm
    from services.langgraph.tests.provider_fakes import FakeProviderHTTP

    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    fake = FakeProviderHTTP()

    def factory(timeout: float) -> httpx.Client:
        fake.timeouts.append(timeout)
        return httpx.Client(transport=httpx.MockTransport(fake.handler), timeout=timeout)

    monkeypatch.setattr(llm, "_http_client", factory)
    return fake
