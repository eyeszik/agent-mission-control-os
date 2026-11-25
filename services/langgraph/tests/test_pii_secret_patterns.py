"""Regression: credential patterns in security/pii.py use real word boundaries.

The gh*_ pattern once ended in a raw-string ``\\\\b`` (a literal backslash
followed by ``b``), so GitHub tokens were not detected unless that text
followed them. Values are fictional and built by concatenation so no
credential-shaped literal appears in the source.
"""
from __future__ import annotations

import pytest

from services.langgraph.security.pii import _EXTRA_SECRET_PATTERNS, PII_PATTERNS, detect_pii, redact_value

GITHUB_TOKEN = "gh" + "p_" + "Q1w2E3r4T5y6U7i8O9p0" + "AbCd"


@pytest.mark.parametrize("secret", [GITHUB_TOKEN])
def test_credential_is_detected_in_plain_text(secret: str) -> None:
    assert detect_pii(f"deploy log: token={secret} done")
    assert detect_pii(secret)


@pytest.mark.parametrize("secret", [GITHUB_TOKEN])
def test_credential_is_redacted_from_nested_payload(secret: str) -> None:
    redacted = redact_value({"log": [f"using {secret}"]})
    assert secret not in repr(redacted)


@pytest.mark.parametrize("text", ["xgh" + "p_" + "a" * 24])
def test_word_boundaries_still_apply(text: str) -> None:
    assert not any(p.search(text) for p in _EXTRA_SECRET_PATTERNS)


# --- C14 hardening (docs/evidence/mcp-integration-2026-11/pii_benchmark_c14.json) ---------------
# Gaps a local detector benchmark found in this module. Values are fictional and low-entropy.

AWS_KEY_ID = "AK" + "IA" + "0" * 16
GOOGLE_KEY = "AI" + "za" + "0" * 35

NEWLY_COVERED = {
    "uk phone": ("UK office: +44 20 7946 0958.", "+44 20 7946 0958", "[REDACTED_PHONE_INTL]"),
    "india phone": ("India desk +91 98765 43210 is open.", "+91 98765 43210", "[REDACTED_PHONE_INTL]"),
    "ipv4": ("Origin 203.0.113.42 was blocked.", "203.0.113.42", "[REDACTED_IPV4]"),
    "aws key id": (f"aws_access_key_id = {AWS_KEY_ID}", AWS_KEY_ID, "[REDACTED_AWS_ACCESS_KEY]"),
    "google key": (f"maps key {GOOGLE_KEY}", GOOGLE_KEY, "[REDACTED_GOOGLE_API_KEY]"),
}


@pytest.mark.parametrize("text, secret, label", NEWLY_COVERED.values(), ids=list(NEWLY_COVERED))
def test_c14_gaps_are_detected_and_redacted(text: str, secret: str, label: str) -> None:
    assert detect_pii(text)
    redacted = redact_value({"note": text})["note"]
    assert secret not in redacted and label in redacted


@pytest.mark.parametrize("text", [
    "Release v1.2.3 and build 2026.11.24.1 are ready.",  # versions are not addresses
    "256.1.1.1 is not an address", "1.2.3", "v1.2.3.4",
    "+12 is a score", "x+44 20 7946 0958",  # too short, glued to a word
    "AK" + "IA" + "0" * 15, "x" + AWS_KEY_ID, "AI" + "za" + "0" * 34,
])
def test_c14_near_misses_are_not_flagged(text: str) -> None:
    assert not detect_pii(text)


@pytest.mark.parametrize("text, secret", [
    ("card 4111 1111 1111 1111", "4111 1111 1111 1111"),
    ("account 123456789012345", "123456789012345"),  # not a card, still redacted: fail closed
    ("ISBN 978-3-16-148410-0", "978-3-16-148410-0"),  # accepted false positive, see pii.py
])
def test_existing_number_redaction_is_not_weakened(text: str, secret: str) -> None:
    assert secret not in redact_value(text)


def test_international_phone_respects_the_e164_length_limit() -> None:
    # 17 digits is longer than E.164 allows; the card pattern may still flag the digits, which is fine.
    assert PII_PATTERNS["phone_intl"].search("+44 1234567890123456") is None
    assert PII_PATTERNS["phone_intl"].search("+44 123456789012") is not None
