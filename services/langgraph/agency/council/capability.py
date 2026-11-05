"""Per-call capability tokens for agent-to-tool calls (OWASP ASI03).

Seats hold standing scopes. The gateway turns each admitted call into a short-lived, single-use
capability that is bound to one tool, one exact argument set, and the scopes that call needs:

* signed with Ed25519 (JWS compact form, ``alg=EdDSA``). Only the gateway holds the private key.
  A tool server verifies with the public key alone, so it cannot mint or extend a capability;
* ``aud`` is the tool id, ``args_sha256`` is the canonical hash of the exact arguments (AMC-CANON-1),
  and ``scopes`` is the set the call needs. A capability for other arguments or another tool fails;
* lifetime is at most ``MAX_TTL_S`` seconds, with ``LEEWAY_S`` of clock skew allowed;
* each ``jti`` is accepted once by a verifier. ``JTIRegistry`` is bounded and process-local.

Scope: the gateway also verifies the capability it just minted before dispatch, and records the
``jti`` in the result. The MCP path forwards the token in request metadata (``amc_capability``).
Verification by an external server is only as strong as that server's own ``jti`` handling. This
module supplies the verifier, and the test fixture shows its use.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from services.langgraph.agency.execution.canonical import canonical_hash

ISSUER = "amc-council-gateway"
DEFAULT_TTL_S = 60
MAX_TTL_S = 120
LEEWAY_S = 5
METADATA_KEY = "amc_capability"
_JTI_MAX = 10_000


class CapabilityError(ValueError):
    """The token is malformed, unsigned, expired, replayed, or not valid for this call."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise CapabilityError("TOKEN_MALFORMED", "bad base64url segment") from exc


def _json(data: dict) -> bytes:
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")


class CapabilityIssuer:
    """Holds the signing key. Created once per process, or loaded from ``AMC_CAPABILITY_SIGNING_KEY_FILE``."""

    def __init__(self, private_key: Ed25519PrivateKey | None = None) -> None:
        self._key = private_key or Ed25519PrivateKey.generate()

    @classmethod
    def from_environment(cls) -> "CapabilityIssuer":
        path = (os.environ.get("AMC_CAPABILITY_SIGNING_KEY_FILE") or "").strip()
        if not path:
            return cls()  # ephemeral: tokens die with the process, which bounds their use anyway
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise CapabilityError("KEY_INVALID", "capability signing key must be Ed25519")
        return cls(key)

    def public_key(self) -> Ed25519PublicKey:
        return self._key.public_key()

    def public_key_pem(self) -> bytes:
        return self.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo)

    def mint(self, *, tool_id: str, seat: str, scopes: frozenset[str], args: dict, ctx: dict,
             ttl_s: int = DEFAULT_TTL_S, now: float | None = None) -> str:
        if not 1 <= ttl_s <= MAX_TTL_S:
            raise CapabilityError("TTL_INVALID", f"ttl must be between 1 and {MAX_TTL_S} seconds")
        issued = int(time.time() if now is None else now)
        header = {"alg": "EdDSA", "typ": "amc-cap+jwt"}
        claims = {
            "iss": ISSUER, "aud": tool_id, "sub": seat,
            "tenant_id": ctx.get("tenant_id"), "project_id": ctx.get("project_id"),
            "mission_id": ctx.get("mission_id") or "-",
            "scopes": sorted(scopes), "args_sha256": canonical_hash(args),
            "iat": issued, "exp": issued + ttl_s, "jti": uuid.uuid4().hex,
        }
        signing_input = _b64(_json(header)) + "." + _b64(_json(claims))
        signature = self._key.sign(signing_input.encode("ascii"))
        return signing_input + "." + _b64(signature)


