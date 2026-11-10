"""Side-effect-free guardrails for design-system integrations.

These helpers validate URLs, redact selected log patterns, enforce process-local
admission limits, and decide when a human review is required. They do not make
network requests, write durable state, dispatch approvals, or send notifications.
"""

from __future__ import annotations

import ipaddress
import math
import re
import threading
import time
import urllib.parse
from collections import deque
from collections.abc import Callable, Sequence
from typing import TypeGuard

ALLOWED_DOMAINS = frozenset({"api.github.com", "mcp.figma.com", "chromatic.com"})
MAX_CLIENT_CALLS_PER_MINUTE = 5
MAX_WORKSPACE_CALLS_PER_HOUR = 50
VISUAL_ERROR_HITL_THRESHOLD_PCT = 15.0
ACCESSIBILITY_HITL_THRESHOLD_PCT = 95.0
_MAX_DNS_ANSWERS = 64

_HOST_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME_RE = re.compile(
    rf"^(?:{_HOST_LABEL})(?:\.(?:{_HOST_LABEL}))*$",
    re.IGNORECASE,
)
_BEARER_TOKEN_RE = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/-]+=*")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:oauth[_-]?token|access[_-]?token|refresh[_-]?token|token|api[_-]?key|"
    r"client[_-]?secret|password|passwd|secret)\s*[:=]\s*['\"]?)([^'\"\s,;&]+)"
)
_PREFIXED_SECRET_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


class RateLimitExceeded(RuntimeError):
    """An admission was rejected by a configured rate limit."""


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _canonical_hostname(hostname: str) -> str:
    if hostname.endswith(".."):
        raise PermissionError("SSRF protection rejected an invalid hostname")
    value = hostname.removesuffix(".")
    try:
        canonical = value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise PermissionError("SSRF protection rejected an invalid hostname") from exc
    if len(canonical) > 253 or not _HOSTNAME_RE.fullmatch(canonical):
        raise PermissionError("SSRF protection rejected an invalid hostname")
    return canonical


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return (
        getattr(address, "scope_id", None) is None
        and address.is_global
        and (mapped is None or mapped.is_global)
    )


def _validate_resolved_ips(resolved_ips: Sequence[str]) -> None:
    too_many = (
        isinstance(resolved_ips, (str, bytes)) or len(resolved_ips) > _MAX_DNS_ANSWERS
    )
    if too_many:
        raise PermissionError(
            "SSRF protection requires a bounded sequence of resolved IP addresses"
        )
    if not resolved_ips or any(
        not isinstance(address, str) or not _is_public_ip(address)
        for address in resolved_ips
    ):
        raise PermissionError("SSRF protection rejected a non-public DNS result")


def _parse_ssrf_url(
    url_str: str,
) -> tuple[urllib.parse.SplitResult, str, int | None] | None:
    if not isinstance(url_str, str) or not url_str or len(url_str) > 8192:
        return None
    if any(ord(char) <= 0x20 or ord(char) == 0x7F for char in url_str):
        raise PermissionError(
            "SSRF protection rejected control characters or whitespace"
        )
    try:
        parsed = urllib.parse.urlsplit(url_str)
        hostname, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise PermissionError("SSRF protection rejected a malformed URL") from exc
    return (parsed, hostname, port) if parsed.netloc and hostname else None


def _validate_ssrf_target(
    parsed: urllib.parse.SplitResult,
    hostname: str,
    port: int | None,
) -> None:
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise PermissionError("SSRF protection rejected the URL scheme or authority")
    if port not in (None, 443):
        raise PermissionError("SSRF protection rejected a non-HTTPS port")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        canonical = _canonical_hostname(hostname)
    else:
        raise PermissionError("SSRF protection does not allow direct IP targets")
    if canonical not in ALLOWED_DOMAINS:
        raise PermissionError(
            "SSRF protection rejected a host outside the exact allowlist"
        )


def validate_ssrf_domain(
    url_str: str,
    *,
    resolved_ips: Sequence[str] | None = None,
) -> bool:
    """Allow configured HTTPS hosts and optionally validate up to 64 pinned DNS answers.

    This helper performs no DNS lookup and cannot prevent rebinding if a caller
    validates one answer but lets its HTTP transport resolve the host again.
    """
    target = _parse_ssrf_url(url_str)
    if target is None:
        return False
    parsed, hostname, port = target
    _validate_ssrf_target(parsed, hostname, port)
    if resolved_ips is not None:
        _validate_resolved_ips(resolved_ips)
    return True


def sanitize_log_stream(log_text: str) -> str:
    """Redact common email, bearer-token, and credential-assignment patterns."""
    sanitized = _BEARER_TOKEN_RE.sub(r"\1[REDACTED_TOKEN]", log_text)
    sanitized = _SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED_SECRET]", sanitized)
    sanitized = _PREFIXED_SECRET_RE.sub("[REDACTED_SECRET]", sanitized)
    return _EMAIL_RE.sub("[REDACTED_EMAIL]", sanitized)


