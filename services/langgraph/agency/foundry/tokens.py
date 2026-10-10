"""CreativeGenome -> DTCG token document, compiled by the repository's one token compiler.

This module only *authors* the DTCG document from the genome. Validation,
alias resolution and CSS generation are ``agency.design_tokens``'s job; there
is no second compiler here.
"""

from __future__ import annotations

from services.langgraph.agency.design_tokens import compile_css, hex_to_color

from .contracts import CreativeGenome

PREFIX = "amc"


def token_document(genome: CreativeGenome) -> dict:
    pal = genome.palette.roles()
    stacks = genome.typography_rules["stacks"]
    radius = float(genome.geometry_rules["corner_radius"])
    energy = float(genome.motion_rules.get("energy", 0.3))
    return {
        "$description": f"Generated from CreativeGenome {genome.content_hash[:16]} for {genome.brand_name}",
        "color": {"$type": "color", **{role: {"$value": hex_to_color(hex_)} for role, hex_ in sorted(pal.items())}},
        "font": {"$type": "fontFamily", "display": {"$value": stacks["display"]}, "text": {"$value": stacks["text"]},
                 "mono": {"$value": stacks["mono"]}},
        "weight": {"$type": "fontWeight", "display": {"$value": int(genome.typography_rules.get("display_weight", 700))},
                   "text": {"$value": 400}},
        "space": {"$type": "dimension", **{f"s{i}": {"$value": {"value": v, "unit": "rem"}}
                                           for i, v in enumerate((0.25, 0.5, 1, 1.5, 2, 3, 4), start=1)}},
        "radius": {"$type": "dimension", "control": {"$value": {"value": round(min(radius, 12), 2), "unit": "px"}},
                   "panel": {"$value": {"value": round(radius * 1.5, 2), "unit": "px"}}},
        "focus": {"$type": "dimension", "ring": {"$value": {"value": genome.interaction_rules["focus_ring_px"], "unit": "px"}}},
        "target": {"$type": "dimension", "min": {"$value": {"value": genome.interaction_rules["min_target_px"], "unit": "px"}}},
        "motion": {"duration": {"$type": "duration", "$value": {"value": round(200 + 400 * energy), "unit": "ms"}},
                   "easing": {"$type": "cubicBezier", "$value": [0.2, 0.0, 0.0, 1.0]}},
    }


def compile_tokens(genome: CreativeGenome) -> tuple[dict, str, str]:
    """Returns (DTCG document, CSS, source hash) -- compiled by ``agency.design_tokens.compile_css``."""
    doc = token_document(genome)
    graph, css = compile_css(doc, prefix=PREFIX, source_label=f"creative-genome:{genome.content_hash[:16]}")
    return doc, css, graph.source_hash


__all__ = ["PREFIX", "compile_tokens", "token_document"]
