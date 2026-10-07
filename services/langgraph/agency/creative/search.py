"""Bounded concept search: diverse seeds, fingerprints, mutation and the Pareto front.

Search is a T4-only mechanism with hard caps (population <= 4, generations
<= 2, <= 1 regeneration per collapsed candidate). It is deterministic:

- ``concept_candidates`` picks materially different ``ConceptSpec``s by
  farthest-point selection over the five concept axes, seeded from the
  mission hash, so the same mission always explores the same concepts;
- ``fingerprint`` / ``distance`` measure candidate difference on structure
  (concept axes, section order, rendered tag sequence), not on wording;
- ``detect_collapse`` reports pairs closer than the diversity floor;
- ``MutationSpec`` changes exactly one soft axis and records why. A mutation
  can never touch a hard constraint: constraints live on the mission, not on
  the concept;
- ``pareto_front`` is non-domination *with uncertainty*: ``a`` dominates
  ``b`` only when ``a``'s lower bound beats ``b``'s upper bound on at least one
  objective and is no worse on all others. Close calls stay on the front and
  go to the human; the runtime never collapses the front to a weighted sum.
"""

from __future__ import annotations

import itertools
from typing import Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.execution_fabric.verifiers import parse_dom

from .ir import ConceptSpec, MissionIR

AXES: dict[str, tuple[str, ...]] = {
    "narrative": ("outcome_first", "problem_first", "proof_first", "story_first"),
    "hierarchy": ("single_focus", "layered", "modular"),
    "composition": ("split_hero", "centered", "editorial", "full_bleed"),
    "interaction": ("single_cta", "guided_demo", "progressive"),
    "metaphor": ("shield", "lens", "control_room", "pathway", "none"),
}
AxisName = Literal["narrative", "hierarchy", "composition", "interaction", "metaphor"]
DEFAULT_CONCEPT = ConceptSpec(narrative="outcome_first", hierarchy="layered", composition="split_hero",
                              interaction="single_cta", metaphor="none")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def axis_distance(a: ConceptSpec, b: ConceptSpec) -> float:
    return sum(getattr(a, k) != getattr(b, k) for k in AXES) / len(AXES)


def _all_concepts() -> list[ConceptSpec]:
    return [ConceptSpec(**dict(zip(AXES, combo))) for combo in itertools.product(*AXES.values())]


def concept_candidates(mission: MissionIR, n: int, *, exclude: Sequence[ConceptSpec] = ()) -> list[ConceptSpec]:
    """``n`` (<= 4) concepts that are pairwise as different as possible."""
    n = max(1, min(4, n))
    pool = sorted(_all_concepts(), key=lambda c: canonical_hash([mission.mission_hash, c.model_dump()]))
    chosen: list[ConceptSpec] = []
    anchors = list(exclude)
    for _ in range(n):
        _, best = max(
            ((i, c) for i, c in enumerate(pool) if c not in chosen and c not in anchors),
            key=lambda ic: (min((axis_distance(ic[1], o) for o in chosen + anchors), default=1.0), -ic[0]),
        )
        chosen.append(best)
    return chosen


class CandidateFingerprint(_Strict):
    candidate_id: str
    concept: dict[str, str]
    section_order: tuple[str, ...]
    tag_sequence_hash: str
    tags: tuple[str, ...] = Field(repr=False)


def fingerprint(candidate_id: str, concept: ConceptSpec, section_order: Sequence[str], rendering: str) -> CandidateFingerprint:
    tags = tuple(parse_dom(rendering).tags)
    return CandidateFingerprint(candidate_id=candidate_id, concept=concept.model_dump(), section_order=tuple(section_order),
                                tag_sequence_hash=canonical_hash(list(tags)), tags=tags)


def _seq_distance(x: Sequence[str], y: Sequence[str]) -> float:
    prev = list(range(len(y) + 1))
    for i, tx in enumerate(x, 1):
        cur = [i]
        for j, ty in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (tx != ty)))
        prev = cur
    return prev[-1] / max(1, len(x), len(y))


