from services.langgraph.security.pii import redact_value, detect_pii


def test_ace_bearer_tokens_are_redacted_in_nested_payload():
    raw = {
        "nested": [{"headers": {"Authorization": "Bearer abcdefghijklmnopqrstuvwxyz"}},
                   {"note": "Bearer abcdefghijklmnopqrstuvwxyz"}],
        "password": "short",
        "raw_prompt": "operator says secret",
    }
    safe = redact_value(raw)
    assert safe["nested"][0]["headers"]["Authorization"] == "[REDACTED_SENSITIVE_FIELD]"
    assert "abcdefghijklmnopqrstuvwxyz" not in str(safe)
    assert safe["password"] == "[REDACTED_SENSITIVE_FIELD]"
    assert safe["raw_prompt"] == "[REDACTED_SENSITIVE_FIELD]"
    assert detect_pii("Bearer abcdefghijklmnopqrstuvwxyz")


def test_ace_redaction_preserves_nonsensitive_structure():
    value = {"tenant_id": "t-1", "items": [{"status": "ok", "count": 2}]}
    assert redact_value(value) == value