def _discard_expired(calls: deque[float], now: float, window_seconds: float) -> None:
    cutoff = now - window_seconds
    while calls and calls[0] <= cutoff:
        calls.popleft()


def _validate_rate_limit_config(
    max_client_calls: int,
    client_window_seconds: float,
    max_workspace_calls: int,
    workspace_window_seconds: float,
) -> None:
    counts = (max_client_calls, max_workspace_calls)
    windows = (client_window_seconds, workspace_window_seconds)
    counts_valid = all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in counts
    )
    windows_valid = all(
        _is_finite_number(value) and float(value) > 0 for value in windows
    )
    if not counts_valid or not windows_valid:
        raise ValueError("rate limits and windows must be finite positive values")


class RateLimiter:
    """Thread-safe in-memory sliding-window limiter for one process only."""

    def __init__(
        self,
        *,
        max_client_calls: int = MAX_CLIENT_CALLS_PER_MINUTE,
        client_window_seconds: float = 60.0,
        max_workspace_calls: int = MAX_WORKSPACE_CALLS_PER_HOUR,
        workspace_window_seconds: float = 3600.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        _validate_rate_limit_config(
            max_client_calls,
            client_window_seconds,
            max_workspace_calls,
            workspace_window_seconds,
        )
        self._max_client_calls = max_client_calls
        self._client_window_seconds = client_window_seconds
        self._max_workspace_calls = max_workspace_calls
        self._workspace_window_seconds = workspace_window_seconds
        self._clock = time.monotonic if clock is None else clock
        self._lock = threading.Lock()
        self._client_calls: dict[str, deque[float]] = {}
        self._workspace_calls: deque[float] = deque()

    def _prune(self, now: float) -> None:
        _discard_expired(self._workspace_calls, now, self._workspace_window_seconds)
        expired_clients = []
        for client_id, calls in self._client_calls.items():
            _discard_expired(calls, now, self._client_window_seconds)
            if not calls:
                expired_clients.append(client_id)
        for client_id in expired_clients:
            del self._client_calls[client_id]

    def _admit(self, client_id: str) -> None:
        with self._lock:
            now = self._clock()
            if not _is_finite_number(now):
                raise RuntimeError("rate-limit clock returned an invalid value")
            self._prune(now)
            client_calls = self._client_calls.get(client_id)
            self._check_capacity(client_calls)
            client_calls = self._client_calls.setdefault(client_id, deque())
            client_calls.append(now)
            self._workspace_calls.append(now)

    def _check_capacity(self, client_calls: deque[float] | None) -> None:
        if client_calls is not None and len(client_calls) >= self._max_client_calls:
            raise RateLimitExceeded("client execution rate limit exceeded")
        if len(self._workspace_calls) >= self._max_workspace_calls:
            raise RateLimitExceeded("workspace execution rate limit exceeded")

    def check(self, client_id: str) -> bool:
        if (
            not isinstance(client_id, str)
            or not client_id.strip()
            or client_id != client_id.strip()
            or len(client_id) > 256
        ):
            raise ValueError("client_id must be a non-empty server-derived identifier")
        self._admit(client_id)
        return True


_DEFAULT_RATE_LIMITER = RateLimiter()


def check_rate_limits(client_id: str) -> bool:
    """Admit an execution under the default per-process limits.

    The identifier must come from authenticated server state. Distributed or
    durable deployments need a shared canonical limiter; this in-memory default
    is not a cross-process security boundary.
    """
    return _DEFAULT_RATE_LIMITER.check(client_id)


def _valid_percentage(value: object) -> bool:
    return _is_finite_number(value) and 0.0 <= float(value) <= 100.0


def evaluate_hitl_trigger(
    visual_error_pct: float,
    wcag_score_pct: float,
) -> tuple[bool, str]:
    """Return whether configured design thresholds require a human review.

    Invalid, non-finite, or out-of-range metrics fail closed. The accessibility
    percentage is a project metric, not proof of WCAG conformance. This function
    does not pause a durable run or send a Slack/other notification.
    """
    if not _valid_percentage(visual_error_pct) or not _valid_percentage(wcag_score_pct):
        return (
            True,
            "HITL required: design metrics are missing or invalid; "
            "pause for human review.",
        )
    triggers = []
    if visual_error_pct > VISUAL_ERROR_HITL_THRESHOLD_PCT:
        triggers.append(
            f"visual regression error {visual_error_pct:.1f}% exceeds "
            f"{VISUAL_ERROR_HITL_THRESHOLD_PCT:.0f}%"
        )
    if wcag_score_pct < ACCESSIBILITY_HITL_THRESHOLD_PCT:
        triggers.append(
            f"accessibility score {wcag_score_pct:.1f}% is below "
            f"{ACCESSIBILITY_HITL_THRESHOLD_PCT:.0f}%"
        )
    if triggers:
        return True, "HITL required before delivery: " + "; ".join(triggers)
    return (
        False,
        "Configured design thresholds passed; this does not grant approval "
        "or prove conformance.",
    )
