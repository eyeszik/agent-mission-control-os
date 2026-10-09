"""Deterministic user-intent compiler.

Extracts the facts the rest of the slice needs from the raw request and keeps
the exact words they came from (character spans). There is no model call, so
identical input always compiles identically.

What it will not do:

* infer authority. An external effect (publish, spend, send) is recorded as
  FORBIDDEN_TO_INFER and needs a separate human decision; "approve" in a
  message is only an APPROVAL_CANDIDATE, never an approval;
* infer a deliverable it cannot name. An unrecognised deliverable is
  AMBIGUOUS_CRITICAL and becomes one of at most three clarification questions;
* switch to simulation from wording alone. The mode is a server-side argument;
  wording that mentions simulation without it is only noted.
"""

from __future__ import annotations

import re
from typing import Optional

from services.langgraph.agency.execution.canonical import canonical_hash

from .contracts import (
    CompiledIntent,
    Deliverable,
    ExecutionMode,
    FactType,
    IntentFact,
    SideEffect,
    UtteranceType,
)

MAX_REQUEST_CHARS = 4000
MAX_CLARIFICATIONS = 3

# Order matters: the first family whose pattern matches wins, and the more
# specific families come first (an "SVG logo" is a vector mark, not an image).
_DELIVERABLE_PATTERNS: tuple[tuple[Deliverable, re.Pattern[str]], ...] = (
    (Deliverable.VECTOR_MARK, re.compile(r"\b(svg|vector|logo|logomark|wordmark|monogram|brand mark|mark)\b", re.I)),
    (Deliverable.DESIGN_TOKENS, re.compile(r"\b(design tokens?|dtcg|token set|colour tokens?|color tokens?)\b", re.I)),
    (Deliverable.GENERATED_VIDEO, re.compile(r"\b(video|reel|animation|clip)\b", re.I)),
    (Deliverable.RASTER_IMAGE, re.compile(r"\b(image|photo|photograph|illustration|picture|render(?:ing)?|poster)\b", re.I)),
)

_SIDE_EFFECT_PATTERNS: tuple[tuple[SideEffect, re.Pattern[str]], ...] = (
    (SideEffect.PUBLISH, re.compile(r"\b(publish|post it|post to|go live|launch it|push live|put it live)\b", re.I)),
    (SideEffect.SPEND, re.compile(r"\b(spend|buy|purchase|boost|run ads?|ad budget|pay for)\b", re.I)),
    (SideEffect.SEND, re.compile(r"\b(send(?!\s+(?:me|us|it to me|it to us)\b)|email|e-mail|dm|message the|notify customers)\b", re.I)),
)

_PROJECT_ID = re.compile(r"\b(prj-[a-z0-9][a-z0-9-]{2,80})\b")
_SIMULATION_WORDS = re.compile(r"\b(simulat\w*|dry[- ]run|pretend|mock(?:-?up)?)\b", re.I)
_CORRECTION = re.compile(r"^\s*(no[,.!]|actually\b|correction\b|that'?s wrong|not that)", re.I)
_APPROVAL = re.compile(r"\b(approve[sd]?|looks good|sign(?:ed)? off|lgtm)\b", re.I)
_REVOCATION = re.compile(r"\b(revoke|withdraw (?:my )?approval|cancel (?:the )?approval|unapprove)\b", re.I)


def _span(match: re.Match[str]) -> tuple[int, int]:
    return (match.start(), match.end())


def _utterance(text: str) -> UtteranceType:
    if _REVOCATION.search(text):
        return UtteranceType.REVOCATION_CANDIDATE
    if _CORRECTION.search(text):
        return UtteranceType.CORRECTION
    if _APPROVAL.search(text):
        return UtteranceType.APPROVAL_CANDIDATE
    if text.rstrip().endswith("?"):
        return UtteranceType.QUESTION
    return UtteranceType.REQUEST


def compile_intent(raw_request: str, *, requested_mode: Optional[ExecutionMode] = None) -> CompiledIntent:
    """Compile a raw request. ``requested_mode`` is a server-validated argument, not text."""
    if not isinstance(raw_request, str) or not raw_request.strip():
        raise ValueError("request text is required")
    if len(raw_request) > MAX_REQUEST_CHARS:
        raise ValueError(f"request text exceeds {MAX_REQUEST_CHARS} characters")
    text = raw_request
    facts: list[IntentFact] = []
    questions: list[str] = []

    deliverable: Optional[Deliverable] = None
    for family, pattern in _DELIVERABLE_PATTERNS:
        match = pattern.search(text)
        if match:
            deliverable = family
            facts.append(IntentFact(kind="deliverable", value=family.value, fact_type=FactType.EXPLICIT, span=_span(match),
                                    note=f"matched '{match.group(0)}'"))
            break
    if deliverable is None:
        facts.append(IntentFact(kind="deliverable", value=None, fact_type=FactType.AMBIGUOUS_CRITICAL,
                                note="no deliverable family this slice can route was named"))
        questions.append("What should be made: a vector mark (SVG), design tokens, an image or a video?")

    side_effects: list[SideEffect] = []
    for effect, pattern in _SIDE_EFFECT_PATTERNS:
        match = pattern.search(text)
        if match:
            side_effects.append(effect)
            facts.append(IntentFact(kind="side_effect", value=effect.value, fact_type=FactType.FORBIDDEN_TO_INFER,
                                    span=_span(match),
                                    note="an external effect needs a separate human authorization; wording never grants it"))

    project_ids: list[str] = []
    for match in _PROJECT_ID.finditer(text):
        if match.group(1) not in project_ids:
            project_ids.append(match.group(1))
            facts.append(IntentFact(kind="project_id", value=match.group(1), fact_type=FactType.EXPLICIT, span=_span(match)))

    mode = requested_mode or ExecutionMode.REAL_EXECUTION
    sim = _SIMULATION_WORDS.search(text)
    if requested_mode is None:
        facts.append(IntentFact(kind="execution_mode", value=mode.value, fact_type=FactType.SAFE_DEFAULT,
                                note="production missions default to real execution"))
        if sim:
            facts.append(IntentFact(kind="execution_mode_hint", value=sim.group(0), fact_type=FactType.AMBIGUOUS_NONCRITICAL,
                                    span=_span(sim),
                                    note="wording mentions simulation; simulation must be selected explicitly, not inferred"))
    else:
        facts.append(IntentFact(kind="execution_mode", value=mode.value, fact_type=FactType.EXPLICIT,
                                note="selected by the caller, validated server-side"))

    utterance = _utterance(text)
    if utterance is UtteranceType.APPROVAL_CANDIDATE:
        facts.append(IntentFact(kind="approval_language", value=True, fact_type=FactType.FORBIDDEN_TO_INFER,
                                note="approval is recorded only through the approvals system, never from message text"))

    return CompiledIntent(
        raw_request=text,
        request_hash=canonical_hash({"request": text, "mode": mode.value}),
        utterance_type=utterance,
        deliverable=deliverable,
        side_effects=tuple(side_effects),
        explicit_project_ids=tuple(project_ids),
        mode=mode,
        facts=tuple(facts),
        clarifications=tuple(questions[:MAX_CLARIFICATIONS]),
    )


__all__ = ["MAX_CLARIFICATIONS", "MAX_REQUEST_CHARS", "compile_intent"]
