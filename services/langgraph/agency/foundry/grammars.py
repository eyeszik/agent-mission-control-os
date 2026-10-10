"""Reusable visual grammars and weighted blending.

A grammar is a set of composition operators, proportions and constraints, not a
picture. Historical movements are named as *influences* (``lineage_note``); no
grammar reproduces a specific artwork, logo or trademark, and ``anti_patterns``
names what each grammar must avoid, including imitation of known marks.

``blend`` normalises weights and returns numeric parameters as weighted means
and categorical ones from the dominant grammar, so a blend is deterministic and
inspectable.
"""

from __future__ import annotations

from typing import Mapping

from .contracts import VisualGrammar

_COMMON_ANTI = ("copying a known artwork, logo or trademark", "text below WCAG contrast", "decoration over operable controls")


def _g(grammar_id, name, ops, proportion, grid, typography, palette_logic, texture, primitives, motion, axes, anti,
       note="Contemporary vocabulary; no single historical source."):
    return VisualGrammar(grammar_id=grammar_id, name=name, composition_operators=ops, proportion=proportion, grid=grid,
                         typography=typography, palette_logic=palette_logic, texture_logic=texture, primitives=primitives,
                         motion=motion, variation_axes=axes, anti_patterns=anti + _COMMON_ANTI, lineage_note=note)


GRAMMARS: dict[str, VisualGrammar] = {g.grammar_id: g for g in (
    _g("swiss_editorial", "Swiss editorial", ("modular_grid", "flush_left_stack", "rule_division", "accent_block"),
       {"margin": 0.08, "gutter": 0.02, "headline_scale": 0.11, "density": 0.35}, {"columns": 12, "baseline": 8},
       {"display_weight": 700, "case": "sentence", "tracking": -0.02, "family": "display"},
       "ink on paper, one accent", "none", ("bar", "rect", "line"), {"easing": "ease_out", "energy": 0.3},
       ("grid", "spacing", "typography", "composition"), ("centered symmetric layouts", "ornament"),
       "Influenced by mid-century International Typographic Style grids."),
    _g("bauhaus_geometry", "Bauhaus geometry", ("primary_shapes", "colour_fields", "diagonal_balance"),
       {"margin": 0.07, "gutter": 0.03, "headline_scale": 0.09, "density": 0.55}, {"columns": 6, "baseline": 12},
       {"display_weight": 800, "case": "upper", "tracking": 0.04, "family": "display"},
       "accent and accent_2 as fields", "flat", ("circle", "rect", "triangle", "bar"), {"easing": "spring", "energy": 0.6},
       ("geometry", "color", "proportion", "composition"), ("gradients", "drop shadows"),
       "Influenced by early-20th-century geometric design education."),
    _g("constructivist", "Constructivist composition", ("diagonal_axis", "wedge", "rotated_type"),
       {"margin": 0.06, "gutter": 0.02, "headline_scale": 0.12, "density": 0.5}, {"columns": 8, "baseline": 8, "angle": -24},
       {"display_weight": 900, "case": "upper", "tracking": 0.02, "family": "display"},
       "ink, paper, one strong accent", "flat", ("bar", "triangle", "circle"), {"easing": "ease_in_out", "energy": 0.8},
       ("geometry", "composition", "typography"), ("political iconography", "photomontage of real people"),
       "Influenced by 1920s diagonal poster composition."),
    _g("art_deco", "Art Deco ornament", ("bilateral_symmetry", "radial_fan", "stepped_frame"),
       {"margin": 0.09, "gutter": 0.02, "headline_scale": 0.08, "density": 0.45}, {"columns": 2, "baseline": 8, "symmetry": True},
       {"display_weight": 500, "case": "upper", "tracking": 0.18, "family": "display"},
       "accent as metallic stand-in, muted grounds", "line", ("fan", "arc", "line", "rect"), {"easing": "ease_in_out", "energy": 0.35},
       ("geometry", "texture", "proportion"), ("asymmetry for its own sake",),
       "Influenced by 1920s-30s decorative geometry."),
    _g("modern_minimalism", "Modern minimalism", ("negative_space", "single_focus", "quiet_type"),
       {"margin": 0.14, "gutter": 0.03, "headline_scale": 0.06, "density": 0.15}, {"columns": 4, "baseline": 8},
       {"display_weight": 500, "case": "sentence", "tracking": 0.0, "family": "text"},
       "paper dominant, single small accent", "none", ("circle", "line"), {"easing": "ease_out", "energy": 0.15},
       ("spacing", "proportion", "typography"), ("more than three elements", "busy texture")),
    _g("retro_computing", "Retro computing", ("pixel_grid", "scanline", "terminal_type"),
       {"margin": 0.06, "gutter": 0.01, "headline_scale": 0.08, "density": 0.5}, {"columns": 32, "baseline": 4, "pixel": 16},
       {"display_weight": 700, "case": "upper", "tracking": 0.06, "family": "mono"},
       "ink ground, accent glyphs", "scanlines", ("pixel_block", "line"), {"easing": "linear", "energy": 0.5},
       ("grid", "texture", "typography"), ("blurry anti-aliased pixels", "copied game sprites"),
       "Influenced by early personal-computer displays."),
    _g("tactile_paper", "Tactile paper", ("layered_sheets", "offset_shadow", "torn_edge"),
       {"margin": 0.08, "gutter": 0.02, "headline_scale": 0.09, "density": 0.4}, {"columns": 6, "baseline": 8},
       {"display_weight": 700, "case": "sentence", "tracking": -0.01, "family": "display"},
       "muted and paper layers, accent cutout", "grain", ("card", "rect", "dots"), {"easing": "ease_out", "energy": 0.3},
       ("texture", "material", "composition"), ("glossy surfaces",), "Influenced by cut-paper collage craft."),
    _g("dimensional_glass", "Dimensional glass", ("translucent_layers", "soft_depth", "rounded_panels"),
       {"margin": 0.08, "gutter": 0.03, "headline_scale": 0.08, "density": 0.4}, {"columns": 6, "baseline": 8},
       {"display_weight": 600, "case": "sentence", "tracking": -0.01, "family": "text"},
       "accent tints at low opacity over paper", "translucency", ("card", "circle"), {"easing": "ease_in_out", "energy": 0.4},
       ("material", "lighting", "composition"), ("glass behind body text", "contrast below AA")),
    _g("synthetic_futurism", "Synthetic futurism", ("concentric_rings", "orbit_lines", "precision_type"),
       {"margin": 0.07, "gutter": 0.02, "headline_scale": 0.07, "density": 0.45}, {"columns": 12, "baseline": 8},
       {"display_weight": 600, "case": "upper", "tracking": 0.12, "family": "text"},
       "ink ground, accent lines", "fine_lines", ("ring", "arc", "line", "circle"), {"easing": "ease_in_out", "energy": 0.6},
       ("geometry", "lighting", "motion"), ("chrome clichés", "sci-fi franchise motifs")),
    _g("cinematic_typography", "Cinematic typography", ("letterbox", "full_bleed_headline", "credit_block"),
       {"margin": 0.06, "gutter": 0.02, "headline_scale": 0.16, "density": 0.25}, {"columns": 12, "baseline": 8},
       {"display_weight": 800, "case": "upper", "tracking": -0.03, "family": "display"},
       "ink ground, paper type, accent rule", "none", ("bar", "line"), {"easing": "ease_in_out", "energy": 0.5},
       ("typography", "proportion", "composition"), ("film studio logos", "title designs of real films")),
    _g("experimental_collage", "Experimental collage", ("rotated_fragments", "scale_contrast", "overlap"),
       {"margin": 0.05, "gutter": 0.01, "headline_scale": 0.1, "density": 0.7}, {"columns": 5, "baseline": 6},
       {"display_weight": 800, "case": "mixed", "tracking": 0.0, "family": "display"},
       "all roles, high contrast", "grain", ("rect", "circle", "triangle", "dots"), {"easing": "spring", "energy": 0.7},
       ("composition", "texture", "color"), ("unlicensed photo fragments",)),
    _g("spatial_interface", "Spatial interface systems", ("depth_cards", "layered_panels", "focus_ring"),
       {"margin": 0.08, "gutter": 0.03, "headline_scale": 0.07, "density": 0.4}, {"columns": 8, "baseline": 8},
       {"display_weight": 600, "case": "sentence", "tracking": -0.01, "family": "text"},
       "paper panels, accent focus", "soft_shadow", ("card", "circle", "line"), {"easing": "spring", "energy": 0.45},
       ("material", "lighting", "spacing"), ("panels obscuring controls", "motion without reduced-motion path")),
)}

