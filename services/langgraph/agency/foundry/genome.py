"""Brief -> CreativeGenome: deterministic, recorded assumptions, contrast-safe palette.

Nothing in the brief is authority. ``project_ref`` is the server-authorized
project; a brief's ``existing_project_id`` that disagrees is refused. Missing
optional fields become ``Assumption`` records rather than silent defaults.
"""

from __future__ import annotations

import colorsys
import random
from typing import Any, Mapping, Optional

from services.langgraph.agency.creative.ir import ResourceBudget
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from .contracts import Assumption, CreativeGenome, Palette, UserBrief
from .grammars import blend, normalise

MARKS = ("circle_bar", "stacked_bars", "split_circle", "triangle_notch", "ring_dot", "quarter_arcs")
FONT_STACKS = {
    "display": ["Inter Display", "Inter", "Helvetica Neue", "Arial", "sans-serif"],
    "text": ["Inter", "Helvetica Neue", "Arial", "sans-serif"],
    "mono": ["JetBrains Mono", "DejaVu Sans Mono", "Menlo", "monospace"],
}
MUTABLE_DIMENSIONS = ("geometry", "spacing", "proportion", "typography", "grid", "color", "texture", "material",
                      "composition", "motion", "lighting", "visual_metaphor")
MIN_TEXT_CONTRAST = 4.5
MIN_GRAPHIC_CONTRAST = 3.0


def _hex(h: float, light: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, light)), max(0.0, min(1.0, s)))
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def derive_palette(seed: int, *, hue: Optional[float] = None) -> Palette:
    """Seeded palette whose ink/paper pass AAA (7:1) and whose accents pass 3:1 against paper."""
    rng = random.Random(seed)
    h = hue if hue is not None else rng.random()
    paper = _hex(h, 0.955, 0.25)
    ink = _hex(h, 0.12, 0.25)
    accent_l, accent_2_l = 0.42, 0.40
    accent = _hex(h + 0.02, accent_l, 0.62)
    accent_2 = _hex(h + 0.45 + rng.random() * 0.1, accent_2_l, 0.45)
    while wcag_contrast_ratio(accent, paper) < MIN_GRAPHIC_CONTRAST + 0.5 and accent_l > 0.1:
        accent_l -= 0.03
        accent = _hex(h + 0.02, accent_l, 0.62)
    while wcag_contrast_ratio(accent_2, paper) < MIN_GRAPHIC_CONTRAST and accent_2_l > 0.1:
        accent_2_l -= 0.03
        accent_2 = _hex(h + 0.5, accent_2_l, 0.45)
    muted = _hex(h, 0.80, 0.12)
    return Palette(ink=ink, paper=paper, accent=accent, accent_2=accent_2, muted=muted)


def contrast_report(p: Palette) -> dict[str, float]:
    return {"ink/paper": wcag_contrast_ratio(p.ink, p.paper), "paper/ink": wcag_contrast_ratio(p.paper, p.ink),
            "accent/paper": wcag_contrast_ratio(p.accent, p.paper), "accent_2/paper": wcag_contrast_ratio(p.accent_2, p.paper),
            "paper/accent": wcag_contrast_ratio(p.paper, p.accent)}


def seed_for(organization: str, project_id: str) -> int:
    return int(canonical_hash({"org": organization, "project": project_id})[:8], 16) % (2**31 - 1)


