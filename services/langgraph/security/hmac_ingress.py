"""Fail-closed HMAC-SHA256 ingress authentication with replay protection (OWASP ASI07).

The middleware authenticates the exact raw request bytes before downstream framework parsing.
It is intentionally independent of any database or queue.

Protocol v2 (required; the body-only v1 scheme is refused):

* headers: the configured signature header, ``X-AMC-Timestamp`` (Unix seconds, integer) and
  ``X-AMC-Nonce`` (16-128 characters from ``[A-Za-z0-9_-]``), each exactly once;
* signed material: ``b"AMC-HMAC-V2\\n" + timestamp + b"\\n" + nonce + b"\\n" + body``;
* the timestamp must lie within ``replay_window_seconds`` (default 300) of the server clock;
* a nonce is accepted once. A ``ReplayGuard`` remembers accepted nonces until their timestamp
  leaves the window, and refuses a repeat with HTTP 401.

Order of checks is cheap-to-expensive, and no state is written before authentication succeeds,
so unsigned traffic cannot fill the nonce store. If the store is full of live nonces the request
is refused with HTTP 503 (fail closed).

Scope limits: the nonce store is process-local. Under several workers, each worker only refuses
replays it has seen itself, so a shared store is needed for multi-worker replay protection.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import time
from typing import Iterable

from starlette.concurrency import run_in_threadpool

from services.langgraph.security.replay_store import (
    MAX_NONCES,
    REPLAY_WINDOW_SECONDS,
    DatabaseReplayStore,
    MemoryReplayStore,
    ReplayDetected,
    ReplayGuard,
    ReplayStore,
    ReplayStoreSaturated,
    build_replay_store,
)

ASGIApp = object

# Request-state key set only after a body signature has been verified.
HMAC_VERIFIED_STATE_KEY = "amc_hmac_verified"

TIMESTAMP_HEADER = "x-amc-timestamp"
NONCE_HEADER = "x-amc-nonce"
SIGNING_DOMAIN = b"AMC-HMAC-V2\n"

_TIMESTAMP_RE = re.compile(r"^[0-9]{1,11}$")
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class HMACVerificationError(ValueError):
    """Raised when a supplied signature, timestamp or nonce cannot be accepted."""


class RequestBodyTooLarge(ValueError):
    """Raised when an authenticated ingress body exceeds the configured limit."""


def signed_material(timestamp: str, nonce: str, body: bytes) -> bytes:
    return SIGNING_DOMAIN + timestamp.encode("ascii") + b"\n" + nonce.encode("ascii") + b"\n" + body


def sign_v2(*, body: bytes, timestamp: str, nonce: str, secret: bytes) -> str:
    """Client-side helper. Returns the hex digest to send in the signature header."""
    if not secret:
        raise ValueError("HMAC secret must be configured")
    return hmac.new(secret, signed_material(timestamp, nonce, body), hashlib.sha256).hexdigest()


def _signature_hex(signature_header: str) -> str:
    candidate = signature_header.strip()
    if candidate.lower().startswith("sha256="):
        candidate = candidate[7:]
    if len(candidate) != 64:
        raise HMACVerificationError("invalid signature encoding")
    try:
        bytes.fromhex(candidate)
    except ValueError as exc:
        raise HMACVerificationError("invalid signature encoding") from exc
    return candidate.lower()


def check_timestamp(timestamp: str, *, now: float, window: int = REPLAY_WINDOW_SECONDS) -> int:
    """Return the parsed timestamp if it is well-formed and inside the window, else raise."""
    if not _TIMESTAMP_RE.match(timestamp):
        raise HMACVerificationError("invalid timestamp")
    value = int(timestamp)
    if abs(now - value) > window:
        raise HMACVerificationError("timestamp outside the replay window")
    return value


def verify_v2(*, raw_body: bytes, signature_header: str, timestamp: str, nonce: str, secret: bytes,
              now: float, window: int = REPLAY_WINDOW_SECONDS) -> int:
    """Verify protocol v2. Returns the timestamp on success; raises ``HMACVerificationError``.

    Checks are: nonce shape, timestamp shape and freshness, then a constant-time signature
    comparison. Replay detection is separate, in ``ReplayGuard``, and runs only after this passes.
    """
    if not secret:
        raise ValueError("HMAC secret must be configured")
    if not _NONCE_RE.match(nonce):
        raise HMACVerificationError("invalid nonce")
    value = check_timestamp(timestamp, now=now, window=window)
    supplied = _signature_hex(signature_header)
    expected = hmac.new(secret, signed_material(timestamp, nonce, raw_body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HMACVerificationError("signature mismatch")
    return value


def verify_hmac_sha256(*, raw_body: bytes, signature_header: str, secret: bytes) -> bool:
    """Legacy v1 body-only check. Retained for reference and not used by the middleware.

    v1 has no timestamp or nonce, so a captured request can be replayed indefinitely. The
    middleware refuses v1 requests. Do not use this function to authenticate new traffic.
    """
    if not secret:
        raise ValueError("HMAC secret must be configured")
    supplied = _signature_hex(signature_header)
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


@dataclass(frozen=True, slots=True)
class HMACIngressConfig:
    header_name: str
    secret: bytes
    protected_paths: tuple[str, ...]
    protected_methods: tuple[str, ...] = ("POST",)
    max_body_bytes: int = 1_048_576
    challenge_scheme: str = "HMAC"
    replay_window_seconds: int = REPLAY_WINDOW_SECONDS
    max_nonces: int = MAX_NONCES
    replay_backend: str = "database"

    def __post_init__(self) -> None:
        if not self.header_name.strip():
            raise ValueError("header_name is required")
        if not self.secret:
            raise ValueError("secret is required")
        if not self.protected_paths:
            raise ValueError("at least one protected path is required")
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        if not 1 <= self.replay_window_seconds <= 3600:
            raise ValueError("replay_window_seconds must be between 1 and 3600")
        if self.max_nonces <= 0:
            raise ValueError("max_nonces must be positive")
        if self.replay_backend not in ("database", "memory"):
            raise ValueError("replay_backend must be 'database' or 'memory'")


def _now() -> float:
    return time.time()


class HMACIngressMiddleware:
    """Pure ASGI middleware that rejects unverified protected requests.

    Authentication occurs before FastAPI/Starlette receives the body. On missing, malformed,
    stale, replayed or incorrect signatures it returns HTTP 401 and does not call the downstream
    application. If the replay store is saturated it returns HTTP 503.
    """

    def __init__(self, app, config: HMACIngressConfig) -> None:
        self.app = app
        self.config = config
        self._header_key = config.header_name.lower().encode("ascii")
        self._paths = frozenset(config.protected_paths)
        self._methods = frozenset(method.upper() for method in config.protected_methods)
        self._replay: ReplayStore = build_replay_store(
            config.replay_backend, window=config.replay_window_seconds, max_entries=config.max_nonces)

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "").upper()
        if path not in self._paths or method not in self._methods:
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", ())
        signature = self._get_header(headers, self._header_key)
        timestamp = self._get_header(headers, TIMESTAMP_HEADER.encode("ascii"))
        nonce = self._get_header(headers, NONCE_HEADER.encode("ascii"))
        if signature is None or timestamp is None or nonce is None:
            await self._reject_401(send)
            return

        # Cheap freshness check before reading the body.
        try:
            check_timestamp(timestamp, now=_now(), window=self.config.replay_window_seconds)
        except HMACVerificationError:
            await self._reject_401(send)
            return

        try:
            raw_body = await self._read_body(receive)
        except RequestBodyTooLarge:
            await self._reject_413(send)
            return
        except HMACVerificationError:
            await self._reject_401(send)
            return

        now = _now()
        try:
            ts_value = verify_v2(
                raw_body=raw_body,
                signature_header=signature,
                timestamp=timestamp,
                nonce=nonce,
                secret=self.config.secret,
                now=now,
                window=self.config.replay_window_seconds,
            )
        except (HMACVerificationError, UnicodeError):
            await self._reject_401(send)
            return

        # Only an authenticated request may write to the replay store.
        try:
            await run_in_threadpool(self._replay.check_and_record, nonce, timestamp=ts_value, now=now)
        except ReplayDetected:
            await self._reject_401(send)
            return
        except ReplayStoreSaturated:
            await self._reject_503(send)
            return

        # Tell the route layer this request's body was authenticated here, so
        # protected routes can fall back to principal auth when it was not.
        scope.setdefault("state", {})[HMAC_VERIFIED_STATE_KEY] = True

        sent = False

        async def replay_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    @staticmethod
    def _get_header(headers: Iterable[tuple[bytes, bytes]], key: bytes) -> str | None:
        values = [value for k, value in headers if k.lower() == key]
        if len(values) != 1:
            return None
        try:
            return values[0].decode("ascii")
        except UnicodeDecodeError:
            return None

    async def _read_body(self, receive) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                raise HMACVerificationError("client disconnected before authentication")
            if message.get("type") != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.config.max_body_bytes:
                raise RequestBodyTooLarge
            chunks.append(chunk)
            if not message.get("more_body", False):
                return b"".join(chunks)

    async def _reject(self, send, status: int, detail: str, extra: list[tuple[bytes, bytes]]) -> None:
        payload = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
                *extra,
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": payload})

    async def _reject_401(self, send) -> None:
        await self._reject(send, 401, "Unauthorized",
                           [(b"www-authenticate", self.config.challenge_scheme.encode("ascii"))])

    async def _reject_413(self, send) -> None:
        await self._reject(send, 413, "Payload too large", [])

    async def _reject_503(self, send) -> None:
        await self._reject(send, 503, "Service unavailable", [(b"retry-after", b"30")])


__all__ = [
    "DatabaseReplayStore", "HMAC_VERIFIED_STATE_KEY", "HMACIngressConfig", "HMACIngressMiddleware",
    "HMACVerificationError", "MemoryReplayStore", "NONCE_HEADER", "ReplayDetected", "ReplayGuard",
    "ReplayStoreSaturated", "RequestBodyTooLarge",
    "TIMESTAMP_HEADER", "check_timestamp", "sign_v2", "signed_material", "verify_v2",
]
