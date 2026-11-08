"""Design guardrail helpers are pure local checks; they perform no remote actions."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from services.langgraph.agency.design.guardrails import filters


@pytest.mark.parametrize(
    "url",
    [
        "https://api.github.com",
        "https://mcp.figma.com/v1/tools",
        "https://chromatic.com:443/",
        "https://API.GITHUB.COM./",
    ],
)
def test_ssrf_allows_only_canonical_https_allowlist_hosts(url: str):
    assert filters.validate_ssrf_domain(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com",
        "https://api.github.com:8443",
        "https://api.github.com.evil.example",
        "https://evil-api.github.com",
        "https://user:password@api.github.com",
        "https://127.0.0.1",
        "https://10.1.2.3",
        "https://172.20.0.1",
        "https://192.168.1.1",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
        "\nhttps://api.github.com",
    ],
)
def test_ssrf_rejects_unsafe_or_non_allowlisted_targets(url: str):
    with pytest.raises(PermissionError):
        filters.validate_ssrf_domain(url)


def test_ssrf_returns_false_for_missing_authority_and_rejects_malformed_url():
    assert filters.validate_ssrf_domain("") is False
    assert filters.validate_ssrf_domain("https:///missing-host") is False
    with pytest.raises(PermissionError):
        filters.validate_ssrf_domain("https://[broken")


def test_ssrf_checks_all_resolved_addresses_without_performing_dns():
    assert filters.validate_ssrf_domain(
        "https://api.github.com", resolved_ips=("1.1.1.1", "8.8.8.8")
    )
    for address in (
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "172.31.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
    ):
        with pytest.raises(PermissionError):
            filters.validate_ssrf_domain(
                "https://api.github.com", resolved_ips=("1.1.1.1", address)
            )
    with pytest.raises(PermissionError):
        filters.validate_ssrf_domain("https://api.github.com", resolved_ips=())
    with pytest.raises(PermissionError):
        filters.validate_ssrf_domain(
            "https://api.github.com", resolved_ips=("1.1.1.1",) * 65
        )


def test_log_sanitizer_redacts_email_oauth_bearer_and_key_patterns():
    bearer = "Bearer " + "token-value_123"
    oauth = "oauth_token=" + "oauth-secret-value"
    api_key = "api_key=" + "api-secret-value"
    token = "token=" + "assigned-token-value"
    openai_key = "sk-" + "A" * 24
    github_key = "ghp_" + "B" * 36
    source = (
        f"contact person@example.com {bearer} {oauth} "
        f"{api_key} {token} {openai_key} {github_key}"
    )
    sanitized = filters.sanitize_log_stream(source)
    assert "person@example.com" not in sanitized
    assert "token-value_123" not in sanitized
    assert "oauth-secret-value" not in sanitized
    assert "api-secret-value" not in sanitized
    assert "assigned-token-value" not in sanitized
    assert openai_key not in sanitized
    assert github_key not in sanitized
    assert "[REDACTED_EMAIL]" in sanitized
    assert "[REDACTED_TOKEN]" in sanitized
    assert sanitized.count("[REDACTED_SECRET]") == 5


def test_log_sanitizer_preserves_non_sensitive_text():
    assert filters.sanitize_log_stream("run=42 status=passed") == "run=42 status=passed"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_client_window_admits_five_calls_then_expires():
    clock = FakeClock()
    limiter = filters.RateLimiter(clock=clock)
    assert all(limiter.check("authenticated-client") for _ in range(5))
    with pytest.raises(filters.RateLimitExceeded, match="client execution"):
        limiter.check("authenticated-client")
    clock.advance(60.0)
    assert limiter.check("authenticated-client") is True


def test_workspace_window_caps_admissions_across_clients():
    clock = FakeClock()
    limiter = filters.RateLimiter(max_workspace_calls=2, clock=clock)
    assert limiter.check("client-a")
    assert limiter.check("client-b")
    with pytest.raises(filters.RateLimitExceeded, match="workspace execution"):
        limiter.check("client-c")
    clock.advance(3600.0)
    assert limiter.check("client-c")


def test_workspace_rejection_does_not_consume_client_quota():
    clock = FakeClock()
    limiter = filters.RateLimiter(
        max_client_calls=1,
        client_window_seconds=7200,
        max_workspace_calls=1,
        clock=clock,
    )
    assert limiter.check("client-a")
    with pytest.raises(filters.RateLimitExceeded):
        limiter.check("client-b")
    clock.advance(3600.0)
    assert limiter.check("client-b")


def test_rate_limiter_fails_closed_when_clock_is_invalid():
    limiter = filters.RateLimiter(clock=lambda: float("nan"))
    with pytest.raises(RuntimeError, match="clock"):
        limiter.check("authenticated-client")


def test_rate_limiter_is_atomic_under_concurrent_calls():
    limiter = filters.RateLimiter()

    def attempt() -> bool:
        try:
            return limiter.check("one-client")
        except filters.RateLimitExceeded:
            return False

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: attempt(), range(100)))
    assert sum(results) == 5


def test_rate_limiter_requires_nonempty_server_derived_identity():
    limiter = filters.RateLimiter()
    for client_id in ("", "   ", " padded ", "x" * 257, None):
        with pytest.raises(ValueError):
            limiter.check(client_id)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "config",
    [
        {"max_client_calls": 0},
        {"workspace_window_seconds": float("inf")},
        {"client_window_seconds": 10**1000},
    ],
)
def test_rate_limiter_rejects_invalid_configuration(config: dict[str, object]):
    with pytest.raises(ValueError):
        filters.RateLimiter(**config)  # type: ignore[arg-type]


def test_module_rate_limit_wrapper_uses_replaceable_process_local_limiter(
    monkeypatch: pytest.MonkeyPatch,
):
    limiter = filters.RateLimiter(max_client_calls=1)
    monkeypatch.setattr(filters, "_DEFAULT_RATE_LIMITER", limiter)
    assert filters.check_rate_limits("authenticated-client") is True
    with pytest.raises(filters.RateLimitExceeded):
        filters.check_rate_limits("authenticated-client")


def test_hitl_triggers_only_beyond_configured_boundaries():
    assert filters.evaluate_hitl_trigger(15.0, 95.0)[0] is False
    visual_trigger, visual_message = filters.evaluate_hitl_trigger(15.01, 95.0)
    assert visual_trigger is True
    assert "visual regression" in visual_message
    accessibility_trigger, accessibility_message = filters.evaluate_hitl_trigger(
        15.0, 94.99
    )
    assert accessibility_trigger is True
    assert "accessibility score" in accessibility_message


@pytest.mark.parametrize(
    ("visual_error", "accessibility_score"),
    [
        (float("nan"), 99.0),
        (float("inf"), 99.0),
        (-0.1, 99.0),
        (10.0, 100.1),
        (10**1000, 99.0),
        (True, 99.0),
        (None, 99.0),
    ],
)
def test_hitl_invalid_metrics_fail_closed(
    visual_error: object, accessibility_score: object
):
    triggered, message = filters.evaluate_hitl_trigger(
        visual_error, accessibility_score
    )  # type: ignore[arg-type]
    assert triggered is True
    assert "invalid" in message
    assert "Slack" not in message
