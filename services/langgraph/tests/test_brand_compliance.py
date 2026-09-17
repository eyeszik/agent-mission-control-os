"""Tests for the machine-checkable brand compliance rule engine."""

from __future__ import annotations

from services.langgraph.quality.brand_safety import (
    READABILITY_GRADE_MAX,
    READABILITY_GRADE_MIN,
    SENTIMENT_MAX,
    evaluate_brand_compliance,
    flesch_kincaid_grade,
    sentiment_polarity,
)


def _ids(result) -> set[str]:
    return {item["pattern_id"] for item in result["violations"]}


def test_clean_copy_passes():
    result = evaluate_brand_compliance("Our team helps small shops plan a seasonal campaign.")
    assert result["passed"] is True
    assert result["violations"] == []
    assert result["flagged_terms"] == []


def test_flags_unqualified_guarantee():
    result = evaluate_brand_compliance("This plan is guaranteed to double your revenue.")
    assert result["passed"] is False
    assert "guaranteed_outcome" in _ids(result)


def test_negated_guarantee_is_a_disclaimer_not_a_violation():
    result = evaluate_brand_compliance("Individual results vary and are not guaranteed.")
    assert result["passed"] is True
    assert _ids(result) == set()


def test_negated_clinical_claim_is_a_disclaimer():
    result = evaluate_brand_compliance("This supplement is not clinically proven to treat illness.")
    assert result["passed"] is True


def test_no_side_effects_still_flags_despite_leading_negator():
    result = evaluate_brand_compliance("Completely safe with no side effects.")
    assert result["passed"] is False
    assert "no_side_effects" in _ids(result)


def test_risk_free_variants_flag():
    for text in ("Try it risk-free today.", "A totally risk free trial."):
        result = evaluate_brand_compliance(text)
        assert result["passed"] is False, text
        assert "risk_free" in _ids(result), text


def test_substring_does_not_false_positive_on_word_boundary():
    # "secure" contains "cure" but is not a medical cure claim.
    result = evaluate_brand_compliance("Our secure checkout protects every transaction.")
    assert "medical_cure" not in _ids(result)


def test_multiple_distinct_violations_are_each_reported():
    result = evaluate_brand_compliance("A miracle cure that is risk-free and FDA-approved.")
    assert {"miracle", "medical_cure", "risk_free", "regulatory_approval"} <= _ids(result)


def test_violation_records_matched_text_and_description():
    result = evaluate_brand_compliance("This is a miracle product.")
    violation = next(item for item in result["violations"] if item["pattern_id"] == "miracle")
    assert violation["matched_text"].lower() == "miracle"
    assert violation["description"]


def test_flagged_terms_are_normalized_and_deduplicated():
    result = evaluate_brand_compliance("Guaranteed savings. GUARANTEED delivery. A miracle.")
    assert result["flagged_terms"] == ["guaranteed", "miracle"]
    # Each occurrence is still recorded individually, with its original casing.
    guarantee_matches = [
        item["matched_text"]
        for item in result["violations"]
        if item["pattern_id"] == "guaranteed_outcome"
    ]
    assert guarantee_matches == ["Guaranteed", "GUARANTEED"]


def test_missing_disclaimer_is_advisory_not_a_failure():
    result = evaluate_brand_compliance(
        "Join the seasonal programme today and start planning your next campaign.",
        required_disclaimers=("terms_apply_ref",),
    )
    assert result["passed"] is True
    assert result["missing_disclaimers"] == ["terms_apply_ref"]
    assert any("terms_apply_ref" in note for note in result["advisories"])


def test_present_disclaimer_is_not_reported_missing():
    result = evaluate_brand_compliance(
        "Join the seasonal programme today. Terms and conditions apply.",
        required_disclaimers=("terms_apply_ref",),
    )
    assert result["missing_disclaimers"] == []


def test_unknown_disclaimer_rule_is_surfaced_not_silently_ignored():
    result = evaluate_brand_compliance(
        "Some copy here.",
        required_disclaimers=("not_a_real_rule",),
    )
    assert result["missing_disclaimers"] == []
    assert any("not_a_real_rule" in note for note in result["advisories"])


def test_short_text_readability_is_not_measured():
    result = evaluate_brand_compliance("Too short.")
    assert result["readability"]["flesch_kincaid_grade"] == "NOT_MEASURED"
    assert result["readability"]["within_target_band"] == "NOT_MEASURED"


def test_readability_scored_once_enough_text_exists():
    text = (
        "We help small teams plan a campaign. "
        "We write the copy and book the media. "
        "You approve every step before it ships."
    )
    result = evaluate_brand_compliance(text)
    assert isinstance(result["readability"]["flesch_kincaid_grade"], float)
    assert result["readability"]["target_grade_min"] == READABILITY_GRADE_MIN
    assert result["readability"]["target_grade_max"] == READABILITY_GRADE_MAX


def test_dense_prose_is_flagged_as_advisory_only():
    text = (
        "Our organisation facilitates comprehensive multinational infrastructure "
        "modernisation initiatives, incorporating sophisticated methodological "
        "frameworks alongside intricate operational considerations that "
        "necessitate substantial interdepartmental collaboration throughout."
    )
    result = evaluate_brand_compliance(text)
    assert result["passed"] is True
    assert result["readability"]["within_target_band"] is False
    assert any("Readability grade" in note for note in result["advisories"])


def test_measured_business_copy_sits_inside_the_sentiment_band():
    result = evaluate_brand_compliance(
        "Our team helps small shops plan a seasonal campaign."
    )
    assert isinstance(result["sentiment"]["compound"], float)
    assert result["sentiment"]["within_target_band"] is True


def test_manufactured_euphoria_exceeds_the_sentiment_band():
    result = evaluate_brand_compliance(
        "AMAZING!!! The most incredible life-changing deal EVER!!! Unbelievable joy!"
    )
    assert result["sentiment"]["compound"] > SENTIMENT_MAX
    assert result["sentiment"]["within_target_band"] is False
    assert any("exceeds" in note for note in result["advisories"])


def test_sentiment_band_breach_is_advisory_not_a_failure():
    result = evaluate_brand_compliance("Wonderful! Fantastic! Perfect! Brilliant! Superb!")
    assert result["sentiment"]["within_target_band"] is False
    assert result["passed"] is True


def test_sentiment_not_measured_on_trivial_text():
    result = evaluate_brand_compliance("Hello.")
    assert result["sentiment"]["compound"] == "NOT_MEASURED"
    assert result["sentiment"]["within_target_band"] == "NOT_MEASURED"


def test_sentiment_polarity_returns_none_below_word_floor():
    assert sentiment_polarity("Hi.") is None


def test_flesch_kincaid_returns_none_below_word_floor():
    assert flesch_kincaid_grade("Five short words here now.") is None


def test_empty_input_is_handled():
    result = evaluate_brand_compliance("")
    assert result["passed"] is True
    assert result["readability"]["flesch_kincaid_grade"] == "NOT_MEASURED"
