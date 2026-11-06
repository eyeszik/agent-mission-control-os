"""ContractCritic: deterministic satisfaction checks for a DeliveryContract.

Only deterministic checks can produce PASS. Anything the critic cannot decide
mechanically is NOT_MEASURED with a reason, and the contract's definition of
done (``dod``) says what that means for release:

* ``FAIL``        a blocking check failed; release is blocked.
* ``ESCALATE``    a blocking check could not be measured (stale evidence,
                  unsupported equivalence); release is blocked until the input
                  changes, and an approval cannot override it.
* ``NEEDS_HUMAN`` the only open blocking items are HUMAN_REVIEW; the release
                  approval, whose subject binds the contract hash, decides them.
* ``PASS``        every blocking check passed.

The critic never calls a model. An LLM may add advisory review notes elsewhere;
nothing it says can turn a requirement into PASS.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.delivery.contract import (
    ContractRequirement,
    DeliveryContract,
    RequiredFact,
    contract_hash,
    pattern_engine_available,
)
from services.langgraph.agency.execution.canonical import canonical_hash

RESULT_SCHEMA_VERSION = "amc-contract-result/v1"
Verdict = Literal["PASS", "FAIL", "NOT_MEASURED"]
Dod = Literal["PASS", "FAIL", "ESCALATE", "NEEDS_HUMAN"]
EvidenceResolver = Callable[[str], Optional[str]]

_WHITESPACE = re.compile(r"\s+")


class RequirementResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    kind: str
    blocking: bool
    verdict: Verdict
    reason: str
    # Indexes into the requirement's phrases, never the matched text itself.
    matched_phrase_indexes: tuple[int, ...] = ()


class ContractResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["amc-contract-result/v1"] = RESULT_SCHEMA_VERSION
    contract_hash: str
    subject_text_hash: str
    results: tuple[RequirementResult, ...]
    dod: Dod


def result_hash(result: ContractResult) -> str:
    return canonical_hash(result.model_dump(mode="json"))


def normalize_phrase_text(text: str) -> str:
    """NFKC, casefold, punctuation/separators to spaces, collapse whitespace.

    Format characters (zero-width joiners and the like) are removed outright so
    they cannot split a forbidden word either.
    """

    folded = unicodedata.normalize("NFKC", text).casefold()
    out = []
    for ch in folded:
        category = unicodedata.category(ch)
        if category == "Cf":
            continue
        out.append(" " if category[0] in {"P", "Z"} else ch)
    return _WHITESPACE.sub(" ", "".join(out)).strip()


def normalize_verbatim(text: str) -> str:
    """Verbatim matching keeps case and punctuation; only NFC and whitespace."""

    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def _contains_tokens(haystack_norm: str, needle_norm: str) -> bool:
    if not needle_norm:
        return False
    return f" {needle_norm} " in f" {haystack_norm} "


def content_text(value: Any) -> str:
    """Deterministic text projection of delivered content (string leaves)."""

    parts: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for key in sorted(v, key=lambda k: str(k).encode("utf-8")):
                walk(v[key])
        elif isinstance(v, (list, tuple)):
            for item in v:
                walk(item)

    walk(value)
    return "\n".join(parts)


def evidence_status(fact: RequiredFact, now: datetime, resolve: Optional[EvidenceResolver]) -> str:
    """FRESH, or the reason the evidence no longer backs the fact."""

    if fact.verified_at > now:
        return "STALE_EVIDENCE:not_yet_verified"
    if fact.valid_until is not None and fact.valid_until <= now:
        return "STALE_EVIDENCE:expired"
    current = resolve(fact.verification_ref) if resolve else None
    if current is None:
        return "STALE_EVIDENCE:unresolvable"
    if current != fact.evidence_hash:
        return "STALE_EVIDENCE:source_changed"
    return "FRESH"


def _check(req: ContractRequirement, text: str, now: datetime, resolve: Optional[EvidenceResolver]) -> RequirementResult:
    def result(verdict: Verdict, reason: str, matched: tuple[int, ...] = ()) -> RequirementResult:
        return RequirementResult(
            requirement_id=req.requirement_id,
            kind=req.kind,
            blocking=req.blocking,
            verdict=verdict,
            reason=reason,
            matched_phrase_indexes=matched,
        )

    if req.kind == "HUMAN_REVIEW":
        return result("NOT_MEASURED", "HUMAN_REVIEW_PENDING")
    if req.kind == "PATTERN":
        # Contracts with PATTERN are rejected at intake while no engine is
        # pinned; this branch only guards against a bypassed intake.
        return result("NOT_MEASURED", "PATTERN_ENGINE_UNAVAILABLE" if not pattern_engine_available() else "PATTERN_UNSUPPORTED")
    if req.kind == "PHRASE_FORBIDDEN":
        normalized = normalize_phrase_text(text)
        matched = tuple(
            index for index, phrase in enumerate(req.phrases) if _contains_tokens(normalized, normalize_phrase_text(phrase))
        )
        return result("FAIL", "FORBIDDEN_PHRASE_PRESENT", matched) if matched else result("PASS", "NO_FORBIDDEN_PHRASE")
    # FACT_PRESENT
    fact = req.fact
    assert fact is not None
    freshness = evidence_status(fact, now, resolve)
    if freshness != "FRESH":
        return result("NOT_MEASURED", freshness)
    if req.must_appear_verbatim:
        present = normalize_verbatim(fact.statement) in normalize_verbatim(text)
    elif req.equivalence == "normalized_text":
        present = _contains_tokens(normalize_phrase_text(text), normalize_phrase_text(fact.statement))
    else:
        return result("NOT_MEASURED", "EQUIVALENCE_UNSUPPORTED")
    return result("PASS", "FACT_PRESENT") if present else result("FAIL", "FACT_ABSENT")


def _dod(results: tuple[RequirementResult, ...]) -> Dod:
    blocking = [r for r in results if r.blocking]
    if any(r.verdict == "FAIL" for r in blocking):
        return "FAIL"
    if any(r.verdict == "NOT_MEASURED" and r.reason != "HUMAN_REVIEW_PENDING" for r in blocking):
        return "ESCALATE"
    if any(r.verdict == "NOT_MEASURED" for r in blocking):
        return "NEEDS_HUMAN"
    return "PASS"


def evaluate_contract(
    contract: DeliveryContract,
    content: Any,
    *,
    now: datetime,
    resolve_evidence: Optional[EvidenceResolver] = None,
) -> ContractResult:
    text = content if isinstance(content, str) else content_text(content)
    results = tuple(_check(req, text, now, resolve_evidence) for req in contract.requirements)
    return ContractResult(
        contract_hash=contract_hash(contract),
        subject_text_hash=canonical_hash(text),
        results=results,
        dod=_dod(results),
    )
