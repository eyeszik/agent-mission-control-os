"""Post-Surrealist Editorial Modernism (PSEM) as a Foundry profile, not a second Foundry.

PSEM is the ``psem_editorial`` grammar in ``grammars.GRAMMARS`` plus a locked
six-colour palette. A PSEM genome is an ordinary ``CreativeGenome`` compiled by
``genome.compile_genome``; tokens go through ``tokens.token_document`` and the
repository's one DTCG compiler.

The palette has an accessibility trap that this module makes explicit instead of
hoping a designer notices: Signal Red on Paper is 2.86:1 and Amber on Paper is
1.64:1, below even the 3:1 floor for graphics. ``PAIRINGS`` is computed with the
repository's WCAG function, and ``check_usage`` is the rule every PSEM renderer
must pass: accents sit on Charcoal (or carry Charcoal type), never as text or
graphics on Paper.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from services.langgraph.agency.design_tokens import compile_css, hex_to_color
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from .contracts import CreativeGenome, UserBrief
from .genome import compile_genome
from .tokens import PREFIX, token_document

GRAMMAR_ID = "psem_editorial"
PALETTE: dict[str, str] = {
    "charcoal": "#171719",
    "graphite": "#323234",
    "fog": "#838185",
    "paper": "#f0eee9",
    "signal_red": "#ff4c2f",
    "amber": "#ffaa3d",
}
# Foundry palette roles. Graphite has no Foundry role; it is an extra PSEM token.
ROLES = {"ink": "charcoal", "paper": "paper", "accent": "signal_red", "accent_2": "amber", "muted": "fog"}
ACCENTS = ("signal_red", "amber")
TEXT_MIN, LARGE_TEXT_MIN, GRAPHIC_MIN = 4.5, 3.0, 3.0

Use = Literal["text", "large_text", "graphic"]


def _ratio(fg: str, bg: str) -> float:
    return round(wcag_contrast_ratio(PALETTE[fg], PALETTE[bg]), 2)


# Every ordered foreground/background pair with what it may carry under WCAG 2.2 AA.
PAIRINGS: dict[str, dict[str, Any]] = {
    f"{fg}/{bg}": {
        "ratio": _ratio(fg, bg),
        "text": _ratio(fg, bg) >= TEXT_MIN,
        "large_text": _ratio(fg, bg) >= LARGE_TEXT_MIN,
        "graphic": _ratio(fg, bg) >= GRAPHIC_MIN,
    }
    for fg in PALETTE for bg in PALETTE if fg != bg
}


class PsemUsageError(ValueError):
    pass


def check_usage(fg: str, bg: str, use: Use) -> dict[str, Any]:
    """The pairing verdict, or ``PsemUsageError`` when PSEM forbids it."""
    if fg not in PALETTE or bg not in PALETTE:
        raise PsemUsageError(f"{fg}/{bg} is not a PSEM colour pair")
    pair = PAIRINGS[f"{fg}/{bg}"]
    if not pair[use]:
        floor = {"text": TEXT_MIN, "large_text": LARGE_TEXT_MIN, "graphic": GRAPHIC_MIN}[use]
        raise PsemUsageError(f"{fg} on {bg} is {pair['ratio']}:1, below {floor}:1 for {use}")
    return {"pair": f"{fg}/{bg}", "use": use, **pair}


def one_accent(colours_used: set[str], *, approved_second_accent: bool = False) -> None:
    """PSEM allows one accent per composition unless a second one was approved."""
    accents = sorted(set(colours_used) & set(ACCENTS))
    if len(accents) > 1 and not approved_second_accent:
        raise PsemUsageError(f"one accent per composition; found {accents}")


def psem_brief(organization: str, *, offering: str = "", target_audience: str = "", business_objective: str = "",
               desired_action: str = "", audience_needs: str = "", seed: Optional[int] = None,
               existing_project_id: Optional[str] = None) -> UserBrief:
    return UserBrief(
        organization=organization, offering=offering, target_audience=target_audience,
        business_objective=business_objective, desired_action=desired_action, audience_needs=audience_needs,
        deliverable_types=("genome", "design_tokens", "website_section"), visual_direction={GRAMMAR_ID: 1.0},
        brand_constraints={"palette": {role: PALETTE[name] for role, name in ROLES.items()}},
        accessibility_requirements=("WCAG 2.2 AA",), seed=seed, existing_project_id=existing_project_id)


def compile_psem_genome(brief: UserBrief, *, project_id: str, evidence_refs: tuple[str, ...] = ()) -> CreativeGenome:
    """A PSEM genome: the brief's palette must be the PSEM palette and its direction the PSEM grammar."""
    palette = (brief.brand_constraints or {}).get("palette") or {}
    expected = {role: PALETTE[name] for role, name in ROLES.items()}
    if {k: str(v).lower() for k, v in palette.items()} != expected:
        raise PsemUsageError("a PSEM genome needs the locked PSEM palette")
    if set(brief.visual_direction) != {GRAMMAR_ID}:
        raise PsemUsageError("a PSEM genome is directed by the psem_editorial grammar only")
    genome = compile_genome(brief, project_id=project_id, evidence_refs=evidence_refs)
    if genome.color_rules["locked"] is not True or "color_rules.palette" not in genome.invariants:
        raise PsemUsageError("the PSEM palette must be an invariant of the genome")
    return genome


