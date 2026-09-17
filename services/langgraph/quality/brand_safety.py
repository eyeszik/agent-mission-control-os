"""Machine-checkable brand compliance rules.

Replaces the previous flat substring scan, which matched banned terms anywhere
in the text and therefore flagged compliance disclaimers as violations: the
sentence "results are not guaranteed" tripped the "guaranteed" rule even though
it is the disclaimer the rule exists to encourage. Patterns are now anchored on
word boundaries and, where the negated form is a disclaimer rather than a claim,
suppressed when a negator immediately precedes the match.

Prohibited-claim matches are hard failures. Missing disclaimers and
out-of-band readability are reported as advisories, because whether they should
block delivery is an open policy decision rather than a settled one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

ENGINE_VERSION = "brand-compliance/v2"

READABILITY_GRADE_MIN = 6.0
READABILITY_GRADE_MAX = 9.0

# Below this, a Flesch-Kincaid score is arithmetic noise rather than a
# readability signal, so it is reported as NOT_MEASURED instead of a number.
READABILITY_MIN_WORDS = 20

# Compound-polarity band. The upper bound is the operative one: copy scoring
# above it reads as manufactured euphoria rather than a claim about the
# product, which is the register regulators and readers both distrust.
SENTIMENT_MIN = 0.15
SENTIMENT_MAX = 0.65
SENTIMENT_MIN_WORDS = 3

_SENTIMENT_ANALYZER = SentimentIntensityAnalyzer()

_NEGATORS = frozenset(
    {
        "not",
        "no",
        "never",
        "cannot",
        "cant",
        "isnt",
        "arent",
        "wont",
        "doesnt",
        "dont",
        "without",
        "nor",
        "neither",
    }
)
_NEGATION_WINDOW_WORDS = 4


@dataclass(frozen=True)
class ProhibitedPattern:
    pattern_id: str
    regex: re.Pattern[str]
    description: str
    negatable: bool


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# ``negatable`` marks rules whose negated form is a legitimate disclaimer.
# "not clinically proven" is a disclosure; "no side effects" is still the claim,
# because the negator is part of the claim rather than a retraction of it.
PROHIBITED_PATTERNS: Tuple[ProhibitedPattern, ...] = (
    ProhibitedPattern(
        "guaranteed_outcome",
        _compile(r"\bguarantee(?:d|s)?\b"),
        "Unqualified guarantee of an outcome",
        True,
    ),
    ProhibitedPattern(
        "risk_free",
        _compile(r"\brisk[-\s]?free\b"),
        "Absolute absence-of-risk claim",
        False,
    ),
    ProhibitedPattern(
        "instant_outcome",
        _compile(r"\binstant\s+(?:results?|wealth|riches|cure)\b"),
        "Immediate-outcome claim",
        False,
    ),
    ProhibitedPattern(
        "medical_cure",
        _compile(r"\bcures?\b"),
        "Medical cure claim",
        True,
    ),
    ProhibitedPattern(
        "miracle",
        _compile(r"\bmiracle\b"),
        "Miracle-efficacy claim",
        False,
    ),
    ProhibitedPattern(
        "clinically_proven",
        _compile(r"\bclinically\s+proven\b"),
        "Clinical-substantiation claim",
        True,
    ),
    ProhibitedPattern(
        "no_side_effects",
        _compile(r"\bno\s+side[-\s]?effects?\b"),
        "Absolute safety claim",
        False,
    ),
    ProhibitedPattern(
        "superlative_rank",
        _compile(r"#\s?1\s+in\s+the\s+world\b|\bbest\s+in\s+the\s+universe\b"),
        "Unsubstantiated superlative ranking",
        False,
    ),
    ProhibitedPattern(
        "regulatory_approval",
        _compile(r"\bfda[-\s]approved\b"),
        "Regulatory-approval claim",
        True,
    ),
)

DISCLAIMER_PATTERNS: Dict[str, re.Pattern[str]] = {
    "terms_apply_ref": _compile(r"\bterms\s+(?:and\s+conditions\s+)?apply\b|\bt&cs?\s+apply\b"),
    "statutory_ad_label": _compile(r"\b(?:advertisement|sponsored|paid\s+partnership)\b|^\s*ad\b"),
}

_WORD_RE = re.compile(r"[A-Za-z']+")
_SENTENCE_RE = re.compile(r"[.!?]+")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")


def _count_syllables(word: str) -> int:
    lowered = word.lower().strip("'")
    if not lowered:
        return 0
    count = len(_VOWEL_GROUP_RE.findall(lowered))
    if lowered.endswith("e") and not lowered.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(count, 1)


def flesch_kincaid_grade(text: str) -> float | None:
    """US grade level, or None when there is too little text to score honestly."""
    words = _WORD_RE.findall(text or "")
    sentences = [chunk for chunk in _SENTENCE_RE.split(text or "") if chunk.strip()]
    if len(words) < READABILITY_MIN_WORDS or not sentences:
        return None
    syllables = sum(_count_syllables(word) for word in words)
    grade = (
        0.39 * (len(words) / len(sentences))
        + 11.8 * (syllables / len(words))
        - 15.59
    )
    return round(grade, 2)


def sentiment_polarity(text: str) -> float | None:
    """VADER compound polarity, or None when there is too little text to score."""
    if len(_WORD_RE.findall(text or "")) < SENTIMENT_MIN_WORDS:
        return None
    return round(_SENTIMENT_ANALYZER.polarity_scores(text)["compound"], 3)


def _is_negated(text: str, match_start: int) -> bool:
    preceding = _WORD_RE.findall(text[:match_start].lower())
    window = preceding[-_NEGATION_WINDOW_WORDS:]
    return any(word.replace("'", "") in _NEGATORS for word in window)


def evaluate_brand_compliance(
    text: str,
    *,
    required_disclaimers: Sequence[str] = (),
) -> Dict[str, Any]:
    """Evaluate copy against prohibited claims, disclaimers, and readability.

    ``passed`` reflects prohibited-claim violations only. Missing disclaimers and
    readability drift populate ``advisories`` without failing the gate.
    """
    source = text or ""

    violations: List[Dict[str, str]] = []
    for rule in PROHIBITED_PATTERNS:
        for match in rule.regex.finditer(source):
            if rule.negatable and _is_negated(source, match.start()):
                continue
            violations.append(
                {
                    "pattern_id": rule.pattern_id,
                    "matched_text": match.group(0),
                    "description": rule.description,
                }
            )

    unknown_disclaimers = [
        name for name in required_disclaimers if name not in DISCLAIMER_PATTERNS
    ]
    missing_disclaimers = [
        name
        for name in required_disclaimers
        if name in DISCLAIMER_PATTERNS and not DISCLAIMER_PATTERNS[name].search(source)
    ]

    grade = flesch_kincaid_grade(source)
    if grade is None:
        readability: Dict[str, Any] = {
            "flesch_kincaid_grade": "NOT_MEASURED",
            "within_target_band": "NOT_MEASURED",
            "target_grade_min": READABILITY_GRADE_MIN,
            "target_grade_max": READABILITY_GRADE_MAX,
        }
    else:
        readability = {
            "flesch_kincaid_grade": grade,
            "within_target_band": READABILITY_GRADE_MIN <= grade <= READABILITY_GRADE_MAX,
            "target_grade_min": READABILITY_GRADE_MIN,
            "target_grade_max": READABILITY_GRADE_MAX,
        }

    polarity = sentiment_polarity(source)
    if polarity is None:
        sentiment: Dict[str, Any] = {
            "compound": "NOT_MEASURED",
            "within_target_band": "NOT_MEASURED",
            "target_min": SENTIMENT_MIN,
            "target_max": SENTIMENT_MAX,
        }
    else:
        sentiment = {
            "compound": polarity,
            "within_target_band": SENTIMENT_MIN <= polarity <= SENTIMENT_MAX,
            "target_min": SENTIMENT_MIN,
            "target_max": SENTIMENT_MAX,
        }

    # Normalized and deduplicated for stable aggregation across runs; the
    # verbatim match stays available on each violation for human reviewers.
    flagged_terms: List[str] = []
    for item in violations:
        normalized = item["matched_text"].lower()
        if normalized not in flagged_terms:
            flagged_terms.append(normalized)

    advisories: List[str] = []
    for name in missing_disclaimers:
        advisories.append(f"Required disclaimer not present: {name}.")
    for name in unknown_disclaimers:
        advisories.append(f"Unknown disclaimer rule requested and not evaluated: {name}.")
    if readability["within_target_band"] is False:
        advisories.append(
            f"Readability grade {grade} is outside the target band "
            f"{READABILITY_GRADE_MIN}-{READABILITY_GRADE_MAX}."
        )
    if sentiment["within_target_band"] is False:
        if polarity > SENTIMENT_MAX:
            advisories.append(
                f"Sentiment polarity {polarity} exceeds {SENTIMENT_MAX}; copy reads as "
                "overstated enthusiasm rather than a substantiated claim."
            )
        else:
            advisories.append(
                f"Sentiment polarity {polarity} is below {SENTIMENT_MIN}; copy reads as "
                "flat or negative for a marketing context."
            )

    return {
        "engine_version": ENGINE_VERSION,
        "passed": not violations,
        "flagged_terms": flagged_terms,
        "violations": violations,
        "missing_disclaimers": missing_disclaimers,
        "readability": readability,
        "sentiment": sentiment,
        "advisories": advisories,
    }
