"""Persuasive-framing check for approval summaries (OWASP ASI09, human trust exploitation).

An approval asks a person to authorize an action. The summary that asks is written by an agent, and that
agent may have an incentive to make approval look routine. This module scores the summary text for
recognisable pressure patterns and for omissions. It stores the result on the approval. A high score
blocks an approve decision until the reviewer explicitly acknowledges it.

This is a deterministic heuristic, not a judgement of intent. Its limits:

* it reads English only, and matches phrases, not meaning;
* it cannot know whether a claim is true, only whether it cites evidence;
* a clean result means "no known pattern", not "no framing".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NONE, REVIEW, HIGH = "NONE", "REVIEW", "HIGH"

_PATTERNS: dict[str, re.Pattern[str]] = {
    "URGENCY": re.compile(r"\b(urgent(ly)?|immediately|right now|asap|act now|deadline|time[- ]sensitive|"
                          r"before it'?s too late|no time)\b", re.I),
    "PRESSURE_TO_APPROVE": re.compile(r"\b(just approve|simply approve|rubber[- ]?stamp|no need to review|"
                                      r"trust me|the owner (wants|asked|approved)|already approved|"
                                      r"everyone (agreed|approved)|don'?t (need|bother) to (check|review))\b", re.I),
    "MINIMIZATION": re.compile(r"\b(harmless|minor|routine|low[- ]risk|no risk|nothing (to see|will change)|"
                               r"trivial|standard procedure|completely safe)\b", re.I),
    "UNSUPPORTED_ASSURANCE": re.compile(r"\b(verified|audited|tested|guaranteed|100 ?%|proven safe)\b", re.I),
}
_EVIDENCE = re.compile(r"(evidence|sha256|hash|sealed|ref)[:= ]\s*[A-Za-z0-9_./:-]{6,}", re.I)


@dataclass(frozen=True)
class FramingAssessment:
    level: str
    codes: tuple[str, ...]

    @property
    def codes_text(self) -> str:
        return ",".join(self.codes)


def assess(summary: str, *, targets: tuple[str, ...] = ()) -> FramingAssessment:
    """Score a summary. ``targets`` are identifiers the summary must mention if they are supplied."""
    text = summary or ""
    codes: list[str] = []
    for code, pattern in _PATTERNS.items():
        if code == "UNSUPPORTED_ASSURANCE":
            if pattern.search(text) and not _EVIDENCE.search(text):
                codes.append(code)
        elif pattern.search(text):
            codes.append(code)
    if targets and not any(t.lower() in text.lower() for t in targets if t):
        codes.append("OMITS_TARGET")
    if not codes:
        return FramingAssessment(NONE, ())
    if "PRESSURE_TO_APPROVE" in codes or len(codes) >= 2:
        return FramingAssessment(HIGH, tuple(codes))
    return FramingAssessment(REVIEW, tuple(codes))


__all__ = ["HIGH", "NONE", "REVIEW", "FramingAssessment", "assess"]