class JTIRegistry:
    """Accepts each ``jti`` once within its lifetime. Bounded: refuses new tokens when full (fail closed)."""

    def __init__(self, max_entries: int = _JTI_MAX) -> None:
        self._max = max_entries
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()

    def accept(self, jti: str, exp: int, now: float) -> None:
        with self._lock:
            for key in [k for k, e in self._seen.items() if e < now]:
                del self._seen[key]
            if jti in self._seen:
                raise CapabilityError("TOKEN_REPLAYED", "this capability was already used")
            if len(self._seen) >= self._max:
                raise CapabilityError("VERIFIER_SATURATED", "too many live capabilities to record another")
            self._seen[jti] = exp


def verify(token: str, *, public_key: Ed25519PublicKey, tool_id: str, args: dict,
           required_scopes: frozenset[str], registry: JTIRegistry | None = None,
           now: float | None = None) -> dict:
    """Return the verified claims, or raise ``CapabilityError``. Signature is checked before any claim is trusted."""
    parts = token.split(".") if isinstance(token, str) else []
    if len(parts) != 3:
        raise CapabilityError("TOKEN_MALFORMED", "expected three segments")
    try:
        header = json.loads(_unb64(parts[0]))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CapabilityError("TOKEN_MALFORMED", "header is not JSON") from exc
    if not isinstance(header, dict) or header.get("alg") != "EdDSA":
        raise CapabilityError("ALG_REJECTED", "only EdDSA capabilities are accepted")
    try:
        public_key.verify(_unb64(parts[2]), f"{parts[0]}.{parts[1]}".encode("ascii"))
    except (InvalidSignature, UnicodeEncodeError) as exc:
        raise CapabilityError("SIGNATURE_INVALID", "signature does not verify") from exc
    try:
        claims = json.loads(_unb64(parts[1]))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CapabilityError("TOKEN_MALFORMED", "claims are not JSON") from exc
    if not isinstance(claims, dict):
        raise CapabilityError("TOKEN_MALFORMED", "claims must be an object")
    current = time.time() if now is None else now
    if claims.get("iss") != ISSUER:
        raise CapabilityError("ISSUER_REJECTED", "unexpected issuer")
    if claims.get("aud") != tool_id:
        raise CapabilityError("AUDIENCE_MISMATCH", "capability was issued for another tool")
    if claims.get("args_sha256") != canonical_hash(args):
        raise CapabilityError("ARGS_MISMATCH", "capability was issued for different arguments")
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, int) or not isinstance(iat, int):
        raise CapabilityError("TOKEN_MALFORMED", "iat and exp must be integers")
    if exp - iat > MAX_TTL_S or exp - iat < 1:
        raise CapabilityError("TTL_INVALID", "lifetime outside the allowed range")
    if current > exp + LEEWAY_S:
        raise CapabilityError("TOKEN_EXPIRED", "capability has expired")
    if iat > current + LEEWAY_S:
        raise CapabilityError("TOKEN_NOT_YET_VALID", "capability issued in the future")
    granted = set(claims.get("scopes") or [])
    if not set(required_scopes) <= granted:
        raise CapabilityError("SCOPE_INSUFFICIENT", f"missing {sorted(set(required_scopes) - granted)}")
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti:
        raise CapabilityError("TOKEN_MALFORMED", "jti is required")
    if registry is not None:
        registry.accept(jti, exp, current)
    return claims


_ISSUER: CapabilityIssuer | None = None
_ISSUER_LOCK = threading.Lock()


def default_issuer() -> CapabilityIssuer:
    global _ISSUER
    with _ISSUER_LOCK:
        if _ISSUER is None:
            _ISSUER = CapabilityIssuer.from_environment()
        return _ISSUER


def reset_default_issuer() -> None:
    """Test hook: discard the process issuer so the next call builds a fresh one."""
    global _ISSUER
    with _ISSUER_LOCK:
        _ISSUER = None


__all__ = ["CapabilityError", "CapabilityIssuer", "JTIRegistry", "METADATA_KEY", "default_issuer", "verify"]
