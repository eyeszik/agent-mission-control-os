import re
from typing import Dict, Any

# Heuristic prompt injection indicators
INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore all previous instructions\b"),
    re.compile(r"(?i)\byou are now\b"),
    re.compile(r"(?i)\bsystem prompt\b"),
    re.compile(r"(?i)\bforget everything\b"),
    re.compile(r"(?i)\bbypass\b.*\bsecurity\b")
]

def sanitize_input(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize input data to prevent prompt injection and XSS using heuristics.
    """
    sanitized = {}
    for k, v in data.items():
        if isinstance(v, str):
            clean_v = v
            for pattern in INJECTION_PATTERNS:
                if pattern.search(clean_v):
                    clean_v = pattern.sub("[MALICIOUS_INTENT_REDACTED]", clean_v)
            # Basic XSS stripping
            clean_v = clean_v.replace("<script>", "").replace("</script>", "")
            sanitized[k] = clean_v
        elif isinstance(v, dict):
            sanitized[k] = sanitize_input(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_input(i) if isinstance(i, dict) else i for i in v
            ]
        else:
            sanitized[k] = v
    return sanitized
