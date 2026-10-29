"""Regression: credential patterns in security/pii.py use real word boundaries.

The gh*_ and xox patterns once ended in a raw-string ``\\\\b`` (a literal
backslash followed by ``b``), so GitHub tokens were not detected unless that
text followed them, and Slack tokens only by accident. Values are fictional
and built by concatenation so no credential-shaped literal appears in the source.
"""
from __future__ import annotations

import pytest

from services.langgraph.security.pii import _EXTRA_SECRET_PATTERNS, detect_pii, redact_value

GITHUB_TOKEN = "gh" + "p_" + "Q1w2E3r4T5y6U7i8O9p0" + "AbCd"
SLACK_TOKEN = "xo" + "xb-" + "fictional-" + "abcdefghij"


@pytest.mark.parametrize("secret", [GITHUB_TOKEN, SLACK_TOKEN])
def test_credential_is_detected_in_plain_text(secret: str) -> None:
    assert detect_pii(f"deploy log: token={secret} done")
    assert detect_pii(secret)


@pytest.mark.parametrize("secret", [GITHUB_TOKEN, SLACK_TOKEN])
def test_credential_is_redacted_from_nested_payload(secret: str) -> None:
    redacted = redact_value({"log": [f"using {secret}"]})
    assert secret not in repr(redacted)


@pytest.mark.parametrize("text", ["xgh" + "p_" + "a" * 24, "noxo" + "xb-" + "a" * 12])
def test_word_boundaries_still_apply(text: str) -> None:
    assert not any(p.search(text) for p in _EXTRA_SECRET_PATTERNS)
