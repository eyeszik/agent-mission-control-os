"""Selectable style profiles. A profile shapes layout and appearance; it never carries brand authority.

Only profiles with a real compiler path are ``IMPLEMENTED``; the rest of the requested
catalogue is listed as ``PROPOSED`` and refused by the compiler rather than approximated.
The Post-Surrealist profile takes its palette from ``foundry.psem`` (the one PSEM
owner) and is selectable, not a global default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.foundry import psem

from .contracts import BrandIR, CapabilityState

Motif = Literal["rings", "bars", "modules", "axis"]


@dataclass(frozen=True)
class StyleProfile:
    profile_id: str
    name: str
    state: CapabilityState
    grid_columns: int = 12
    margin: float = 0.08              # fraction of the short side
    headline_scale: float = 0.075     # font size as a fraction of width
    motif: Motif = "rings"
    grain: bool = False
    negative_space: float = 0.45
    headline_weight: int = 700
    annotation: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)


_IMPLEMENTED = (
    StyleProfile("post-surrealist-editorial", "Post-Surrealist Editorial", CapabilityState.IMPLEMENTED_VERIFIED,
                 grid_columns=12, margin=0.07, headline_scale=0.09, motif="rings", grain=True, negative_space=0.55,
                 notes=("one signal accent", "monumental negative space", "optical asymmetry", "matte, fine grain",
                        "technical annotation", "neo-grotesk type")),
    StyleProfile("swiss-editorial-modernism", "Swiss Editorial Modernism", CapabilityState.IMPLEMENTED_VERIFIED,
                 grid_columns=12, margin=0.08, headline_scale=0.08, motif="bars", grain=False, negative_space=0.45,
                 notes=("modular grid", "flush-left type", "single accent")),
    StyleProfile("technical-minimalism", "Technical Minimalism", CapabilityState.IMPLEMENTED_VERIFIED,
                 grid_columns=8, margin=0.1, headline_scale=0.06, motif="axis", grain=False, negative_space=0.6,
                 headline_weight=500, notes=("hairline rules", "dense annotation", "restrained palette")),
    StyleProfile("geometric-infographics", "Geometric Infographics", CapabilityState.IMPLEMENTED_VERIFIED,
                 grid_columns=6, margin=0.08, headline_scale=0.07, motif="modules", grain=False, negative_space=0.35,
                 notes=("modular blocks", "legible hierarchy")),
)
_PROPOSED = ("Experimental Brand Geometry", "Premium Product Vector", "Atmospheric Monochrome", "Material-Rich Abstraction",
             "Modular Identity Systems", "Contemporary Typographic Poster", "Analog Conceptual Photography", "Digital Collage",
             "Cinematic Composition", "Optical Surrealism", "Retro Digital Broadcast", "Photographic Vector Realism")

PROFILES: dict[str, StyleProfile] = {p.profile_id: p for p in _IMPLEMENTED}
for _name in _PROPOSED:
    _pid = _name.lower().replace(" ", "-")
    PROFILES[_pid] = StyleProfile(_pid, _name, CapabilityState.PROPOSED, notes=("listed; no compiler path yet",))


class ProfileUnavailable(ValueError):
    pass


def get_profile(profile_id: str) -> StyleProfile:
    p = PROFILES.get(profile_id)
    if p is None:
        raise ProfileUnavailable(f"unknown style profile {profile_id!r}")
    if p.state != CapabilityState.IMPLEMENTED_VERIFIED:
        raise ProfileUnavailable(f"style profile {profile_id!r} is {p.state.value}: no compiler path, not approximated")
    return p


def psem_brand(*, approval_ref: Optional[str] = None) -> BrandIR:
    """BrandIR projection of the code-owned PSEM palette. ``approved`` only with an approval reference."""
    return BrandIR(source="foundry.psem.PALETTE", source_hash=canonical_hash(psem.PALETTE), approved=approval_ref is not None,
                   palette=dict(psem.PALETTE),
                   roles={"ground": "paper", "ink": "charcoal", "secondary": "graphite", "muted": "fog",
                          "accent": "signal_red", "accent_2": "amber", "night": "charcoal"},
                   typography=("Helvetica Neue", "Arial", "sans-serif"),
                   protected_invariants=("palette", "single_signal_accent", "accent_never_on_paper"),
                   allowed_variations=("composition", "motif", "headline_scale", "annotation"),
                   max_signal_accents=1)


def catalogue() -> list[dict]:
    return [{"profile_id": p.profile_id, "name": p.name, "state": p.state.value, "notes": list(p.notes)} for p in PROFILES.values()]


__all__ = ["PROFILES", "ProfileUnavailable", "StyleProfile", "catalogue", "get_profile", "psem_brand"]