DEFAULT_WEIGHTS = {"swiss_editorial": 1.0}


def normalise(weights: Mapping[str, float]) -> dict[str, float]:
    unknown = sorted(set(weights) - set(GRAMMARS))
    if unknown:
        raise ValueError(f"unknown visual grammar(s): {unknown}")
    clean = {k: float(v) for k, v in weights.items() if float(v) > 0} or dict(DEFAULT_WEIGHTS)
    total = sum(clean.values())
    return {k: round(v / total, 6) for k, v in sorted(clean.items())}


def dominant(weights: Mapping[str, float]) -> VisualGrammar:
    w = normalise(weights)
    return GRAMMARS[max(sorted(w), key=lambda k: w[k])]


def blend(weights: Mapping[str, float]) -> dict:
    w = normalise(weights)
    keys = {k for g in w for k in GRAMMARS[g].proportion}
    proportion = {k: round(sum(GRAMMARS[g].proportion.get(k, 0) * wt for g, wt in w.items()), 6) for k in sorted(keys)}
    lead = dominant(w)
    return {"weights": w, "dominant": lead.grammar_id, "proportion": proportion, "grid": lead.grid,
            "typography": lead.typography, "primitives": sorted({p for g in w for p in GRAMMARS[g].primitives}),
            "motion": lead.motion, "anti_patterns": sorted({a for g in w for a in GRAMMARS[g].anti_patterns})}


__all__ = ["DEFAULT_WEIGHTS", "GRAMMARS", "blend", "dominant", "normalise"]
