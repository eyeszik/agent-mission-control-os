"""Content operations: one verified fact core, many channel-native derivatives.

A :class:`ContentAtom` holds the claims (each with its evidence refs and
verification state). Derivatives never invent facts: every section of a
derivative is built from atom claims and names the claim ids it used, so the
claim → evidence lineage survives every transformation. A derivative that uses
an unverified or contradicted claim carries a release blocker; it can be drafted
but never scheduled.

This is structure, not copywriting. No LLM is called here: the sections are the
deterministic skeleton (what each format must contain and which claims feed it)
that the copy/creative roles fill in under their N3 contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import Claim, ContentAtom, ContentVariantSpec
from .vocabulary import ContentKind
from .workspace import canonical_json, sha256_bytes


@dataclass(frozen=True)
class FormatRule:
    sections: tuple[str, ...]
    claims_per_unit: int | None  # None = all claims
    verified_only: bool = False
    constraints: tuple[str, ...] = ()


# Channel-native structure per content kind. "{claim}" sections are expanded
# once per claim the format uses.
FORMAT_RULES: dict[ContentKind, FormatRule] = {
    ContentKind.ARTICLE: FormatRule(("headline", "lede", "{claim}", "sources"), None),
    ContentKind.EMAIL: FormatRule(("subject", "preheader", "{claim}", "cta"), 3, constraints=("subject<=60 chars", "preheader<=100 chars")),
    ContentKind.NEWSLETTER: FormatRule(("subject", "intro", "{claim}", "sign_off"), None, constraints=("subject<=60 chars",)),
    ContentKind.CAROUSEL: FormatRule(("cover_slide", "{claim}", "cta_slide"), 8, constraints=("<=10 slides", "one claim per slide")),
    ContentKind.SOCIAL_POST: FormatRule(("hook", "{claim}", "cta"), 1),
    ContentKind.THREAD: FormatRule(("hook_post", "{claim}", "closing_post"), 6, constraints=("one claim per post",)),
    ContentKind.VIDEO_SCRIPT: FormatRule(("cold_open", "{claim}", "outro"), 5, constraints=("spoken-word pacing",)),
    ContentKind.SHORT_VIDEO: FormatRule(("hook_0_3s", "{claim}", "end_card"), 2, constraints=("<=60s", "captions burned in")),
    ContentKind.REEL: FormatRule(("hook_0_3s", "{claim}", "end_card"), 2, constraints=("9:16", "<=90s")),
    ContentKind.STORY: FormatRule(("frame", "{claim}", "sticker_cta"), 3, constraints=("9:16",)),
    ContentKind.PODCAST_EPISODE: FormatRule(("intro", "{claim}", "outro"), None),
    ContentKind.FAQ: FormatRule(("{claim}",), None, constraints=("question + direct answer per claim",)),
    ContentKind.LANDING_SECTION: FormatRule(("heading", "{claim}", "cta"), 3),
    # Answer engines and paid placements amplify claims: verified evidence only.
    ContentKind.AI_SEARCH_ANSWER: FormatRule(("direct_answer", "{claim}", "citations"), None, verified_only=True, constraints=("cite every claim",)),
    ContentKind.PAID_CREATIVE: FormatRule(("headline", "{claim}", "cta"), 1, verified_only=True, constraints=("platform ad policy review",)),
}

CHANNEL_LIMITS: dict[str, str] = {
    "x": "<=280 chars per post",
    "linkedin": "<=3000 chars",
    "instagram": "caption <=2200 chars",
    "tiktok": "caption <=2200 chars",
    "youtube": "title <=100 chars",
    "email": "subject <=60 chars",
    "web": "semantic HTML headings",
}


class ContentLineageError(ValueError):
    pass


def atom_hash(title: str, claims: Iterable[Claim], source_refs: Iterable[str]) -> str:
    payload = {
        "title": title,
        "claims": [claim.model_dump(mode="json") for claim in claims],
        "source_refs": sorted(source_refs),
    }
    return sha256_bytes(canonical_json(payload))


def _eligible_claims(atom: ContentAtom, rule: FormatRule) -> list[Claim]:
    claims = [claim for claim in atom.claims if claim.verification != "CONTRADICTED"]
    if rule.verified_only:
        claims = [claim for claim in claims if claim.verification == "VERIFIED"]
    return claims if rule.claims_per_unit is None else claims[: rule.claims_per_unit]


def derive_variant(atom: ContentAtom, kind: ContentKind | str, channel: str) -> ContentVariantSpec:
    kind = ContentKind(kind)
    rule = FORMAT_RULES[kind]
    used = _eligible_claims(atom, rule)
    sections: list[str] = []
    for section in rule.sections:
        if section == "{claim}":
            sections.extend(f"claim:{claim.claim_id}" for claim in used)
        else:
            sections.append(section)
    blockers: list[str] = []
    if not used:
        blockers.append("NO_ELIGIBLE_CLAIMS")
    blockers += [f"UNVERIFIED_CLAIM:{claim.claim_id}" for claim in used if claim.verification != "VERIFIED"]
    blockers += [f"CLAIM_WITHOUT_EVIDENCE:{claim.claim_id}" for claim in used if not claim.evidence_refs]
    constraints = list(rule.constraints)
    if channel in CHANNEL_LIMITS:
        constraints.append(CHANNEL_LIMITS[channel])
    return ContentVariantSpec(
        kind=kind,
        channel=channel,
        title=f"{atom.title} — {kind.value} for {channel}",
        sections=tuple(sections),
        claim_refs=tuple(claim.claim_id for claim in used),
        constraints=tuple(constraints),
        atom_id=atom.atom_id,
        atom_version=atom.version,
        release_blockers=tuple(blockers),
    )


def derive_variants(atom: ContentAtom, targets: Iterable[tuple[str, str]]) -> list[ContentVariantSpec]:
    return [derive_variant(atom, kind, channel) for kind, channel in targets]


def assert_lineage(atom: ContentAtom, variant: ContentVariantSpec) -> None:
    """A derivative may only cite claims that exist in its source atom version."""
    if variant.atom_id != atom.atom_id or variant.atom_version != atom.version:
        raise ContentLineageError("variant does not derive from this atom version")
    known = {claim.claim_id for claim in atom.claims}
    unknown = [ref for ref in variant.claim_refs if ref not in known]
    if unknown:
        raise ContentLineageError(f"variant cites claims missing from the atom: {unknown}")


def evidence_for(atom: ContentAtom, variant: ContentVariantSpec) -> dict[str, list[str]]:
    assert_lineage(atom, variant)
    by_id = {claim.claim_id: claim for claim in atom.claims}
    return {ref: list(by_id[ref].evidence_refs) for ref in variant.claim_refs}


def exhaustion_map(atom: ContentAtom, produced: Iterable[ContentVariantSpec]) -> dict[str, object]:
    """ContentExhaustionMap: which claims have been used, by which formats."""
    usage: dict[str, list[str]] = {claim.claim_id: [] for claim in atom.claims}
    for variant in produced:
        for ref in variant.claim_refs:
            if ref in usage:
                usage[ref].append(f"{variant.kind.value}:{variant.channel}")
    unused_kinds = [kind.value for kind in ContentKind if kind not in {v.kind for v in produced}]
    return {
        "atom_id": atom.atom_id,
        "claim_usage": usage,
        "unused_claims": sorted(ref for ref, uses in usage.items() if not uses),
        "untapped_formats": unused_kinds,
    }
