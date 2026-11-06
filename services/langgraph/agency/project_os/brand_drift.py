"""Brand stewardship: detect drift, propose refreshes, never overwrite.

Inputs are project artifacts (metadata + readable text), content items and
explicit brand facts. Each check is deterministic and reports evidence. A
category with no input to judge it is listed in ``not_evaluated`` rather than
reported as clean, so the report never claims more coverage than it has.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

from .models import BrandDriftFinding, BrandDriftReport
from .workspace import canonical_json, sha256_bytes

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_PRICE = re.compile(r"(?:[$€£]\s?\d[\d,]*(?:\.\d{2})?)")

ALL_CATEGORIES = (
    "logo_misuse", "colors", "typography", "voice", "naming", "claims", "stale_product_facts", "old_pricing",
    "old_screenshots", "expired_rights", "accessibility", "duplicate_content", "creative_repetition",
)


@dataclass(frozen=True)
class BrandFacts:
    palette: tuple[str, ...] = ()
    banned_terms: tuple[str, ...] = ()
    deprecated_names: Mapping[str, str] = field(default_factory=dict)  # old -> current
    current_prices: tuple[str, ...] = ()
    brand_core_ref: Optional[str] = None


@dataclass(frozen=True)
class DriftSubject:
    artifact_id: str
    status: str
    text: Optional[str] = None
    content_hash: Optional[str] = None
    variant_of: Optional[str] = None
    prompt_refs: tuple[str, ...] = ()
    rights: Optional[Mapping[str, object]] = None
    unverified_claims: tuple[str, ...] = ()


def analyze(*, project_id: str, tenant_id: str, facts: BrandFacts, subjects: Iterable[DriftSubject]) -> BrandDriftReport:
    subjects = list(subjects)
    findings: list[BrandDriftFinding] = []
    evaluated: set[str] = set()
    palette = {color.lower() for color in facts.palette}
    texts = [s for s in subjects if s.text]

    if palette and texts:
        evaluated.add("colors")
        for subject in texts:
            off = sorted({c.lower() for c in _HEX.findall(subject.text)} - palette)
            if off:
                findings.append(BrandDriftFinding(category="colors", severity="warning", artifact_id=subject.artifact_id,
                                                  detail=f"colors outside the approved palette: {', '.join(off)}", evidence=tuple(off)))
    if facts.banned_terms and texts:
        evaluated.add("voice")
        for subject in texts:
            hits = sorted({term for term in facts.banned_terms if re.search(rf"\b{re.escape(term)}\b", subject.text, re.IGNORECASE)})
            if hits:
                findings.append(BrandDriftFinding(category="voice", severity="warning", artifact_id=subject.artifact_id,
                                                  detail=f"off-voice terms: {', '.join(hits)}", evidence=tuple(hits)))
    if facts.deprecated_names and texts:
        evaluated.add("naming")
        for subject in texts:
            hits = sorted(old for old in facts.deprecated_names if re.search(rf"\b{re.escape(old)}\b", subject.text, re.IGNORECASE))
            if hits:
                findings.append(BrandDriftFinding(category="naming", severity="warning", artifact_id=subject.artifact_id,
                                                  detail="deprecated names: " + ", ".join(f"{h} → {facts.deprecated_names[h]}" for h in hits), evidence=tuple(hits)))
    if facts.current_prices and texts:
        evaluated.add("old_pricing")
        current = {price.replace(" ", "") for price in facts.current_prices}
        for subject in texts:
            stale = sorted({p.replace(" ", "") for p in _PRICE.findall(subject.text)} - current)
            if stale:
                findings.append(BrandDriftFinding(category="old_pricing", severity="blocking", artifact_id=subject.artifact_id,
                                                  detail=f"prices not in the current price list: {', '.join(stale)}", evidence=tuple(stale)))

    evaluated.add("claims")
    for subject in subjects:
        if subject.unverified_claims:
            findings.append(BrandDriftFinding(category="claims", severity="blocking", artifact_id=subject.artifact_id,
                                              detail="uses unverified claims", evidence=subject.unverified_claims))
    evaluated.add("stale_product_facts")
    for subject in subjects:
        if subject.status in {"invalidated", "review_required"}:
            findings.append(BrandDriftFinding(category="stale_product_facts", severity="warning", artifact_id=subject.artifact_id,
                                              detail=f"upstream changed; artifact is {subject.status}"))
    if any(s.rights is not None for s in subjects):
        evaluated.add("expired_rights")
        for subject in subjects:
            if subject.rights is not None and not subject.rights.get("ok"):
                findings.append(BrandDriftFinding(category="expired_rights", severity="blocking", artifact_id=subject.artifact_id,
                                                  detail=str(subject.rights.get("reason"))))
    evaluated.add("duplicate_content")
    by_hash: dict[str, list[DriftSubject]] = defaultdict(list)
    for subject in subjects:
        if subject.content_hash:
            by_hash[subject.content_hash].append(subject)
    for digest, group in sorted(by_hash.items()):
        independent = [s for s in group if not s.variant_of]
        if len(independent) > 1:
            for subject in independent[1:]:
                findings.append(BrandDriftFinding(category="duplicate_content", severity="info", artifact_id=subject.artifact_id,
                                                  detail=f"identical content to {independent[0].artifact_id}", evidence=(digest,)))
    evaluated.add("creative_repetition")
    prompt_use = Counter(ref for subject in subjects for ref in subject.prompt_refs)
    for ref, count in sorted(prompt_use.items()):
        if count >= 4:
            users = [s.artifact_id for s in subjects if ref in s.prompt_refs]
            findings.append(BrandDriftFinding(category="creative_repetition", severity="info", artifact_id=users[-1],
                                              detail=f"prompt {ref} reused {count} times; creative fatigue risk", evidence=(ref,)))

    findings.sort(key=lambda f: ({"blocking": 0, "warning": 1, "info": 2}[f.severity], f.category, f.artifact_id))
    refresh = sorted({f.artifact_id for f in findings if f.severity in {"blocking", "warning"}})
    not_evaluated = tuple(category for category in ALL_CATEGORIES if category not in evaluated)
    body = {"findings": [f.model_dump(mode="json") for f in findings], "refresh": refresh, "not_evaluated": list(not_evaluated)}
    return BrandDriftReport(
        project_id=project_id,
        tenant_id=tenant_id,
        brand_core_ref=facts.brand_core_ref,
        findings=tuple(findings),
        refresh_candidates=tuple(refresh),
        not_evaluated=not_evaluated,
        report_hash=sha256_bytes(canonical_json(body)),
    )
