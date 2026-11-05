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

# Comprehensive XSS patterns to catch various attack vectors
XSS_PATTERNS = [
    # Script tags (various forms)
    re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<script[^>]*/>", re.IGNORECASE),
    # Event handlers in HTML attributes
    re.compile(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', re.IGNORECASE),
    re.compile(r'\s+on\w+\s*=\s*\S+', re.IGNORECASE),
    # JavaScript URIs
    re.compile(r'javascript\s*:', re.IGNORECASE),
    # Data URIs with script content
    re.compile(r'data\s*:\s*text/html', re.IGNORECASE),
    # Dangerous HTML tags
    re.compile(r'<\s*(iframe|object|embed|form|input|button|select|textarea|meta|link|base|applet)\b[^>]*>', re.IGNORECASE),
    re.compile(r'</\s*(iframe|object|embed|form|input|button|select|textarea)\s*>', re.IGNORECASE),
    # SVG with event handlers
    re.compile(r'<svg[^>]*\bon\w+', re.IGNORECASE),
    # Expression() for older IE
    re.compile(r'expression\s*\(', re.IGNORECASE),
    # VBScript
    re.compile(r'vbscript\s*:', re.IGNORECASE),
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
            # Apply comprehensive XSS stripping
            for pattern in XSS_PATTERNS:
                clean_v = pattern.sub("", clean_v)
            # Additional encoding for angle brackets that might slip through
            clean_v = clean_v.replace("<", "&lt;").replace(">", "&gt;")
            sanitized[k] = clean_v
        elif isinstance(v, dict):
            sanitized[k] = sanitize_input(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_input(i) if isinstance(i, dict) 
                else sanitize_text(i) if isinstance(i, str) 
                else i 
                for i in v
            ]
        else:
            sanitized[k] = v
    return sanitized

def sanitize_text(text: str) -> str:
    """
    Sanitize a single text string to prevent XSS.
    """
    clean_v = text
    for pattern in INJECTION_PATTERNS:
        if pattern.search(clean_v):
            clean_v = pattern.sub("[MALICIOUS_INTENT_REDACTED]", clean_v)
    for pattern in XSS_PATTERNS:
        clean_v = pattern.sub("", clean_v)
    clean_v = clean_v.replace("<", "&lt;").replace(">", "&gt;")
    return clean_v
