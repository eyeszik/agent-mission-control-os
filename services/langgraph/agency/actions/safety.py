"""Input safety for actions. Pure: no network, no DNS.

* SSRF: a URL must be https on the default port, carry no credentials, and name
  a public DNS host. IP literals, loopback, link-local, private, metadata and
  single-label hosts are refused before any adapter sees them.
* Targets: a sandbox target path is normalised and refused if it climbs out
  (``..``), contains control characters or is absolute in the wrong place.
* Secrets: a payload that carries a secret-shaped string is refused outright
  (I16), because storing it would leak it into the evidence trail. Percent-encoded
  and base64-encoded forms are decoded and checked too, so encoding a credential
  does not smuggle it into storage (ACE v100 edge case 8).
* Untrusted text: every string is scanned for injection markers. Flags are
  recorded as evidence and never change risk, scope or authority (I18).
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from services.langgraph.agency.compiled.role_sources import scan_for_injection
from services.langgraph.security.pii import redact_value

_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".intranet", ".lan", ".home.arpa", ".corp")
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata", "instance-data"}
_SECRET = re.compile(
    r"(?i)(?:\b(?:sk|pk|rk)-[a-z0-9_-]{16,}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bghp_[a-z0-9]{30,}\b|\b(?:api|secret|token|password)[_-]?key?\s*[:=]\s*\S{8,}|"
    r"\bbearer\s+[a-z0-9._~+/-]{16,}=*)"
)
_BASE64_FRAGMENT = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{24,4096}={0,2}(?![A-Za-z0-9+/=])")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class UnsafeInput(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def check_public_url(url: str) -> str:
    """Return the normalised URL or raise UnsafeInput (SSRF_*)."""
    if not isinstance(url, str) or len(url) > 2048 or _CONTROL.search(url):
        raise UnsafeInput("SSRF_MALFORMED_URL")
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise UnsafeInput("SSRF_SCHEME", "only https is allowed")
    if parts.username or parts.password or "@" in parts.netloc:
        raise UnsafeInput("SSRF_CREDENTIALS_IN_URL")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeInput("SSRF_MALFORMED_URL", str(exc)) from exc
    if port not in (None, 443):
        raise UnsafeInput("SSRF_PORT", "only the default https port is allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeInput("SSRF_NO_HOST")
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise UnsafeInput("SSRF_IP_LITERAL", "address literals are refused; name a public host")
    except ValueError:
        pass
    if host.isdigit() or re.fullmatch(r"0x[0-9a-f]+", host):
        raise UnsafeInput("SSRF_IP_LITERAL", "numeric host encodings are refused")
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise UnsafeInput("SSRF_INTERNAL_HOST", host)
    if not _HOST.match(host):
        raise UnsafeInput("SSRF_HOST_NOT_PUBLIC_DNS", host)
    return parts._replace(netloc=host, fragment="").geturl()


def safe_relative_path(path: str) -> str:
    if not isinstance(path, str) or not path or len(path) > 512 or _CONTROL.search(path) or "\\" in path:
        raise UnsafeInput("UNSAFE_PATH")
    if not path.startswith("/"):
        raise UnsafeInput("UNSAFE_PATH", "must start with /")
    segments = [s for s in path.split("/") if s]
    if any(s in {".", ".."} for s in segments):
        raise UnsafeInput("PATH_TRAVERSAL")
    if any(not re.fullmatch(r"[A-Za-z0-9._~-]+", s) for s in segments):
        raise UnsafeInput("UNSAFE_PATH", "segments may only use unreserved characters")
    return "/" + "/".join(segments)


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _decoded(text: str) -> Iterable[str]:
    """The text, then its percent-decoded forms (two rounds) and decoded base64 fragments."""
    yield text
    current = text
    for _ in range(2):
        if "%" not in current:
            break
        decoded = unquote(current, errors="replace")
        if decoded == current:
            break
        current = decoded
        yield current
    for fragment in _BASE64_FRAGMENT.findall(text):
        try:
            yield base64.b64decode(fragment, validate=True).decode("utf-8", errors="ignore")
        except (ValueError, binascii.Error):
            continue


def assert_no_secrets(value: Any) -> None:
    for text in _strings(value):
        if any(_SECRET.search(form) for form in _decoded(text)):
            raise UnsafeInput("SECRET_IN_PAYLOAD", "secrets must be referenced from protected storage, never sent in a payload")


def injection_flags(value: Any) -> tuple[str, ...]:
    return tuple(sorted({flag for text in _strings(value) for flag in scan_for_injection(text)}))


def redacted(value: Any) -> Any:
    """Redacted copy for views, logs and evidence. Raw args stay in protected storage."""
    return redact_value(value)


__all__ = ["UnsafeInput", "assert_no_secrets", "check_public_url", "injection_flags", "redacted", "safe_relative_path"]
