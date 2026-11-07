"""Fail-closed, side-effect-free design guardrail helpers."""

from .filters import (
    ACCESSIBILITY_HITL_THRESHOLD_PCT,
    ALLOWED_DOMAINS,
    MAX_CLIENT_CALLS_PER_MINUTE,
    MAX_WORKSPACE_CALLS_PER_HOUR,
    VISUAL_ERROR_HITL_THRESHOLD_PCT,
    RateLimiter,
    RateLimitExceeded,
    check_rate_limits,
    evaluate_hitl_trigger,
    sanitize_log_stream,
    validate_ssrf_domain,
)

__all__ = [
    "ACCESSIBILITY_HITL_THRESHOLD_PCT",
    "ALLOWED_DOMAINS",
    "MAX_CLIENT_CALLS_PER_MINUTE",
    "MAX_WORKSPACE_CALLS_PER_HOUR",
    "VISUAL_ERROR_HITL_THRESHOLD_PCT",
    "RateLimitExceeded",
    "RateLimiter",
    "check_rate_limits",
    "evaluate_hitl_trigger",
    "sanitize_log_stream",
    "validate_ssrf_domain",
]
