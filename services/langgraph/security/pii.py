import re
from typing import Dict, Any

# Basic regex patterns for PII detection
PII_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "phone": re.compile(r"\b(?:\+?1[-.●]?)?\(?([0-9]{3})\)?[-.●]?([0-9]{3})[-.●]?([0-9]{4})\b"),
    "ssn": re.compile(r"\b(?!000|666)[0-8][0-9]{2}-(?!00)[0-9]{2}-(?!0000)[0-9]{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b")
}

def detect_pii(text: str) -> bool:
    """
    Detect raw PII in text using regex heuristics.
    Returns True if PII is detected.
    """
    if not text:
        return False
    
    for pattern in PII_PATTERNS.values():
        if pattern.search(text):
            return True
    return False

def quarantine_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scrub PII from payload before it enters the workflow state.
    """
    quarantined = {}
    for k, v in payload.items():
        if isinstance(v, str):
            scrubbed_val = v
            for p_name, pattern in PII_PATTERNS.items():
                scrubbed_val = pattern.sub(f"[REDACTED_{p_name.upper()}]", scrubbed_val)
            quarantined[k] = scrubbed_val
        elif isinstance(v, dict):
            quarantined[k] = quarantine_payload(v)
        elif isinstance(v, list):
            quarantined[k] = [
                quarantine_payload(i) if isinstance(i, dict) else 
                (PII_PATTERNS["email"].sub("[REDACTED]", i) if isinstance(i, str) else i)
                for i in v
            ]
        else:
            quarantined[k] = v
    return quarantined
