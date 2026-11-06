"""Project an approved VNEXUS genome into the compilers and renderers that already exist.

The foundry renderers (SVG composition, experience twin, scene, motion) read a
``CreativeGenome``; the UI/UX compiler reads a ``BrandContext``. Rather than
re-implementing either, this module maps resolved genome keys onto their
inputs and records which keys were used, so every downstream decision can cite
the genome values it came from.

Key vocabulary read here (all optional; anything absent is reported, and the
foundry's own documented defaults apply and are recorded as assumptions):

    visual.color.{ink,paper,accent,accent_2,muted}   #rrggbb
    visual.typography.{display,body}                  font family names
    visual.shape_grammar.<grammar_id>                 weight in (0, 1]
    visual.logo.{mark,wordmark}                       one of foundry MARKS / text
    visual.motion.pace                                text
    visual.imagery.style                              text
    verbal.voice.tone                                 text or list of text
    strategy.positioning.{statement,promise}          text
    strategy.audience.{primary,needs}                 text
    experience.accessibility.standard                 text (default WCAG 2.2 AA)
"""

from __future__ import annotations

from typing import Any, Optional

from services.langgraph.agency.foundry.contracts import CreativeGenome, UserBrief
from services.langgraph.agency.foundry.genome import FONT_STACKS, MARKS, compile_genome
from services.langgraph.agency.foundry.grammars import GRAMMARS
from services.langgraph.agency.ui_ux.models import BrandContext, SourceKind

from .genome import Resolution

PALETTE_ROLES = ("ink", "paper", "accent", "accent_2", "muted")


class GenomeProjection:
    """Which genome keys fed which downstream input, plus what had to be assumed."""

    def __init__(self, resolution: Resolution, *, brand_name: str, genome_ref: str):
        self.values = resolution.values
        self.brand_name = brand_name
        self.genome_ref = genome_ref
        self.resolution_hash = resolution.resolution_hash
        self.used: dict[str, Any] = {}
        self.missing: list[str] = []

    def fresh(self) -> "GenomeProjection":
        """A copy with empty usage tracking, so each compile reports only the keys it read."""
        clone = GenomeProjection.__new__(GenomeProjection)
        clone.values, clone.brand_name, clone.genome_ref = self.values, self.brand_name, self.genome_ref
        clone.resolution_hash, clone.used, clone.missing = self.resolution_hash, {}, []
        return clone

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.values and self.values[key] is not None:
            self.used[key] = self.values[key]
            return self.values[key]
        self.missing.append(key)
        return default

    def text(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        if isinstance(value, list):
            return ", ".join(value)
        return str(value) if value is not None else default

    def palette(self) -> Optional[dict[str, str]]:
        found = {role: self.get(f"visual.color.{role}") for role in PALETTE_ROLES}
        if all(isinstance(v, str) for v in found.values()):
            return {k: str(v).lower() for k, v in found.items()}
        return None

    def grammar_weights(self) -> dict[str, float]:
        prefix = "visual.shape_grammar."
        weights = {k[len(prefix):]: float(v) for k, v in self.values.items()
                   if k.startswith(prefix) and k[len(prefix):] in GRAMMARS and isinstance(v, (int, float)) and 0 < float(v) <= 1}
        for k in weights:
            self.used[prefix + k] = self.values[prefix + k]
        if not weights:
            self.missing.append(prefix + "*")
        return weights

    def trace(self) -> dict[str, Any]:
        return {"genome_ref": self.genome_ref, "resolution_hash": self.resolution_hash, "keys_used": dict(sorted(self.used.items())),
                "keys_missing": sorted(set(self.missing))}


def foundry_brief(p: GenomeProjection, *, deliverables: tuple[str, ...], desired_action: str = "", objective: str = "",
                  audience: str = "", seed: Optional[int] = None) -> UserBrief:
    constraints: dict[str, Any] = {"wordmark": p.text("visual.logo.wordmark", p.brand_name)}
    palette = p.palette()
    if palette:
        constraints["palette"] = palette
    mark = p.get("visual.logo.mark")
    if isinstance(mark, str) and mark in MARKS:
        constraints["mark"] = mark
    standard = p.text("experience.accessibility.standard", "WCAG 2.2 AA")
    return UserBrief(organization=p.brand_name[:80], offering=p.text("strategy.positioning.statement")[:300],
                     business_objective=(objective or p.text("strategy.positioning.promise"))[:500],
                     target_audience=(audience or p.text("strategy.audience.primary"))[:300],
                     audience_needs=p.text("strategy.audience.needs")[:500], desired_action=desired_action[:120],
                     deliverable_types=deliverables, visual_direction=p.grammar_weights(), brand_constraints=constraints,
                     accessibility_requirements=(standard,), seed=seed)


def typography_hook(p: GenomeProjection):
    """Put the genome's approved families first in the foundry font stacks (fallbacks stay)."""
    display, body = p.get("visual.typography.display"), p.get("visual.typography.body")

    def apply(genome: CreativeGenome) -> CreativeGenome:
        stacks = {k: list(v) for k, v in genome.typography_rules["stacks"].items()}
        if isinstance(display, str) and display:
            stacks["display"] = [display] + [f for f in FONT_STACKS["display"] if f != display]
        if isinstance(body, str) and body:
            stacks["text"] = [body] + [f for f in FONT_STACKS["text"] if f != body]
        rules = {**genome.typography_rules, "stacks": stacks, "source": "vnexus genome" if (display or body) else "foundry default"}
        return genome.model_copy(update={"typography_rules": rules, "brand_canon_hash": p.resolution_hash,
                                         "source_evidence_refs": tuple(genome.source_evidence_refs) + (f"vnexus:{p.genome_ref}",)})

    return apply


def creative_genome(p: GenomeProjection, *, project_id: str, deliverables: tuple[str, ...] = ("genome",), **brief_kw: Any) -> CreativeGenome:
    """The foundry genome for this projection, with the approved typography applied."""
    brief = foundry_brief(p, deliverables=deliverables, **brief_kw)
    return typography_hook(p)(compile_genome(brief, project_id=project_id, brand_canon_hash=p.resolution_hash))


def brand_context(p: GenomeProjection) -> BrandContext:
    palette = p.palette()
    tone = p.get("verbal.voice.tone")
    return BrandContext(brand_name=p.brand_name, positioning=p.text("strategy.positioning.statement") or None,
                        tone_attributes=list(tone) if isinstance(tone, list) else ([str(tone)] if tone else []),
                        typography_direction=p.text("visual.typography.display") or None,
                        imagery_style=p.text("visual.imagery.style") or None, motion_pace=p.text("visual.motion.pace") or None,
                        reduced_motion_fallback="static final frame; no parallax", palette_hex=list(palette.values()) if palette else [],
                        palette_source=SourceKind.brand_core if palette else SourceKind.compiler_default)


__all__ = ["GenomeProjection", "PALETTE_ROLES", "brand_context", "creative_genome", "foundry_brief", "typography_hook"]
