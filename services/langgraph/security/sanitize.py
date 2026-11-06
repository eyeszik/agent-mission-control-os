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
# Scope note: this is the whole of sanitize_input's XSS duty by contract -- it is the
# Python reference for packages/pii/src/sanitize.ts and for the committed parity
# fixture, so removing script *bodies* here would fork the two languages. Broader
# neutralisation (element bodies, handlers, URI schemes, residual-bracket encoding)
# lives in sanitize_text below, which has no TypeScript twin.
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


# Broader XSS coverage for display-bound text: event handlers, dangerous URI
# schemes, script-capable or form-capable elements, and legacy IE/VBScript vectors.
XSS_PATTERNS = [
    re.compile(r"(?is)<script[^>]*>.*?</script>"),
    re.compile(r"(?i)<script[^>]*/>"),
    re.compile(r"""(?i)\s+on\w+\s*=\s*["'][^"']*["']"""),
    re.compile(r"(?i)\s+on\w+\s*=\s*\S+"),
    re.compile(r"(?i)javascript\s*:"),
    re.compile(r"(?i)data\s*:\s*text/html"),
    re.compile(r"(?i)<\s*(iframe|object|embed|form|input|button|select|textarea|meta|link|base|applet)\b[^>]*>"),
    re.compile(r"(?i)</\s*(iframe|object|embed|form|input|button|select|textarea)\s*>"),
    re.compile(r"(?i)<svg[^>]*\bon\w+"),
    re.compile(r"(?i)expression\s*\("),
    re.compile(r"(?i)vbscript\s*:"),
]


def sanitize_text(text: str) -> str:
    """Comprehensive single-string cleaner for text bound for HTML contexts.

    Runs broader than ``sanitize_input`` on purpose: whole ``<script>`` elements
    including their bodies, inline event handlers, dangerous URI schemes,
    script-capable or form-capable elements, then encodes any surviving angle
    brackets so residual markup cannot open a tag. Applied to a fixpoint so nested
    fragments cannot reassemble a vector after one pass, for the same reason
    ``_strip_script_tags`` loops.

    Element-level stripping must run *before* the tag-only pass: once the tags are
    gone there is no longer a complete element for the body-removing pattern to match.

    Deliberately NOT used by ``sanitize_input``, whose output is pinned by the
    cross-language parity fixture (packages/pii/tests/fixtures/pii-parity.json), which
    the TypeScript reference in packages/pii/src/sanitize.ts consumes. Widening
    sanitize_input would fork Python from TS without a matching TS change.
    """
    previous = None
    while previous != text:
        previous = text
        for pattern in XSS_PATTERNS:
            text = pattern.sub("", text)
    text = _clean_string(text)
    return text.replace("<", "&lt;").replace(">", "&gt;")
