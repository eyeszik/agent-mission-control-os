"""Creative Genome Foundry: seeded candidates, mutation, crossbreeding, comparison and lineage.

A candidate is a set of *overrides* on top of a genome, never an edit of the
genome itself, so approved invariants (brand name, mark, a locked palette) are
untouchable by construction. Population and generations are capped by the
creative runtime's ``ResourceBudget`` (<= 4 candidates, <= 2 generations); the
cap is enforced here, not just documented.

Three different things are kept apart:

* ``constraints``  objective checks (palette conformance, invariants, contrast);
* ``diversity``    a computed parameter/shape distance between candidates;
* ``feedback``     what a named human actually said, recorded verbatim.

Nothing here predicts audience preference.
"""

from __future__ import annotations

import random
from typing import Optional, Sequence

from pydantic import Field

from services.langgraph.agency.creative.ir import ResourceBudget
from services.langgraph.agency.execution.canonical import canonical_hash

from . import compose
from .contracts import CreativeGenome, _Strict
from .genome import MUTABLE_DIMENSIONS
from .grammars import GRAMMARS, normalise

POSTER_DIMS = {"geometry": ("angle", "variant_seed"), "spacing": ("margin",), "proportion": ("headline_scale",),
               "typography": ("display_weight",), "grid": ("columns",), "texture": ("density",),
               "composition": ("grammar_weights", "variant_seed"), "visual_metaphor": ("variant_seed",), "color": ("emphasis",),
               "material": ("material",), "motion": ("motion_energy",), "lighting": ("lighting",)}


class FoundryCapExceeded(ValueError):
    pass


class Candidate(_Strict):
    candidate_id: str
    genome_hash: str
    generation: int = Field(ge=0)
    parents: tuple[str, ...] = ()
    mutations: tuple[dict, ...] = ()
    params: dict
    ir_hash: Optional[str] = None
    svg_sha256: Optional[str] = None


def _cid(genome_hash: str, params: dict, parents: Sequence[str]) -> str:
    return "cand-" + canonical_hash({"g": genome_hash, "p": params, "parents": list(parents)})[:20]


def base_params(genome: CreativeGenome, variant_seed: int = 0) -> dict:
    return {"variant_seed": variant_seed, "angle": genome.geometry_rules["angle"], "margin": genome.layout_rules["margin"],
            "headline_scale": genome.composition_rules["headline_scale"],
            "display_weight": genome.typography_rules.get("display_weight", 700), "columns": genome.layout_rules["columns"],
            "density": genome.composition_rules["density"], "grammar_weights": dict(genome.grammar_weights),
            "emphasis": "accent", "material": genome.material_rules["package"], "motion_energy": genome.motion_rules["energy"],
            "lighting": "soft_key"}


def generate_candidate(genome: CreativeGenome, *, variant_seed: int = 0, params: Optional[dict] = None,
                       parents: Sequence[str] = (), mutations: Sequence[dict] = (), generation: int = 0) -> Candidate:
    p = params or base_params(genome, variant_seed)
    return Candidate(candidate_id=_cid(genome.content_hash, p, parents), genome_hash=genome.content_hash, generation=generation,
                     parents=tuple(parents), mutations=tuple(mutations), params=p)


def mutate_candidate(genome: CreativeGenome, parent: Candidate, *, dimensions: Sequence[str], seed: int,
                     strength: float = 0.5) -> Candidate:
    _check_generation(genome, parent.generation + 1)
    unknown = sorted(set(dimensions) - set(MUTABLE_DIMENSIONS))
    if unknown:
        raise ValueError(f"unknown mutation dimension(s): {unknown}")
    rng = random.Random(f"{parent.candidate_id}:{seed}:{','.join(sorted(dimensions))}")
    p = dict(parent.params)
    log = []
    for dim in sorted(dimensions):
        for key in POSTER_DIMS[dim]:
            before = p[key]
            if key == "variant_seed":
                p[key] = rng.randrange(1, 10_000)
            elif key == "angle":
                p[key] = round(before + (rng.random() - 0.5) * 30 * strength, 2)
            elif key == "margin":
                p[key] = round(min(0.16, max(0.04, before * (1 + (rng.random() - 0.5) * strength))), 4)
            elif key == "headline_scale":
                p[key] = round(min(0.16, max(0.05, before * (1 + (rng.random() - 0.5) * strength))), 4)
            elif key == "display_weight":
                p[key] = rng.choice([w for w in (500, 600, 700, 800, 900) if w != before])
            elif key == "columns":
                p[key] = rng.choice([c for c in (4, 6, 8, 12) if c != before])
            elif key == "density":
                p[key] = round(min(0.8, max(0.1, before + (rng.random() - 0.5) * strength)), 3)
            elif key == "grammar_weights":
                extra = rng.choice(sorted(set(GRAMMARS) - set(before)))
                w = {**before, extra: round(0.15 + 0.35 * strength * rng.random(), 3)}
                p[key] = normalise(w)
            elif key == "emphasis":
                p[key] = "accent_2" if before == "accent" else "accent"
            elif key == "material":
                p[key] = {**before, "roughness": round(min(1, max(0, before["roughness"] + (rng.random() - 0.5) * strength)), 3)}
            elif key == "motion_energy":
                p[key] = round(min(1, max(0.05, before + (rng.random() - 0.5) * strength)), 3)
            elif key == "lighting":
                p[key] = rng.choice([v for v in ("soft_key", "hard_side", "top_down", "rim_glow") if v != before])
            log.append({"dimension": dim, "parameter": key, "before": before, "after": p[key]})
    return generate_candidate(genome, params=p, parents=(parent.candidate_id,), mutations=log, generation=parent.generation + 1)


