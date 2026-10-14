import base64
import binascii
import re
from urllib.parse import unquote
from typing import Any, Dict

# Basic regex patterns for PII detection/redaction. These are deliberately
# conservative heuristics, not a substitute for a full data-classification
# service. The important invariant is that every supported nested container
# shape is processed recursively before persistence or model exposure.
PII_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "phone": re.compile(r"\b(?:\+?1[-.●]?)?\(?([0-9]{3})\)?[-.●]?([0-9]{3})[-.●]?([0-9]{4})\b"),
    "ssn": re.compile(r"\b(?!000|666)[0-8][0-9]{2}-(?!00)[0-9]{2}-(?!0000)[0-9]{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "api_key_like": re.compile(r"\b(?:sk|api|key)[-_][A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    "bearer": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*", re.IGNORECASE),
}


_BASE64_FRAGMENT = re.compile(r"(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{24,}={0,2})(?![A-Za-z0-9+/=])")
_EXTRA_SECRET_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\\bxox[abprs]-[A-Za-z0-9-]{10,}\\b"),
)


def _plain_sensitive(text: str) -> bool:
    return (any(pattern.search(text) for pattern in PII_PATTERNS.values())
            or any(pattern.search(text) for pattern in _EXTRA_SECRET_PATTERNS))


def _encoded_sensitive(text: str) -> bool:
    if "%" in text:
        decoded = text
        for _ in range(2):
            new_text = unquote(decoded, errors="replace")
            if new_text == decoded:
                break
            decoded = new_text
            if _plain_sensitive(decoded):
                return True
    for token in _BASE64_FRAGMENT.finditer(text):
        candidate = token.group(0)
        if len(candidate) > 4096:
            continue
        try:
            raw = base64.b64decode(candidate, validate=True)
            decoded = raw.decode("utf-8", errors="ignore")
        except (ValueError, binascii.Error):
            continue
        if _plain_sensitive(decoded):
            return True
    return False


def detect_pii(text: str) -> bool:
    return bool(text) and (_plain_sensitive(text) or _encoded_sensitive(text))


def _redact_string(value: str) -> str:
    if _encoded_sensitive(value):
        return "[REDACTED_ENCODED_SECRET]"
    scrubbed = value
    for name, pattern in PII_PATTERNS.items():
        scrubbed = pattern.sub(f"[REDACTED_{name.upper()}]", scrubbed)
    for pattern in _EXTRA_SECRET_PATTERNS:
        scrubbed = pattern.sub("[REDACTED_SECRET]", scrubbed)
    return scrubbed


_SENSITIVE_KEYS = {"authorization", "proxy_authorization", "x_api_key", "api_key", "access_token", "refresh_token", "password", "secret", "client_secret", "private_key", "raw_prompt"}


def redact_value(value: Any) -> Any:
    """Recursively redact supported sensitive patterns from arbitrary JSON-like values."""

    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return {k: ("[REDACTED_SENSITIVE_FIELD]" if isinstance(k, str) and k.lower().replace("-", "_") in _SENSITIVE_KEYS else redact_value(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def quarantine_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a recursively redacted copy suitable for safe workflow state."""

    return redact_value(payload)
