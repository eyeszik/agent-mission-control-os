"""Rights-safe, budgeted context portfolio.

Candidate units come from two governed sources:

- the installed design corpus, loaded through ``design_corpus.load_validated_corpus``
  (hash-validated; any integrity failure means *no* corpus units and a
  ``DEGRADED`` portfolio, never invented guidance). Owned standards contribute
  their best-matching bounded excerpt; reference-only entries contribute
  category plus generic principle names only; unknown-rights entries are
  excluded;
- workflow guides of the capabilities the plan activates (core-constraint
  line only), after the registry's hash and injection checks.

Selection first filters (rights, integrity, authority, injection, mission
compatibility), always keeps mandatory units, then fills the token budget
greedily by

    U = a*R + b*A + c*D + d*I + e*N - l*Redundancy - m*TokenCost - n*ConflictRisk

with deterministic tie-breaks. The weights are configuration heuristics, not
creative truth. Every selected and excluded unit is receipted with a reason.

``derive_requirements`` turns the owned accessibility contract's checklist
keys into concrete artifact requirements, which is how selected context
changes the artifact (and what the counterfactual benchmark measures).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency import design_corpus as dc
from services.langgraph.agency.compiled.role_sources import scan_for_injection
from services.langgraph.agency.execution.canonical import canonical_hash

from .capabilities import RegistryLoad, REGISTRY_ROOT
from .ir import MissionIR

# Authority ladder (A0 highest). Owned standards are A5, workflow guides A6,
# reference principles A7.
AUTHORITY = {"owned_standard": 5, "workflow_guide": 6, "reference_principles": 7}
WEIGHTS = {"R": 0.35, "A": 0.15, "D": 0.20, "I": 0.15, "N": 0.15, "redundancy": 0.20, "token": 0.10, "conflict": 0.25}
MAX_UNIT_CHARS = 700

# Standards that are mandatory context for a family (resolved by title).
MANDATORY_STANDARDS = {
    "interface": ("Contract 02 — Accessible UI Requirements",),
    "*": ("Contract 04 — Rights & Compliance Controls",),
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextUnit(_Strict):
    id: str
    source_class: Literal["owned_standard", "workflow_guide", "reference_principles"]
    authority: int
    relevance: float
    dependency_value: float
    novelty: float
    redundancy: float
    estimated_impact: float
    token_cost: int
    conflict_risk: float
    rights_status: str
    content_hash: str
    text: str
    mandatory: bool = False
    utility: float = 0.0


class ExcludedUnit(_Strict):
    id: str
    reason: str


class ContextPortfolio(_Strict):
    status: Literal["OK", "DEGRADED", "BUDGET_EXHAUSTED"]
    corpus_version: Optional[str]
    token_budget: int
    total_tokens: int
    selected: tuple[ContextUnit, ...]
    excluded: tuple[ExcludedUnit, ...]
    reasons: tuple[str, ...] = ()
    context_hash: str

    def receipt(self) -> dict:
        return {
            "status": self.status, "corpus_version": self.corpus_version, "token_budget": self.token_budget,
            "total_tokens": self.total_tokens, "context_hash": self.context_hash,
            "selected": [{"id": u.id, "source_class": u.source_class, "utility": u.utility, "tokens": u.token_cost,
                          "mandatory": u.mandatory, "content_hash": u.content_hash} for u in self.selected],
            "excluded": [e.model_dump() for e in self.excluded], "reasons": list(self.reasons),
        }


def _tokens(text: str) -> set[str]:
    return dc.query_tokens([text])


def _cost(text: str) -> int:
    # Approximate token count: ~4 characters per token (a budgeting heuristic,
    # not a tokenizer).
    return max(1, len(text) // 4)


def mission_query(mission: MissionIR) -> set[str]:
    return dc.query_tokens([mission.business_goal, mission.user_goal, mission.audience, mission.artifact_type.replace("_", " "),
                            mission.channel, mission.desired_action, mission.artifact_family])


@dataclass
class _Raw:
    id: str
    source_class: str
    rights_status: str
    text: str
    title: str
    mandatory: bool


def _corpus_units(mission: MissionIR, corpus_root: Optional[Path]) -> tuple[list[_Raw], list[ExcludedUnit], Optional[str], list[str]]:
    try:
        manifest, loaded = dc.load_validated_corpus(corpus_root)
    except (dc.CorpusIntegrityError, OSError) as exc:
        return [], [], None, [f"CORPUS_INVALID: {type(exc).__name__}: {str(exc)[:120]}"]
    mandatory_titles = set(MANDATORY_STANDARDS["*"]) | set(MANDATORY_STANDARDS.get(mission.artifact_family, ()))
    query = mission_query(mission)
    raws: list[_Raw] = []
    excluded: list[ExcludedUnit] = []
    for entry, text in loaded:
        cid = entry["corpus_id"]
        if entry["inclusion_status"] != dc.INCLUDED or entry["rights_status"] == dc.RIGHTS_UNKNOWN:
            excluded.append(ExcludedUnit(id=cid, reason="RIGHTS_BLOCKED: unknown rights, pending review"))
            continue
        if entry["source_class"] == dc.SOURCE_CLASS_STANDARD:
            excerpt = dc._standard_excerpt(text, query)[:MAX_UNIT_CHARS]
            body = f"{entry['title']}: {excerpt}"
            raws.append(_Raw(cid, "owned_standard", entry["rights_status"], body, entry["title"], entry["title"] in mandatory_titles))
        else:
            category = next((t.split(":", 1)[1] for t in entry["tags"] if t.startswith("category:")), "uncategorized")
            principles = dc.reference_principles(entry["headings"])
            # Abstract, brand-neutral principles only: no source text, title or name.
            raws.append(_Raw(cid, "reference_principles", entry["rights_status"],
                             f"{category}: {', '.join(principles)}", category, False))
    return raws, excluded, manifest.get("corpus_version"), []


def _guide_units(active_caps: list[str], registry: RegistryLoad, registry_root: Path) -> tuple[list[_Raw], list[ExcludedUnit]]:
    raws: list[_Raw] = []
    excluded: list[ExcludedUnit] = []
    seen: set[str] = set()
    for cap_id in sorted(active_caps):
        cap = registry.capabilities.get(cap_id)
        if cap is None:
            continue
        for ref in cap.source_provenance.guides:
            if ref.path in seen:
                continue
            seen.add(ref.path)
            uid = f"guide:{ref.path}"
            if not registry.usable(cap_id):
                excluded.append(ExcludedUnit(id=uid, reason=registry.quarantined.get(cap_id) or registry.degraded.get(cap_id) or "unusable"))
                continue
            text = (registry_root / ref.path).read_text(encoding="utf-8")
            match = re.search(r"^Core constraint:\s*(.+)$", text, re.M)
            line = (match.group(1) if match else "").strip()[:MAX_UNIT_CHARS]
            raws.append(_Raw(uid, "workflow_guide", "owned_workflow_guide", line, Path(ref.path).stem, True))
    return raws, excluded


def select_context(
    mission: MissionIR,
    registry: RegistryLoad,
    active_capabilities: list[str],
    *,
    token_budget: Optional[int] = None,
    corpus_root: Optional[Path] = None,
    registry_root: Optional[Path] = None,
) -> ContextPortfolio:
    budget = mission.resource_budget.context_token_budget if token_budget is None else token_budget
    corpus_raw, excluded, corpus_version, reasons = _corpus_units(mission, corpus_root)
    guide_raw, guide_excluded = _guide_units(active_capabilities, registry, Path(registry_root or REGISTRY_ROOT))
    excluded += guide_excluded
    query = mission_query(mission)

    units: list[ContextUnit] = []
    for raw in corpus_raw + guide_raw:
        flags = scan_for_injection(raw.text)
        if flags:
            excluded.append(ExcludedUnit(id=raw.id, reason=f"QUARANTINE_SOURCE: {list(flags)}"))
            continue
        toks = _tokens(raw.text)
        relevance = len(query & toks) / max(1, len(query))
        if relevance == 0 and not raw.mandatory:
            excluded.append(ExcludedUnit(id=raw.id, reason="NOT_RELEVANT"))
            continue
        authority = AUTHORITY[raw.source_class]
        units.append(ContextUnit(
            id=raw.id, source_class=raw.source_class, authority=authority, relevance=round(relevance, 4),
            dependency_value=1.0 if raw.mandatory else 0.0, novelty=1.0, redundancy=0.0,
            estimated_impact=0.8 if raw.source_class == "owned_standard" else (0.6 if raw.source_class == "workflow_guide" else 0.3),
            token_cost=_cost(raw.text), conflict_risk=0.2 if raw.source_class == "reference_principles" else 0.0,
            rights_status=raw.rights_status, content_hash=canonical_hash(raw.text), text=raw.text, mandatory=raw.mandatory,
        ))

    def utility(unit: ContextUnit, chosen_tokens: set[str]) -> float:
        toks = _tokens(unit.text)
        overlap = len(toks & chosen_tokens) / max(1, len(toks))
        a = (9 - unit.authority) / 9
        w = WEIGHTS
        return round(w["R"] * unit.relevance + w["A"] * a + w["D"] * unit.dependency_value + w["I"] * unit.estimated_impact
                     + w["N"] * (1 - overlap) - w["redundancy"] * overlap - w["token"] * min(1.0, unit.token_cost / 400)
                     - w["conflict"] * unit.conflict_risk, 6)

    selected: list[ContextUnit] = []
    chosen: set[str] = set()
    used = 0
    status: str = "OK" if not reasons else "DEGRADED"
    # Mandatory units first (deterministic order), then greedy by utility.
    for unit in sorted((u for u in units if u.mandatory), key=lambda u: u.id):
        if used + unit.token_cost > budget:
            status = "BUDGET_EXHAUSTED"
            reasons.append(f"BUDGET_EXHAUSTED: mandatory unit {unit.id} needs {unit.token_cost} tokens")
            excluded.append(ExcludedUnit(id=unit.id, reason="BUDGET_EXHAUSTED: mandatory unit did not fit"))
            continue
        u = utility(unit, chosen)
        selected.append(unit.model_copy(update={"utility": u}))
        chosen |= _tokens(unit.text)
        used += unit.token_cost
    pool = [u for u in units if not u.mandatory]
    seen_signatures: set[str] = set()
    while pool:
        scored = sorted(((utility(u, chosen), u) for u in pool), key=lambda x: (-x[0], x[1].id))
        best_u, best = scored[0]
        pool.remove(best)
        signature = best.text if best.source_class == "reference_principles" else best.id
        if signature in seen_signatures:
            excluded.append(ExcludedUnit(id=best.id, reason="REDUNDANT: identical abstract principles already selected"))
            continue
        if best_u <= 0:
            excluded.append(ExcludedUnit(id=best.id, reason=f"LOW_UTILITY: {best_u}"))
            continue
        if used + best.token_cost > budget:
            excluded.append(ExcludedUnit(id=best.id, reason="TOKEN_BUDGET"))
            continue
        seen_signatures.add(signature)
        selected.append(best.model_copy(update={"utility": best_u}))
        chosen |= _tokens(best.text)
        used += best.token_cost

    selected_sorted = tuple(sorted(selected, key=lambda u: (not u.mandatory, -u.utility, u.id)))
    excluded_sorted = tuple(sorted(excluded, key=lambda e: e.id))
    body = {"mission_hash": mission.mission_hash, "corpus_version": corpus_version, "budget": budget,
            "selected": [(u.id, u.content_hash) for u in selected_sorted]}
    return ContextPortfolio(status=status, corpus_version=corpus_version, token_budget=budget, total_tokens=used,
                            selected=selected_sorted, excluded=excluded_sorted, reasons=tuple(reasons),
                            context_hash=canonical_hash(body))


# Owned accessibility contract checklist keys -> concrete artifact requirements.
_REQUIREMENT_KEYS = {
    "prefers_reduced_motion": "reduced_motion",
    "visible_focus": "visible_focus",
    "24x24": "target_size_24",
    "text_alternatives": "text_alternatives",
    "contrast_verified": "contrast_aa",
    "headings_landmarks_labels": "landmarks",
    "reflow": "reflow",
}


def derive_requirements(portfolio: ContextPortfolio, corpus_root: Optional[Path] = None) -> tuple[str, ...]:
    """Concrete accessibility requirements from selected *owned* standards only.

    The full standard text is read through the validated loader (selection only
    forwarded a bounded excerpt); reference principles never create
    requirements.
    """
    ids = {u.id for u in portfolio.selected if u.source_class == "owned_standard"}
    if not ids:
        return ()
    try:
        _, loaded = dc.load_validated_corpus(corpus_root)
    except (dc.CorpusIntegrityError, OSError):
        return ()
    found: set[str] = set()
    for entry, text in loaded:
        if entry["corpus_id"] in ids:
            for key, requirement in _REQUIREMENT_KEYS.items():
                if key in text:
                    found.add(requirement)
    return tuple(sorted(found))


__all__ = ["AUTHORITY", "ContextPortfolio", "ContextUnit", "ExcludedUnit", "WEIGHTS", "derive_requirements",
           "mission_query", "select_context"]