def plate(genome: CreativeGenome, *, title: str, motif_seed: int = 0, width: int = 1200, height: int = 800) -> str:
    """A text-free PSEM plate (procedural, owned): charcoal ground, fog hairlines, one accent motif.

    It reuses the foundry composer's ``psem_editorial`` primitives and SVG writer; every
    primitive is checked against ``check_usage`` before the SVG is written, so a plate can
    never carry an illegal pairing.
    """
    import random

    from .compose import _primitives_for, to_svg
    from .contracts import CompositionIR

    if genome.composition_rules.get("dominant_grammar") != GRAMMAR_ID:
        raise PsemUsageError("a PSEM plate needs a PSEM genome")
    margin = width * float(genome.layout_rules["margin"])
    box = (margin, margin, width - 2 * margin, height - 2 * margin)
    rng = random.Random(f"{genome.deterministic_seed}:plate:{motif_seed}")
    prims = tuple(_primitives_for(GRAMMAR_ID, 7, rng, box, int(genome.layout_rules["columns"]), 0.0))
    ir = CompositionIR(kind="frame", width=width, height=height, background="ink", primitives=prims,
                       genome_hash=genome.content_hash, grammar_weights=dict(genome.grammar_weights), seed=motif_seed,
                       title=title)
    used = {ROLES[r] for r in {p.fill for p in prims} | {p.stroke for p in prims} if r and r != "none"}
    one_accent(used)
    for colour in used - {"charcoal"}:
        check_usage(colour, "charcoal", "graphic")
    return to_svg(ir, genome)


def token_document_psem(genome: CreativeGenome) -> dict:
    """Foundry's token document plus Graphite and the computed pairing rules, as DTCG."""
    doc = token_document(genome)
    doc["color"]["graphite"] = {"$value": hex_to_color(PALETTE["graphite"])}
    doc["$description"] = doc["$description"] + "; PSEM profile"
    doc["$extensions"] = {"amc.psem": {
        "grammar": GRAMMAR_ID,
        "pairings": {k: v for k, v in PAIRINGS.items() if v["graphic"]},
        "rules": ["one accent per composition unless approved", "accents never as text or graphics on paper",
                  "fog on paper only for large text or graphics", "protected whitespace",
                  "macro/meso/micro hierarchy", "reduced-motion path required"],
    }}
    return doc


def compile_psem_tokens(genome: CreativeGenome) -> tuple[dict, str, str]:
    doc = token_document_psem(genome)
    graph, css = compile_css(doc, prefix=PREFIX, source_label=f"psem-genome:{genome.content_hash[:16]}")
    return doc, css, graph.source_hash


__all__ = ["ACCENTS", "GRAMMAR_ID", "PAIRINGS", "PALETTE", "ROLES", "PsemUsageError", "check_usage",
           "compile_psem_genome", "plate", "compile_psem_tokens", "one_accent", "psem_brief", "token_document_psem"]
