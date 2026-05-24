def detect_pii(text: str) -> bool:
    """
    Scaffold: Detect raw PII in text.
    Returns True if PII is detected.
    """
    # [VOID_DETECTED] Real PII model/regex not yet implemented
    return False

def quarantine_payload(payload: dict) -> dict:
    """
    Scaffold: Scrub PII from payload before it enters the workflow state.
    """
    return payload