def compile_genome(brief: UserBrief, *, project_id: str, brand_canon_hash: Optional[str] = None,
                   evidence_refs: tuple[str, ...] = ()) -> CreativeGenome:
    if brief.existing_project_id and brief.existing_project_id != project_id:
        raise PermissionError("brief names a different project than the authorized one")
    assumptions: list[Assumption] = []

    def assume(field: str, value: Any, reason: str) -> Any:
        assumptions.append(Assumption(field=field, value=value, reason=reason))
        return value

    seed = brief.seed if brief.seed is not None else assume("seed", seed_for(brief.organization, project_id),
                                                            "no seed given; derived from organization and project")
    for field, reason in (("offering", "not stated"), ("target_audience", "not stated"), ("business_objective", "not stated"),
                          ("audience_needs", "not stated"), ("desired_action", "not stated")):
        if not getattr(brief, field):
            assume(field, None, f"{reason}; copy uses neutral placeholders that a human must replace")
    weights = normalise(brief.visual_direction) if brief.visual_direction else assume(
        "visual_direction", normalise({}), "no direction given; Swiss editorial default")
    style = blend(weights)

    constraints = dict(brief.brand_constraints)
    if "palette" in constraints:
        palette = Palette(**{k: str(v).lower() for k, v in constraints["palette"].items()})
        locked_palette = True
    else:
        palette = derive_palette(seed, hue=constraints.get("hue"))
        locked_palette = False
        assume("brand_constraints.palette", palette.model_dump(), "no palette supplied; derived from seed with contrast floors")
    report = contrast_report(palette)
    if report["ink/paper"] < MIN_TEXT_CONTRAST:
        raise ValueError(f"palette ink/paper contrast {report['ink/paper']} is below {MIN_TEXT_CONTRAST}:1")
    rng = random.Random(seed)
    mark = constraints.get("mark") or MARKS[rng.randrange(len(MARKS))]
    wordmark = str(constraints.get("wordmark") or brief.organization)
    budget = ResourceBudget()
    invariants = ["brand_name", "geometry_rules.mark"] + (["color_rules.palette"] if locked_palette else [])
    invariants += [f"brand_constraints.{k}" for k in sorted(constraints) if k not in {"palette", "mark", "wordmark", "hue"}]
    return CreativeGenome(
        project_ref=project_id, brand_name=wordmark, brand_canon_hash=brand_canon_hash,
        geometry_rules={"mark": mark, "corner_radius": round(4 + rng.random() * 12, 2), "stroke": round(1.5 + rng.random() * 2.5, 2),
                        "angle": round(style["grid"].get("angle", 0) + (rng.random() - 0.5) * 10, 2),
                        "primitives": style["primitives"]},
        color_rules={"palette": palette.model_dump(), "contrast": report, "locked": locked_palette,
                     "usage": {"text": "ink on paper (or paper on ink)", "graphics": "accent, accent_2 at >= 3:1",
                               "never": "text on accent below 4.5:1"}},
        typography_rules={"stacks": FONT_STACKS, "scale_ratio": 1.333, **style["typography"],
                          "fallback_required": True, "min_body_px": 16},
        layout_rules={"columns": style["grid"].get("columns", 12), "baseline": style["grid"].get("baseline", 8),
                      "margin": style["proportion"]["margin"], "gutter": style["proportion"]["gutter"]},
        composition_rules={"headline_scale": style["proportion"]["headline_scale"], "density": style["proportion"]["density"],
                           "dominant_grammar": style["dominant"]},
        material_rules={"plinth": {"roughness": 0.65, "metallic": 0.0}, "package": {"roughness": 0.45, "metallic": 0.0},
                        "accent_finish": {"roughness": 0.3, "metallic": 0.6 if style["dominant"] == "art_deco" else 0.0}},
        motion_rules={**style["motion"], "base_duration_s": 2.5, "stagger_s": 0.18,
                      "reduced_motion": "static final frame; no parallax, no looping"},
        imagery_rules={"source": "procedural and owned assets only; licensed imagery only when a licence is recorded",
                       "photography": "not generated; synthetic renders are labelled synthetic"},
        interaction_rules={"focus_ring_px": 3, "min_target_px": 44, "states": ["default", "hover", "focus", "active",
                                                                               "disabled", "loading", "error", "success"]},
        novelty_constraints={"max_candidates": budget.max_candidates, "max_generations": budget.max_generations,
                             "mutable_dimensions": list(MUTABLE_DIMENSIONS), "min_parameter_distance": 0.08,
                             "source": "agency.creative.ir.ResourceBudget"},
        accessibility_constraints={"standard": list(brief.accessibility_requirements), "min_text_contrast": MIN_TEXT_CONTRAST,
                                   "min_graphic_contrast": MIN_GRAPHIC_CONTRAST, "reduced_motion_required": True,
                                   "text_scaling_to": "200%", "reflow_min_width_px": 320},
        source_evidence_refs=tuple(evidence_refs) + tuple(f"artifact:{r}" for r in brief.reference_assets),
        deterministic_seed=int(seed), grammar_weights=weights, invariants=tuple(invariants), assumptions=tuple(assumptions),
    )


def genome_get(genome: CreativeGenome, dotted: str) -> Any:
    node: Any = genome.model_dump(mode="json")
    if dotted.startswith("brand_constraints."):
        return None
    for part in dotted.split("."):
        node = node[part] if isinstance(node, Mapping) else None
    return node


__all__ = ["FONT_STACKS", "MARKS", "MUTABLE_DIMENSIONS", "compile_genome", "contrast_report", "derive_palette",
           "genome_get", "seed_for"]