def crossbreed_candidates(genome: CreativeGenome, a: Candidate, b: Candidate, *, seed: int) -> Candidate:
    _check_generation(genome, max(a.generation, b.generation) + 1)
    rng = random.Random(f"{a.candidate_id}:{b.candidate_id}:{seed}")
    p, log = {}, []
    for key in sorted(a.params):
        src = a if rng.random() < 0.5 else b
        p[key] = src.params[key]
        log.append({"parameter": key, "from": src.candidate_id})
    return generate_candidate(genome, params=p, parents=(a.candidate_id, b.candidate_id), mutations=log,
                              generation=max(a.generation, b.generation) + 1)


def fork_candidate(genome: CreativeGenome, parent: Candidate, *, edits: dict) -> Candidate:
    """A human edit of allowed parameters becomes a new candidate; the parent is untouched."""
    allowed = set(base_params(genome))
    bad = sorted(set(edits) - allowed)
    if bad:
        raise ValueError(f"not an editable parameter: {bad}")
    p = {**parent.params, **edits}
    log = [{"parameter": k, "before": parent.params.get(k), "after": v, "by": "human_edit"} for k, v in sorted(edits.items())]
    return generate_candidate(genome, params=p, parents=(parent.candidate_id,), mutations=log, generation=parent.generation)


def _check_generation(genome: CreativeGenome, generation: int) -> None:
    cap = int(genome.novelty_constraints.get("max_generations", ResourceBudget().max_generations))
    if generation > cap:
        raise FoundryCapExceeded(f"generation {generation} exceeds the creative runtime cap of {cap}")


def check_population(genome: CreativeGenome, n: int) -> None:
    cap = int(genome.novelty_constraints.get("max_candidates", ResourceBudget().max_candidates))
    if n > cap:
        raise FoundryCapExceeded(f"population {n} exceeds the creative runtime cap of {cap}")


def render_candidate(genome: CreativeGenome, cand: Candidate, *, headline: str, subhead: str = "", cta: str = "",
                     meta: str = "", width: int = 1200, height: int = 1600) -> tuple[Candidate, compose.CompositionIR, str]:
    overrides = {k: cand.params[k] for k in ("grammar_weights", "margin", "density", "columns", "angle", "headline_scale",
                                              "display_weight")}
    ir = compose.poster(genome, headline=headline, subhead=subhead, cta=cta, meta=meta, width=width, height=height,
                        variant_seed=int(cand.params["variant_seed"]), overrides=overrides)
    if cand.params.get("emphasis") == "accent_2":
        swap = {"accent": "accent_2", "accent_2": "accent"}
        ir = ir.model_copy(update={"primitives": tuple(p.model_copy(update={"fill": swap.get(p.fill, p.fill),
                                                                              "stroke": swap.get(p.stroke, p.stroke)})
                                                       for p in ir.primitives)})
    svg = compose.to_svg(ir, genome)
    import hashlib

    done = cand.model_copy(update={"ir_hash": ir.content_hash, "svg_sha256": hashlib.sha256(svg.encode()).hexdigest()})
    return done, ir, svg


def _numeric(p: dict) -> list[float]:
    return [p["angle"] / 90, p["margin"] * 5, p["headline_scale"] * 6, p["display_weight"] / 900, p["columns"] / 12, p["density"]]


def compare_candidates(a: tuple[Candidate, compose.CompositionIR], b: tuple[Candidate, compose.CompositionIR]) -> dict:
    """Computed design diversity. Not a quality or preference score."""
    pa, pb = a[0].params, b[0].params
    param = sum((x - y) ** 2 for x, y in zip(_numeric(pa), _numeric(pb))) ** 0.5 / len(_numeric(pa)) ** 0.5
    wa, wb = pa["grammar_weights"], pb["grammar_weights"]
    grammar = sum(abs(wa.get(k, 0) - wb.get(k, 0)) for k in set(wa) | set(wb)) / 2
    sa, sb = compose.shape_signature(a[1]), compose.shape_signature(b[1])
    inter = sum(min(sa.get(k, 0), sb.get(k, 0)) for k in set(sa) | set(sb))
    union = sum(max(sa.get(k, 0), sb.get(k, 0)) for k in set(sa) | set(sb)) or 1
    return {"parameter_distance": round(param, 4), "grammar_distance": round(grammar, 4),
            "shape_jaccard_distance": round(1 - inter / union, 4), "kind": "COMPUTED_DIVERSITY (not a preference score)"}


def lineage(candidates: Sequence[Candidate]) -> list[dict]:
    return [{"candidate_id": c.candidate_id, "generation": c.generation, "parents": list(c.parents),
             "mutations": [m.get("dimension") or m.get("by") or "crossbreed" for m in c.mutations][:12],
             "ir_hash": c.ir_hash, "svg_sha256": c.svg_sha256} for c in candidates]


def record_feedback(candidate_id: str, *, reviewer: str, text: str, decision: Optional[str] = None) -> dict:
    """Actual human feedback, verbatim and attributed. There is no synthetic counterpart."""
    if not reviewer or not text.strip():
        raise ValueError("feedback needs a named reviewer and their words")
    return {"candidate_id": candidate_id, "reviewer": reviewer, "text": text.strip()[:2000], "decision": decision,
            "kind": "HUMAN_FEEDBACK"}


__all__ = ["Candidate", "FoundryCapExceeded", "POSTER_DIMS", "base_params", "check_population", "compare_candidates",
           "crossbreed_candidates", "fork_candidate", "generate_candidate", "lineage", "mutate_candidate", "record_feedback",
           "render_candidate"]
