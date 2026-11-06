"""KnowledgeOps: a deterministic evidence pipeline for continuously researched sources.

    DISCOVER → FETCH → SANITIZE → INJECTION_SCAN → RIGHTS_CLASSIFY
    → CLAIM_EXTRACT → DATE/FRESHNESS → DEDUPE → TRIANGULATE
    → CONTRADICTION_CHECK → EVIDENCE_SCORE → CAPSULE → REVIEW → PROMOTE

This module runs FETCHED text through every stage up to REVIEW. Fetching is
the caller's job (and an external action); promotion is a human decision.
Nothing here calls a network or an LLM.

Rights shape what is kept. Third-party text never becomes prompt authority:
only short extracted claims are stored, never the source body, and a source
whose rights prohibit copying keeps no text at all. This follows the design
corpus provenance rule: record where knowledge came from and what you may do
with it, and copy as little as possible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from services.langgraph.security.preprocess import sanitize_deep

from .models import KnowledgeClaim
from .vocabulary import RightsClass
from .workspace import canonical_json, sha256_bytes

MAX_CLAIMS = 20
MAX_CLAIM_CHARS = 280
PROMOTION_SCORE_FLOOR = 0.6

# Freshness windows per research domain. Fast-moving domains go stale sooner.
FRESHNESS_DAYS: dict[str, int] = {
    "provider_cost": 30,
    "provider_capability": 45,
    "models": 60,
    "social": 90,
    "search": 120,
    "aeo_geo": 90,
    "advertising": 180,
    "production_tooling": 180,
}
DEFAULT_FRESHNESS_DAYS = 365

_INJECTION_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts)",
    r"disregard (the )?(system|previous) (prompt|instructions)",
    r"you are now (?:a|an|the) ",
    r"\bsystem prompt\b",
    r"<\s*script\b",
    r"\bBEGIN (?:SYSTEM|INSTRUCTIONS)\b",
    r"\bact as (?:an? )?(?:admin|developer|root)\b",
))
_OPEN_LICENSES = ("cc0", "cc-by", "cc by", "public domain", "mit", "apache-2.0", "apache 2.0", "ogl", "open government licence")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_TOKEN = re.compile(r"[a-z0-9]+")
_NEGATION = {"not", "no", "never", "none", "cannot", "isn't", "aren't", "doesn't", "don't", "won't"}


@dataclass(frozen=True)
class SourceDocument:
    domain: str
    source_uri: str
    text: str
    license: Optional[str] = None
    rights_declared: Optional[RightsClass] = None
    published_at: Optional[str] = None
    fetched_at: Optional[str] = None


@dataclass
class PipelineOutcome:
    stage: str
    status: str
    rights_class: RightsClass
    claims: tuple[KnowledgeClaim, ...] = ()
    evidence_score: float = 0.0
    rejection_reasons: tuple[str, ...] = ()
    content_hash: str = ""
    stage_log: list[str] = field(default_factory=list)


def classify_rights(document: SourceDocument) -> RightsClass:
    if document.rights_declared is not None:
        return document.rights_declared
    license_text = (document.license or "").strip().lower()
    if not license_text:
        return RightsClass.UNKNOWN
    if any(token in license_text for token in _OPEN_LICENSES):
        return RightsClass.OPEN_LICENSE
    if "all rights reserved" in license_text or "no derivatives" in license_text:
        return RightsClass.PROPRIETARY_NO_COPY
    return RightsClass.LICENSED


def injection_findings(text: str) -> list[str]:
    return [pattern.pattern for pattern in _INJECTION_PATTERNS if pattern.search(text)]


def extract_claims(text: str) -> list[str]:
    claims: list[str] = []
    for sentence in _SENTENCE.split(text):
        sentence = " ".join(sentence.split())
        words = sentence.split()
        if not 6 <= len(words) <= 60 or sentence.endswith("?"):
            continue
        claims.append(sentence[:MAX_CLAIM_CHARS])
        if len(claims) >= MAX_CLAIMS:
            break
    return claims


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a) - _NEGATION, _tokens(b) - _NEGATION
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _negated(text: str) -> bool:
    return bool(_tokens(text) & _NEGATION) or "n't" in text.lower()


def freshness_deadline(document: SourceDocument, now: datetime) -> Optional[datetime]:
    stamp = document.published_at or document.fetched_at
    if not stamp:
        return None
    moment = datetime.fromisoformat(stamp)
    moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return moment + timedelta(days=FRESHNESS_DAYS.get(document.domain, DEFAULT_FRESHNESS_DAYS))


def run_pipeline(
    document: SourceDocument,
    *,
    now: datetime,
    known_hashes: Iterable[str] = (),
    corpus: Iterable[tuple[str, str]] = (),
) -> PipelineOutcome:
    """``corpus`` is ``(source_uri, claim_text)`` pairs already in the tenant's
    knowledge store, used for triangulation and contradiction checks."""
    log = ["DISCOVER", "FETCH"]
    rights = classify_rights(document)
    sanitized = sanitize_deep(document.text or "")
    log.append("SANITIZE")
    digest = sha256_bytes(canonical_json({"uri": document.source_uri, "text": sanitized}))

    findings = injection_findings(document.text or "")
    log.append("INJECTION_SCAN")
    if findings:
        return PipelineOutcome("INJECTION_SCAN", "REJECTED", rights, rejection_reasons=tuple(f"INJECTION:{f}" for f in findings), content_hash=digest, stage_log=log)

    log.append("RIGHTS_CLASSIFY")
    if rights is RightsClass.PROPRIETARY_NO_COPY:
        return PipelineOutcome("RIGHTS_CLASSIFY", "REJECTED", rights, rejection_reasons=("RIGHTS_PROHIBIT_COPY",), content_hash=digest, stage_log=log)

    raw_claims = extract_claims(sanitized)
    log.append("CLAIM_EXTRACT")
    if not raw_claims:
        return PipelineOutcome("CLAIM_EXTRACT", "REJECTED", rights, rejection_reasons=("NO_EXTRACTABLE_CLAIMS",), content_hash=digest, stage_log=log)

    deadline = freshness_deadline(document, now)
    stale = deadline is not None and deadline < now
    log.append("DATE_FRESHNESS")

    if digest in set(known_hashes):
        log.append("DEDUPE")
        return PipelineOutcome("DEDUPE", "REJECTED", rights, rejection_reasons=("DUPLICATE_SOURCE",), content_hash=digest, stage_log=log)
    log.append("DEDUPE")

    corpus_list = [(uri, text) for uri, text in corpus if uri != document.source_uri]
    claims: list[KnowledgeClaim] = []
    contradictions = 0
    corroborated = 0
    for text in raw_claims:
        supporting = sorted({uri for uri, other in corpus_list if similarity(text, other) >= 0.6 and _negated(text) == _negated(other)})
        opposing = sorted({uri for uri, other in corpus_list if similarity(text, other) >= 0.6 and _negated(text) != _negated(other)})
        corroborated += 1 if supporting else 0
        contradictions += 1 if opposing else 0
        claims.append(KnowledgeClaim(
            text=text,
            observed_date=document.published_at or document.fetched_at,
            corroborating_sources=tuple(supporting),
            contradicted_by=tuple(opposing),
        ))
    log += ["TRIANGULATE", "CONTRADICTION_CHECK"]

    score = 0.2
    score += 0.2 if rights in {RightsClass.OPEN_LICENSE, RightsClass.LICENSED} else 0.0
    score += 0.2 if deadline is not None and not stale else 0.0
    score += 0.3 * min(1.0, corroborated / max(len(claims), 1) * 2)
    score -= 0.3 if contradictions else 0.0
    score = round(max(0.0, min(1.0, score)), 3)
    log += ["EVIDENCE_SCORE", "CAPSULE"]

    reasons = []
    if stale:
        reasons.append("SOURCE_STALE")
    if rights is RightsClass.UNKNOWN:
        reasons.append("RIGHTS_UNKNOWN_SUMMARY_ONLY")
    return PipelineOutcome("REVIEW", "AWAITING_REVIEW", rights if rights is not RightsClass.UNKNOWN else RightsClass.SUMMARY_ONLY,
                           claims=tuple(claims), evidence_score=score, rejection_reasons=tuple(reasons), content_hash=digest, stage_log=log + ["REVIEW"])


def promotion_authority(evidence_score: float) -> str:
    """Promoted knowledge becomes evidence memory only above the score floor."""
    return "VERIFIED_EVIDENCE" if evidence_score >= PROMOTION_SCORE_FLOOR else "WORKING_CONTEXT"
