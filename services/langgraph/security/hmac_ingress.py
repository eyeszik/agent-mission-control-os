"""Fail-closed HMAC-SHA256 ingress authentication for ASGI applications.

The middleware authenticates the exact raw request bytes before downstream
framework parsing. It is intentionally independent of any database or queue.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Iterable

ASGIApp = object


class HMACVerificationError(ValueError):
    """Raised when a supplied signature cannot be verified."""


class RequestBodyTooLarge(ValueError):
    """Raised when an authenticated ingress body exceeds the configured limit."""


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


def verify_hmac_sha256(*, raw_body: bytes, signature_header: str, secret: bytes) -> bool:
    """Verify HMAC-SHA256 using constant-time comparison.

    ``secret`` must be injected from the repository's existing secret/config
    boundary. This module intentionally does not define or load a credential.
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

    def __post_init__(self) -> None:
        if not self.header_name.strip():
            raise ValueError("header_name is required")
        if not self.secret:
            raise ValueError("secret is required")
        if not self.protected_paths:
            raise ValueError("at least one protected path is required")
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")


class HMACIngressMiddleware:
    """Pure ASGI middleware that rejects unverified protected requests.

    Authentication occurs before FastAPI/Starlette receives the body. On
    missing, malformed, or incorrect signatures it returns HTTP 401 and does
    not call the downstream application.
    """

    def __init__(self, app, config: HMACIngressConfig) -> None:
        self.app = app
        self.config = config
        self._header_key = config.header_name.lower().encode("ascii")
        self._paths = frozenset(config.protected_paths)
        self._methods = frozenset(method.upper() for method in config.protected_methods)

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "").upper()
        if path not in self._paths or method not in self._methods:
            await self.app(scope, receive, send)
            return

        signature = self._get_header(scope.get("headers", ()))
        if signature is None:
            await self._reject_401(send)
            return

        try:
            raw_body = await self._read_body(receive)
        except RequestBodyTooLarge:
            await self._reject_413(send)
            return

        try:
            valid = verify_hmac_sha256(
                raw_body=raw_body,
                signature_header=signature,
                secret=self.config.secret,
            )
        except (HMACVerificationError, UnicodeError):
            valid = False

        if not valid:
            await self._reject_401(send)
            return

        sent = False

        async def replay_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    def _get_header(self, headers: Iterable[tuple[bytes, bytes]]) -> str | None:
        values = [value for key, value in headers if key.lower() == self._header_key]
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

    async def _reject_401(self, send) -> None:
        payload = json.dumps({"detail": "Unauthorized"}, separators=(",", ":")).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"www-authenticate", self.config.challenge_scheme.encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    async def _reject_413(self, send) -> None:
        payload = json.dumps({"detail": "Payload too large"}, separators=(",", ":")).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})
