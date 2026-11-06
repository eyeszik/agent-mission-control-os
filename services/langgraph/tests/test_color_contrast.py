"""Tests for the WCAG 2.2 contrast-ratio utilities.

Reference values are independently verifiable, not derived from the
implementation under test: black/white is the standard 21:1 textbook
example cited throughout WCAG documentation and every contrast checker.
"""

from __future__ import annotations

import pytest

from services.langgraph.agency.artifacts.color_contrast import (
    contrast_ratio,
    meets_wcag_aa,
    meets_wcag_non_text,
    relative_luminance,
)


def test_white_luminance_is_one():
    assert relative_luminance("#FFFFFF") == pytest.approx(1.0)


def test_black_luminance_is_zero():
    assert relative_luminance("#000000") == pytest.approx(0.0)


def test_black_on_white_is_the_textbook_21_to_1():
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=1e-9)


def test_contrast_is_symmetric():
    assert contrast_ratio("#000000", "#FFFFFF") == contrast_ratio("#FFFFFF", "#000000")


def test_a_color_against_itself_is_1_to_1():
    assert contrast_ratio("#1a2b4c", "#1a2b4c") == pytest.approx(1.0, abs=1e-9)


def test_accepts_lowercase_and_uppercase_hex():
    assert contrast_ratio("#000000", "#ffffff") == contrast_ratio("#000000", "#FFFFFF")


def test_rejects_non_hex_input():
    with pytest.raises(ValueError, match="not a 6-digit hex color"):
        relative_luminance("blue")


def test_rejects_short_hex_shorthand():
    with pytest.raises(ValueError):
        relative_luminance("#fff")


def test_rejects_missing_hash():
    with pytest.raises(ValueError):
        relative_luminance("1a2b4c")


def test_meets_wcag_aa_normal_text_threshold_is_4_5():
    assert meets_wcag_aa(4.5) is True
    assert meets_wcag_aa(4.49) is False


def test_meets_wcag_aa_large_text_threshold_is_3():
    assert meets_wcag_aa(3.0, large_text=True) is True
    assert meets_wcag_aa(2.99, large_text=True) is False


def test_meets_wcag_non_text_threshold_is_3():
    assert meets_wcag_non_text(3.0) is True
    assert meets_wcag_non_text(2.99) is False


def test_high_contrast_pair_passes_normal_text_aa():
    ratio = contrast_ratio("#000000", "#FFFFFF")
    assert meets_wcag_aa(ratio) is True


def test_near_identical_grays_fail_normal_text_aa():
    ratio = contrast_ratio("#808080", "#828282")
    assert meets_wcag_aa(ratio) is False
