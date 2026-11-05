import re
from typing import Dict, Any

# Heuristic prompt injection indicators (ASI01). Heuristics are a first filter only;
# the RAG path additionally runs agency/project_os/knowledge.py::injection_findings.
INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore all previous instructions\b"),
    re.compile(r"(?i)\byou are now\b"),
    re.compile(r"(?i)\bsystem prompt\b"),
    re.compile(r"(?i)\bforget everything\b"),
    re.compile(r"(?i)\bbypass\b.*\bsecurity\b")
]

# Any script open/close tag, any case, with attributes. Applied until stable so that
# nested fragments such as "<scr<script>ipt>" cannot reassemble a tag after one pass.
_SCRIPT_TAG = re.compile(r"(?i)</?script\b[^>]*>")


def _strip_script_tags(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _SCRIPT_TAG.sub("", text)
    return text


def _clean_string(text: str) -> str:
    for pattern in INJECTION_PATTERNS:
        text = pattern.sub("[MALICIOUS_INTENT_REDACTED]", text)
    return _strip_script_tags(text)


def _clean(value: Any) -> Any:
    """Recursively sanitize every string inside dicts, lists and tuples."""
    if isinstance(value, str):
        return _clean_string(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clean(item) for item in value)
    return value


def sanitize_input(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize input data to prevent prompt injection and XSS using heuristics.

    Walks nested dicts, lists and tuples. Previously, plain strings inside lists were
    passed through unredacted, and script tags were stripped only in lower case.
    """
    return {k: _clean(v) for k, v in data.items()}
