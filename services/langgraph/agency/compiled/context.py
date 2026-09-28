"""T08/T09 — CompanyGenome projection and ContextLens capsules.

The genome is a deterministic, evidence-linked *projection* over canonical
state supplied by the caller (approved briefs, verified facts, decisions). It
is never a second source of truth: it stores refs and hashes, preserves
contradictions and unknowns, and has no write path back into canonical state.

A :class:`ContextCapsule` is the minimum sufficient context for one work node:
it carries refs (``key@hash``), not generated summaries, and becomes
``INVALIDATED_CONTEXT`` as soon as any dependency hash it was built from moves.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable, Mapping

from pydantic import BaseModel

from services.langgraph.agency.kernel.models import EpistemicStatus as KernelEpistemicStatus

from .hashing import semantic_hash

_FROZEN = {"frozen": True, "extra": "forbid"}


class GenomeEpistemic(str, Enum):
    VERIFIED_FACT = "VERIFIED_FACT"
    INFERENCE = "INFERENCE"
    ASSUMPTION = "ASSUMPTION"
    HYPOTHESIS = "HYPOTHESIS"
    PROPOSAL = "PROPOSAL"
    CONFLICT = "CONFLICT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


# Bridge to the kernel's evidence vocabulary so genome facts can be checked
# against kernel Evidence rows without a second enum becoming authoritative.
KERNEL_EPISTEMIC_MAP: dict[GenomeEpistemic, KernelEpistemicStatus] = {
    GenomeEpistemic.VERIFIED_FACT: KernelEpistemicStatus.verified,
    GenomeEpistemic.INFERENCE: KernelEpistemicStatus.inferred,
    GenomeEpistemic.ASSUMPTION: KernelEpistemicStatus.assumption,
    GenomeEpistemic.HYPOTHESIS: KernelEpistemicStatus.hypothesis,
    GenomeEpistemic.PROPOSAL: KernelEpistemicStatus.unverified,
    GenomeEpistemic.CONFLICT: KernelEpistemicStatus.conflict,
    GenomeEpistemic.STALE: KernelEpistemicStatus.stale,
    GenomeEpistemic.UNKNOWN: KernelEpistemicStatus.unverified,
}


class GenomeAssertion(BaseModel):
    model_config = _FROZEN

    key: str
    domain: str
    value_or_ref: str
    source_refs: tuple[str, ...] = ()
    epistemic_status: GenomeEpistemic = GenomeEpistemic.UNKNOWN
    confidence: float | None = None
    freshness: str | None = None
    sensitivity: str = "internal"
    owner_ref: str | None = None
    decision_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()

    @property
    def content_hash(self) -> str:
        return semantic_hash(self)

    @property
    def ref(self) -> str:
        return f"{self.key}@{self.content_hash[:16]}"


class CompanyGenome(BaseModel):
    model_config = _FROZEN

    assertions: tuple[GenomeAssertion, ...]
    conflicts: tuple[str, ...]
    unknowns: tuple[str, ...]
    genome_hash: str

    def by_key(self, key: str) -> tuple[GenomeAssertion, ...]:
        return tuple(a for a in self.assertions if a.key == key)


def project_genome(assertions: Iterable[GenomeAssertion]) -> CompanyGenome:
    """Deterministic projection. Contradictions are kept, never resolved silently.

    Facts without any source ref are downgraded to ``UNKNOWN``: an unsourced
    "fact" cannot carry the same epistemic weight as an evidenced one.
    """
    normalized: list[GenomeAssertion] = []
    for a in assertions:
        if a.epistemic_status is GenomeEpistemic.VERIFIED_FACT and not a.source_refs:
            a = a.model_copy(update={"epistemic_status": GenomeEpistemic.UNKNOWN})
        normalized.append(a)
    unique = {a.content_hash: a for a in normalized}
    ordered = tuple(sorted(unique.values(), key=lambda a: (a.key, a.content_hash)))

    values_by_key: dict[str, set[str]] = {}
    for a in ordered:
        if a.epistemic_status in {GenomeEpistemic.VERIFIED_FACT, GenomeEpistemic.INFERENCE, GenomeEpistemic.ASSUMPTION}:
            values_by_key.setdefault(a.key, set()).add(a.value_or_ref)
    conflicts = {k for k, vals in values_by_key.items() if len(vals) > 1}
    conflicts |= {a.key for a in ordered if a.epistemic_status is GenomeEpistemic.CONFLICT}
    unknowns = {a.key for a in ordered if a.epistemic_status is GenomeEpistemic.UNKNOWN}
    body = {
        "assertions": [a.content_hash for a in ordered],
        "conflicts": sorted(conflicts),
        "unknowns": sorted(unknowns),
    }
    return CompanyGenome(
        assertions=ordered,
        conflicts=tuple(sorted(conflicts)),
        unknowns=tuple(sorted(unknowns)),
        genome_hash=semantic_hash(body),
    )


class ContextCapsule(BaseModel):
    model_config = _FROZEN

    objective: str
    acceptance_criteria: tuple[str, ...]
    relevant_genome_refs: tuple[str, ...]
    approved_decision_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    dependency_refs: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    authority_refs: tuple[str, ...]
    tool_permissions: tuple[str, ...]
    open_questions: tuple[str, ...]
    freshness_deadlines: tuple[str, ...]
    dependency_hashes: tuple[tuple[str, str], ...]
    capsule_hash: str


def project_capsule(
    genome: CompanyGenome,
    *,
    objective: str,
    acceptance_criteria: Iterable[str],
    domains: Iterable[str],
    genome_keys: Iterable[str] = (),
    approved_decision_refs: Iterable[str] = (),
    artifact_refs: Iterable[str] = (),
    dependency_hashes: Mapping[str, str] | None = None,
    hard_constraints: Iterable[str] = (),
    authority_refs: Iterable[str] = (),
    tool_permissions: Iterable[str] = (),
) -> ContextCapsule:
    """Minimum sufficient context: only assertions in the node's domains or named keys."""
    domain_set = set(domains)
    key_set = set(genome_keys)
    selected = [a for a in genome.assertions if a.domain in domain_set or a.key in key_set]
    open_questions = sorted(
        {f"CONFLICT:{a.key}" for a in selected if a.key in genome.conflicts}
        | {f"{a.epistemic_status.value}:{a.key}" for a in selected
           if a.epistemic_status in {GenomeEpistemic.UNKNOWN, GenomeEpistemic.STALE, GenomeEpistemic.HYPOTHESIS}}
    )
    deadlines = sorted({f"{a.key}:{a.freshness}" for a in selected if a.freshness})
    deps = tuple(sorted((dependency_hashes or {}).items()))
    body = {
        "objective": objective,
        "acceptance_criteria": tuple(sorted(acceptance_criteria)),
        "relevant_genome_refs": tuple(sorted(a.ref for a in selected)),
        "approved_decision_refs": tuple(sorted(approved_decision_refs)),
        "artifact_refs": tuple(sorted(artifact_refs)),
        "dependency_refs": tuple(ref for ref, _ in deps),
        "hard_constraints": tuple(sorted(hard_constraints)),
        "authority_refs": tuple(sorted(authority_refs)),
        "tool_permissions": tuple(sorted(tool_permissions)),
        "open_questions": tuple(open_questions),
        "freshness_deadlines": tuple(deadlines),
        "dependency_hashes": deps,
    }
    return ContextCapsule(**body, capsule_hash=semantic_hash(body))


class CapsuleFreshness(str, Enum):
    FRESH = "FRESH"
    INVALIDATED_CONTEXT = "INVALIDATED_CONTEXT"


def capsule_freshness(capsule: ContextCapsule, current_hashes: Mapping[str, str]) -> CapsuleFreshness:
    for ref, digest in capsule.dependency_hashes:
        if current_hashes.get(ref) != digest:
            return CapsuleFreshness.INVALIDATED_CONTEXT
    return CapsuleFreshness.FRESH


def hoist_shared_refs(capsules: Iterable[ContextCapsule]) -> tuple[str, ...]:
    """Genome refs every capsule needs — loaded once rather than per specialist."""
    sets = [set(c.relevant_genome_refs) for c in capsules]
    if not sets:
        return ()
    return tuple(sorted(set.intersection(*sets)))
