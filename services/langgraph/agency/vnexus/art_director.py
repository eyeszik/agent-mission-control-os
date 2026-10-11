"""VNEXUS art director: strategic intent -> a constrained, evidence-labelled art direction brief.

Every statement in the brief is a ``Claim`` with one of four classes, so a
reader can tell what is required from what was decided, suggested or assumed:

    VERIFIED_REQUIREMENT    an approved genome value or an explicit request field
    INFERRED_DECISION       derived deterministically from those (rule cited)
    EXPERIMENTAL_SUGGESTION a variation worth exploring, explicitly optional
    UNSUPPORTED_ASSUMPTION  something the brief needed but nobody supplied

The rubric separates what can be measured from what needs a person. Scores
are produced only for measured criteria; subjective criteria return
``HUMAN_REQUIRED`` and are never folded into a number.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import Field

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.foundry.grammars import dominant, normalise
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from .bridge import GenomeProjection
from .genome import _Strict

ART_DIRECTOR_VERSION = "amc-vnexus-art-director/v1"


class ClaimClass(str, Enum):
    VERIFIED_REQUIREMENT = "VERIFIED_REQUIREMENT"
    INFERRED_DECISION = "INFERRED_DECISION"
    EXPERIMENTAL_SUGGESTION = "EXPERIMENTAL_SUGGESTION"
    UNSUPPORTED_ASSUMPTION = "UNSUPPORTED_ASSUMPTION"


class Medium(str, Enum):
    POSTER = "POSTER"
    SOCIAL = "SOCIAL"
    WEB = "WEB"
    VIDEO = "VIDEO"
    PACKAGING = "PACKAGING"
    PRESENTATION = "PRESENTATION"
    IDENTITY = "IDENTITY"


class RightsStatus(str, Enum):
    OWNED = "OWNED"
    LICENSED = "LICENSED"
    UNKNOWN = "UNKNOWN"


class Reference(_Strict):
    ref: str = Field(min_length=1, max_length=300)
    rights: RightsStatus
    licence_ref: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=300)


class PlatformSpec(_Strict):
    name: str
    width: int = Field(gt=0, le=16384)
    height: int = Field(gt=0, le=16384)
    formats: tuple[str, ...] = ("png",)
    safe_margin: float = Field(default=0.06, ge=0, le=0.25)
    max_bytes: Optional[int] = Field(default=None, gt=0)


# Commonly published platform presets. They change; a request-supplied spec always wins
# and these are labelled INFERRED (not verified) when used.
PLATFORM_PRESETS: dict[str, PlatformSpec] = {
    "social.portrait_4x5": PlatformSpec(name="social.portrait_4x5", width=1080, height=1350),
    "social.square": PlatformSpec(name="social.square", width=1080, height=1080),
    "social.story_9x16": PlatformSpec(name="social.story_9x16", width=1080, height=1920, safe_margin=0.12),
    "web.open_graph": PlatformSpec(name="web.open_graph", width=1200, height=630),
    "video.landscape_16x9": PlatformSpec(name="video.landscape_16x9", width=1920, height=1080, formats=("mp4",)),
    "print.poster_a_ratio": PlatformSpec(name="print.poster_a_ratio", width=1200, height=1697, formats=("svg", "pdf")),
    "presentation.16x9": PlatformSpec(name="presentation.16x9", width=1920, height=1080, formats=("svg", "pdf")),
}


class ArtDirectionRequest(_Strict):
    objective: str = Field(min_length=1, max_length=500)
    audience: str = Field(default="", max_length=300)
    medium: Medium
    brief: str = Field(default="", max_length=2000)
    platform: Optional[str] = None
    platform_spec: Optional[PlatformSpec] = None
    references: tuple[Reference, ...] = Field(default=(), max_length=30)
    budget_ceiling_minor: Optional[int] = Field(default=None, ge=0)
    exploration: bool = False


class Claim(_Strict):
    section: str
    statement: str
    claim_class: ClaimClass
    basis: tuple[str, ...] = ()
    rationale: str = ""


def _claims_for_color(p: GenomeProjection) -> list[Claim]:
    out: list[Claim] = []
    palette = p.palette()
    if palette is None:
        return [Claim(section="color_system", statement="Palette is not fully defined in the approved genome",
                      claim_class=ClaimClass.UNSUPPORTED_ASSUMPTION, basis=("genome:visual.color.*",),
                      rationale="ink, paper, accent, accent_2 and muted are all required for production")]
    for role, value in palette.items():
        out.append(Claim(section="color_system", statement=f"{role} is {value}", claim_class=ClaimClass.VERIFIED_REQUIREMENT,
                         basis=(f"genome:visual.color.{role}",)))
    for fg, bg, floor, use in (("ink", "paper", 4.5, "body text"), ("accent", "paper", 3.0, "graphic elements and large text")):
        ratio = wcag_contrast_ratio(palette[fg], palette[bg])
        out.append(Claim(section="color_system", statement=f"Use {fg} on {bg} for {use} ({ratio}:1)" if ratio >= floor else
                         f"Do not use {fg} on {bg} for {use} ({ratio}:1 is below {floor}:1)", claim_class=ClaimClass.INFERRED_DECISION,
                         basis=(f"genome:visual.color.{fg}", f"genome:visual.color.{bg}"), rationale="WCAG 2.2 contrast ratio"))
    return out


def _composition(p: GenomeProjection, req: ArtDirectionRequest) -> list[Claim]:
    weights = p.grammar_weights()
    if not weights:
        return [Claim(section="composition_system", statement="No approved shape grammar; Swiss editorial default would apply",
                      claim_class=ClaimClass.UNSUPPORTED_ASSUMPTION, basis=("genome:visual.shape_grammar.*",))]
    weights = normalise(weights)
    g = dominant(weights)
    lead = g.grammar_id
    out = [Claim(section="composition_system", statement=f"Lead grammar: {g.name} ({weights[lead]:.0%})",
                 claim_class=ClaimClass.VERIFIED_REQUIREMENT, basis=(f"genome:visual.shape_grammar.{lead}",)),
           Claim(section="composition_system", statement="Operators: " + ", ".join(g.composition_operators),
                 claim_class=ClaimClass.INFERRED_DECISION, basis=(f"grammar:{lead}",), rationale="operators declared by the grammar")]
    out.append(Claim(section="visual_hierarchy", statement="One focal element, then headline, then supporting copy, then action",
                     claim_class=ClaimClass.INFERRED_DECISION, basis=(f"grammar:{lead}", f"medium:{req.medium.value}"),
                     rationale="single-entry reading order for a constrained format"))
    if req.exploration:
        for axis in g.variation_axes[:3]:
            out.append(Claim(section="composition_system", statement=f"Explore variation along '{axis}'",
                             claim_class=ClaimClass.EXPERIMENTAL_SUGGESTION, basis=(f"grammar:{lead}",),
                             rationale="declared variation axis; optional, needs human review"))
    return out


def _typography(p: GenomeProjection) -> list[Claim]:
    out = []
    for key, label in (("visual.typography.display", "Display face"), ("visual.typography.body", "Body face")):
        value = p.get(key)
        out.append(Claim(section="typography_direction", statement=f"{label}: {value}", claim_class=ClaimClass.VERIFIED_REQUIREMENT,
                         basis=(f"genome:{key}",)) if value else
                   Claim(section="typography_direction", statement=f"{label} not specified", claim_class=ClaimClass.UNSUPPORTED_ASSUMPTION,
                         basis=(f"genome:{key}",), rationale="fallback stacks would be used"))
    out.append(Claim(section="typography_direction", statement="Body text at least 16px equivalent; headline uses a fluid scale",
                     claim_class=ClaimClass.INFERRED_DECISION, basis=("compiler floor",)))
    return out


def _platform(req: ArtDirectionRequest) -> tuple[Optional[PlatformSpec], list[Claim]]:
    if req.platform_spec is not None:
        s = req.platform_spec
        return s, [Claim(section="production_constraints", statement=f"{s.width}x{s.height} {'/'.join(s.formats)}, safe margin {s.safe_margin:.0%}",
                         claim_class=ClaimClass.VERIFIED_REQUIREMENT, basis=("request.platform_spec",))]
    if req.platform and req.platform in PLATFORM_PRESETS:
        s = PLATFORM_PRESETS[req.platform]
        return s, [Claim(section="production_constraints", statement=f"{s.width}x{s.height} {'/'.join(s.formats)} (preset {s.name})",
                         claim_class=ClaimClass.INFERRED_DECISION, basis=(f"preset:{s.name}",),
                         rationale="built-in preset; confirm the platform's current specification before delivery")]
    return None, [Claim(section="production_constraints", statement="No platform specification supplied",
                        claim_class=ClaimClass.UNSUPPORTED_ASSUMPTION, basis=("request.platform",))]


def rubric(medium: Medium) -> list[dict[str, Any]]:
    return [
        {"criterion": "brand_fidelity", "method": "MEASURED", "how": "every fill/stroke in the palette; approved typefaces declared"},
        {"criterion": "legibility", "method": "MEASURED", "how": "WCAG 2.2 contrast of text/background pairs; minimum text size"},
        {"criterion": "accessibility", "method": "MEASURED", "how": "text alternative present; reduced-motion variant for motion"},
        {"criterion": "platform_suitability", "method": "MEASURED", "how": "dimensions and format match the specification"},
        {"criterion": "production_feasibility", "method": "MEASURED", "how": "every required renderer is available locally"},
        {"criterion": "visual_coherence", "method": "HUMAN_REQUIRED", "how": "a reviewer judges consistency with the brand"},
        {"criterion": "distinctiveness", "method": "HUMAN_REQUIRED",
         "how": "a reviewer judges; computed diversity between candidates is shown as context, not as a score"},
    ]


def compile_brief(p: GenomeProjection, req: ArtDirectionRequest) -> dict[str, Any]:
    p = p.fresh()
    claims: list[Claim] = [Claim(section="objective", statement=req.objective, claim_class=ClaimClass.VERIFIED_REQUIREMENT,
                                 basis=("request.objective",))]
    audience = req.audience or p.text("strategy.audience.primary")
    claims.append(Claim(section="objective", statement=f"Audience: {audience}" if audience else "Audience not stated",
                        claim_class=ClaimClass.VERIFIED_REQUIREMENT if audience else ClaimClass.UNSUPPORTED_ASSUMPTION,
                        basis=("request.audience" if req.audience else "genome:strategy.audience.primary",)))
    claims += _composition(p, req) + _typography(p) + _claims_for_color(p)
    finish = "matte, low sheen" if req.medium in (Medium.PACKAGING, Medium.POSTER) else "flat colour, no simulated texture"
    claims.append(Claim(section="material_language", statement=finish, claim_class=ClaimClass.INFERRED_DECISION,
                        basis=(f"medium:{req.medium.value}",), rationale="medium default; replace with approved material rules when they exist"))
    imagery = p.text("visual.imagery.style")
    claims.append(Claim(section="lighting_direction", statement=imagery or "Soft key light, low contrast shadows for 3D renders",
                        claim_class=ClaimClass.VERIFIED_REQUIREMENT if imagery else ClaimClass.INFERRED_DECISION,
                        basis=("genome:visual.imagery.style",) if imagery else ("renderer default",)))
    spec, platform_claims = _platform(req)
    claims += platform_claims
    usable = [r for r in req.references if r.rights is not RightsStatus.UNKNOWN]
    excluded = [r for r in req.references if r.rights is RightsStatus.UNKNOWN]
    for r in usable:
        claims.append(Claim(section="reference_provenance", statement=f"May inform direction: {r.ref} ({r.rights.value})",
                            claim_class=ClaimClass.VERIFIED_REQUIREMENT, basis=(f"reference:{r.ref}",), rationale=r.licence_ref or r.note))
    for r in excluded:
        claims.append(Claim(section="reference_provenance", statement=f"Excluded: {r.ref} (rights unknown)",
                            claim_class=ClaimClass.INFERRED_DECISION, basis=(f"reference:{r.ref}",),
                            rationale="references with unknown rights contribute nothing"))
    if req.budget_ceiling_minor is not None:
        claims.append(Claim(section="production_constraints", statement=f"Budget ceiling {req.budget_ceiling_minor} (minor units)",
                            claim_class=ClaimClass.VERIFIED_REQUIREMENT, basis=("request.budget_ceiling_minor",)))
    counts = {c.value: sum(1 for x in claims if x.claim_class is c) for c in ClaimClass}
    doc = {"version": ART_DIRECTOR_VERSION, "genome_ref": p.genome_ref, "resolution_hash": p.resolution_hash,
           "request_hash": canonical_hash(req.model_dump(mode="json")), "claims": [c.model_dump(mode="json") for c in claims],
           "claim_counts": counts, "platform_spec": spec.model_dump(mode="json") if spec else None, "rubric": rubric(req.medium),
           "excluded_references": [r.ref for r in excluded], "genome_trace": p.trace()}
    doc["brief_hash"] = canonical_hash(doc)
    return doc


def score(brief: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Score only what was measured. ``evidence`` maps criterion -> {"passed": bool, "detail": str} from real checks."""
    results = []
    for item in brief["rubric"]:
        name = item["criterion"]
        if item["method"] == "HUMAN_REQUIRED":
            results.append({"criterion": name, "status": "HUMAN_REQUIRED", "value": None})
        elif name in evidence:
            results.append({"criterion": name, "status": "MEASURED", "value": 1.0 if evidence[name]["passed"] else 0.0,
                            "detail": evidence[name].get("detail", "")})
        else:
            results.append({"criterion": name, "status": "NOT_RUN", "value": None})
    measured = [r for r in results if r["status"] == "MEASURED"]
    return {"criteria": results, "measured": len(measured), "measured_passed": sum(1 for r in measured if r["value"] == 1.0),
            "human_required": [r["criterion"] for r in results if r["status"] == "HUMAN_REQUIRED"],
            "not_run": [r["criterion"] for r in results if r["status"] == "NOT_RUN"],
            "note": "pass counts over measured criteria only; there is no overall quality score"}


__all__ = ["ART_DIRECTOR_VERSION", "ArtDirectionRequest", "Claim", "ClaimClass", "Medium", "PLATFORM_PRESETS", "PlatformSpec",
           "Reference", "RightsStatus", "compile_brief", "rubric", "score"]
