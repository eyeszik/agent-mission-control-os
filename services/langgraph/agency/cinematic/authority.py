"""Source-authority resolution, conflict detection, and unresolved-state.

Higher-authority information always wins over lower. Inferences never silently
become canon; an unknown-critical fact becomes a development proposal or a
focused question rather than an invented value.
"""

from __future__ import annotations

from typing import Iterable

from .schemas import Fact, FactLedger, FactStatus, SourceAuthority


def resolve_facts(facts: Iterable[Fact]) -> tuple[FactLedger, list[dict[str, str]]]:
    """Partition facts by status and surface conflicts.

    A conflict is two facts on the same ``key`` with different values. The
    higher-authority fact is preserved (lower ``rank`` wins); the conflict is
    recorded rather than silently resolved away.
    """

    ledger = FactLedger()
    winners: dict[str, Fact] = {}
    conflicts: list[dict[str, str]] = []

    for fact in facts:
        current = winners.get(fact.key)
        if current is None:
            winners[fact.key] = fact
            continue
        if _same_value(current.value, fact.value):
            # Agreement: keep the higher-authority provenance.
            if fact.authority.rank < current.authority.rank:
                winners[fact.key] = fact
            continue
        # Genuine disagreement.
        keep, drop = (
            (current, fact)
            if current.authority.rank <= fact.authority.rank
            else (fact, current)
        )
        winners[fact.key] = keep
        conflicts.append(
            {
                "key": fact.key,
                "kept_value": _repr(keep.value),
                "kept_authority": keep.authority.value,
                "dropped_value": _repr(drop.value),
                "dropped_authority": drop.authority.value,
                "resolution": "higher_authority_preserved",
            }
        )

    for fact in winners.values():
        if fact.status is FactStatus.defined:
            ledger.defined.append(fact)
        elif fact.status is FactStatus.inferred:
            ledger.inferred.append(fact)
        elif fact.status is FactStatus.proposed:
            ledger.proposed.append(fact)
        # UNKNOWN_CRITICAL facts are surfaced through unresolved_items, not stored
        # as if they were known.

    ledger.conflicts = conflicts
    return ledger, conflicts


def promote_to_canon(fact: Fact) -> Fact:
    """Guard: refuse to silently convert an inference into canon.

    Promotion is only legal for a DEFINED fact. An INFERRED/PROPOSED fact must
    first be confirmed (its status changed by an authoritative source), so this
    raises rather than laundering an inference into established canon.
    """

    if fact.status is not FactStatus.defined:
        raise ValueError(
            f"cannot promote {fact.key!r} to canon: status is {fact.status.value}, "
            "not DEFINED — confirm the fact before it becomes canon"
        )
    return fact.model_copy(update={"authority": SourceAuthority.established_canon})


def unresolved_items(facts: Iterable[Fact]) -> list[dict[str, str]]:
    """UNKNOWN_CRITICAL facts become focused questions / development proposals."""

    items: list[dict[str, str]] = []
    for fact in facts:
        if fact.status is FactStatus.unknown_critical:
            items.append(
                {
                    "key": fact.key,
                    "kind": "unknown_critical",
                    "question": fact.note
                    or f"Critical fact {fact.key!r} is undefined — supply it or accept a proposed default.",
                }
            )
    return items


def requires_human_review(ledger: FactLedger, unresolved: list[dict[str, str]]) -> bool:
    """Human-in-the-loop is required on unresolved conflicts or unknown criticals."""

    return bool(ledger.conflicts) or bool(unresolved)


def _same_value(left: object, right: object) -> bool:
    return _norm(left) == _norm(right)


def _norm(value: object) -> str:
    return str(value).strip().lower()


def _repr(value: object) -> str:
    return "" if value is None else str(value)