def distance(a: CandidateFingerprint, b: CandidateFingerprint) -> float:
    """0 = structurally identical, 1 = maximally different (mean of three views)."""
    concept = sum(a.concept[k] != b.concept[k] for k in AXES) / len(AXES)
    return round((concept + _seq_distance(a.section_order, b.section_order) + _seq_distance(a.tags, b.tags)) / 3, 4)


def detect_collapse(fps: Sequence[CandidateFingerprint], floor: float) -> list[tuple[str, str, float]]:
    out = []
    for a, b in itertools.combinations(fps, 2):
        d = distance(a, b)
        if d < floor:
            out.append((a.candidate_id, b.candidate_id, d))
    return out


class NoveltyReservoir:
    """In-run memory of explored fingerprints; novelty = distance to the nearest."""

    def __init__(self) -> None:
        self._items: list[CandidateFingerprint] = []

    def novelty(self, fp: CandidateFingerprint) -> float:
        others = [o for o in self._items if o.candidate_id != fp.candidate_id]
        return min((distance(fp, o) for o in others), default=1.0)

    def add(self, fp: CandidateFingerprint) -> None:
        if all(o.candidate_id != fp.candidate_id for o in self._items):
            self._items.append(fp)

    def __len__(self) -> int:
        return len(self._items)


class MutationSpec(_Strict):
    mutation_id: str
    parent_candidate_id: str
    axis: AxisName
    from_value: str
    to_value: str
    reason: str
    preserves_hard_constraints: Literal[True] = True


def mutate(parent_id: str, concept: ConceptSpec, *, reason: str, avoid: Sequence[ConceptSpec] = (),
           axis: Optional[AxisName] = None) -> tuple[ConceptSpec, MutationSpec]:
    """Change exactly one soft axis, choosing the value that is farthest from ``avoid``."""
    options: list[tuple[float, str, str, ConceptSpec]] = []
    for name in ([axis] if axis else list(AXES)):
        for value in AXES[name]:
            if value == getattr(concept, name):
                continue
            child = concept.model_copy(update={name: value})
            spread = min((axis_distance(child, o) for o in avoid), default=1.0)
            options.append((spread, name, value, child))
    if not options:
        raise ValueError("no mutation available on the requested axis")
    spread, name, value, child = max(options, key=lambda o: (o[0], -list(AXES).index(o[1]), -AXES[o[1]].index(o[2])))
    spec = MutationSpec(mutation_id=f"mut-{canonical_hash([parent_id, name, value])[:12]}", parent_candidate_id=parent_id,
                        axis=name, from_value=getattr(concept, name), to_value=value, reason=reason)
    return child, spec


class ObjectiveEstimate(_Strict):
    value: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)


def dominates(a: Mapping[str, ObjectiveEstimate], b: Mapping[str, ObjectiveEstimate]) -> bool:
    keys = sorted(set(a) & set(b))
    if not keys:
        return False
    no_worse = all(a[k].value - a[k].uncertainty >= b[k].value - b[k].uncertainty for k in keys)
    strictly = any(a[k].value - a[k].uncertainty > b[k].value + b[k].uncertainty for k in keys)
    return no_worse and strictly


class ParetoResult(_Strict):
    front: tuple[str, ...]
    dominated_by: dict[str, tuple[str, ...]]
    objectives: tuple[str, ...]


def pareto_front(candidates: Mapping[str, Mapping[str, ObjectiveEstimate]]) -> ParetoResult:
    ids = sorted(candidates)
    dominated_by = {i: tuple(j for j in ids if j != i and dominates(candidates[j], candidates[i])) for i in ids}
    front = tuple(i for i in ids if not dominated_by[i])
    objectives = tuple(sorted(set().union(*(set(v) for v in candidates.values())))) if candidates else ()
    return ParetoResult(front=front, dominated_by={k: v for k, v in dominated_by.items() if v}, objectives=objectives)


__all__ = [
    "AXES", "CandidateFingerprint", "DEFAULT_CONCEPT", "MutationSpec", "NoveltyReservoir", "ObjectiveEstimate",
    "ParetoResult", "axis_distance", "concept_candidates", "detect_collapse", "distance", "dominates",
    "fingerprint", "mutate", "pareto_front",
]
