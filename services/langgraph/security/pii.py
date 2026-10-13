import re
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
    "bearer": re.compile(r"\\bBearer\\s+[A-Za-z0-9._~+/-]{12,}=*", re.IGNORECASE),
}


def detect_pii(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in PII_PATTERNS.values())


def _redact_string(value: str) -> str:
    scrubbed = value
    for name, pattern in PII_PATTERNS.items():
        scrubbed = pattern.sub(f"[REDACTED_{name.upper()}]", scrubbed)
    return scrubbed


_SENSITIVE_KEYS = {"authorization", "api_key", "access_token", "refresh_token", "password", "secret", "client_secret", "private_key", "raw_prompt"}


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
