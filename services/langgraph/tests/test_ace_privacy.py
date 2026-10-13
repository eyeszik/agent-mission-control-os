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


def test_ace_multiple_credential_encodings_redact_without_leaking():
    import base64
    from urllib.parse import quote
    raw = "Bearer abcdefghijklmnopqrstuvwxyz"
    examples = (
        quote(raw, safe=""),
        quote(quote(raw, safe=""), safe=""),
        base64.b64encode(raw.encode()).decode(),
        "Authorization:\\n" + raw,
    )
    for example in examples:
        assert detect_pii(example), example[:10]
        scrubbed = redact_value({"event": {"message": example}})["event"]["message"]
        assert "abcdefghijklmnopqrstuvwxyz" not in scrubbed
        assert "[REDACTED" in scrubbed


def test_ace_secret_key_names_are_dropped_before_persistence():
    unsafe = {"tenant_id": "t-1", "Authorization": "not-otherwise-detectable",
              "X-API-KEY": "shortvalue",
              "nested": {"proxy-authorization": "also-short"}}
    safe = redact_value(unsafe)
    assert safe["tenant_id"] == "t-1"
    assert safe["Authorization"] == "[REDACTED_SENSITIVE_FIELD]"
    assert safe["X-API-KEY"] == "[REDACTED_SENSITIVE_FIELD]"
    assert safe["nested"]["proxy-authorization"] == "[REDACTED_SENSITIVE_FIELD]"
