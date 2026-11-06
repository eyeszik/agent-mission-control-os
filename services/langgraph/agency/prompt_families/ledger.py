"""Deterministic concept signatures, duplicate detection and bounded repair.

The hard gate is structural, not semantic: a signature is the SHA-256 of the
canonical concept-level fields (metaphor, composition, subject, graphic
device). Two concepts are duplicates when the signature matches, and
duplicate-risk when three of the four concept fields repeat an accepted
concept. Embedding similarity may be added later as an advisory signal; it is
never the release gate.
"""

from __future__ import annotations

from services.langgraph.agency.prompt_compiler import stable_hash

from .models import (
    AXIS_PRIORITY,
    ConceptLedger,
    ConceptLedgerEntry,
    ConceptSignature,
    LedgerStatus,
    PromptFamilyInstance,
    VariationAxis,
)

MAX_REPAIR_PASSES = 3
NEAR_DUPLICATE_SHARED_FIELDS = 3


def concept_signature(variation: dict[str, str]) -> ConceptSignature:
    fields = {
        "primary_metaphor": variation.get(VariationAxis.concept_metaphor.value, ""),
        "composition": variation.get(VariationAxis.composition.value, ""),
        "subject": variation.get(VariationAxis.subject.value, ""),
        "graphic_device": variation.get(VariationAxis.graphic_device.value, ""),
    }
    normalized = {key: " ".join(value.lower().split()) for key, value in fields.items()}
    return ConceptSignature(**fields, signature_hash=stable_hash(normalized))


def duplicate_reason(signature: ConceptSignature, accepted: list[ConceptSignature]) -> str | None:
    """Return why ``signature`` repeats an accepted concept, or None."""
    for prior in accepted:
        if prior.signature_hash == signature.signature_hash:
            return "exact concept signature already used"
        mine = [" ".join(item.lower().split()) for item in signature.fields()]
        theirs = [" ".join(item.lower().split()) for item in prior.fields()]
        shared = sum(1 for a, b in zip(mine, theirs) if a and a == b)
        if shared >= NEAR_DUPLICATE_SHARED_FIELDS:
            return f"{shared} of 4 concept fields repeat an accepted concept"
    return None


def repair_variation(
    variation: dict[str, str],
    axes: dict[VariationAxis, list[str]],
    accepted: list[ConceptSignature],
) -> tuple[dict[str, str], list[str]]:
    """Change the highest-level concept variable first, bounded to three passes.

    Returns the (possibly unchanged) variation and a log of what was altered.
    Cosmetic axes are only touched once every higher-level axis is exhausted.
    """
    current = dict(variation)
    log: list[str] = []
    for _ in range(MAX_REPAIR_PASSES):
        if duplicate_reason(concept_signature(current), accepted) is None:
            return current, log
        changed = False
        for axis in AXIS_PRIORITY:
            options = axes.get(axis)
            if not options or len(options) < 2:
                continue
            start = options.index(current[axis.value]) if current.get(axis.value) in options else -1
            for step in range(1, len(options)):
                candidate = dict(current)
                candidate[axis.value] = options[(start + step) % len(options)]
                if duplicate_reason(concept_signature(candidate), accepted) is None:
                    log.append(f"{axis.value}: {current.get(axis.value)!r} -> {candidate[axis.value]!r}")
                    current = candidate
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    return current, log


def record(ledger: ConceptLedger, instances: list[PromptFamilyInstance]) -> ConceptLedger:
    """Append instances to a new ledger value; the input ledger is not mutated."""
    entries = list(ledger.entries)
    rejected = list(ledger.rejected_patterns)
    for instance in instances:
        entries.append(
            ConceptLedgerEntry(
                family_id=instance.family_id,
                instance_id=instance.instance_id,
                signature=instance.signature,
                status=instance.status,
                variation=dict(instance.variation),
            )
        )
        if instance.status is LedgerStatus.rejected_duplicate:
            rejected.append(instance.signature.signature_hash)
    return ConceptLedger(entries=entries, rejected_patterns=sorted(set(rejected)))
