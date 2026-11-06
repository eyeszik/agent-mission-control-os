"""Deterministic landing-page generator and renderer.

``generate_landing`` composes a ``LandingPageIR`` from the mission only: the
brand name, audience, goals, desired action, verified claims and the
*verified* copy/metric/testimonial assets the brief supplied. It never writes
a claim of its own. A section with no supplied content is omitted (and the
omission recorded) rather than filled with invented copy, unless the mission
requires it, in which case it is emitted empty so the content critic and the
human see the gap.

Copy assets are matched to sections by ``asset_id`` prefix: ``value``,
``problem``, ``solution``, ``feature``, ``security``, ``step``, ``faq``.

``render_landing_html`` is a pure function of the IR plus the context-derived
requirements (``context.derive_requirements``): reduced-motion guards, visible
focus, 24px targets and reflow-safe layout are emitted only when the selected
owned standards require them. That dependency is deliberate and is what the
champion/challenger benchmark measures.
"""

from __future__ import annotations

import html
import re
from typing import Any, Iterable

from services.langgraph.agency.design_tokens import compile_css, hex_to_color

from .ir import (
    ArtifactIR,
    CallToAction,
    ConceptSpec,
    ConstraintKind,
    LandingPageIR,
    MissionIR,
    Section,
    SectionKind,
    seal_artifact,
)
from .mission import mission_constraint

GENERATOR_VERSION = "amc-creative-landing/v1"

NARRATIVE_ORDER: dict[str, tuple[SectionKind, ...]] = {
    "outcome_first": (SectionKind.HERO, SectionKind.SOLUTION, SectionKind.FEATURES, SectionKind.PROOF,
                      SectionKind.SECURITY, SectionKind.HOW_IT_WORKS, SectionKind.FAQ, SectionKind.CTA, SectionKind.FOOTER),
    "problem_first": (SectionKind.HERO, SectionKind.PROBLEM, SectionKind.SOLUTION, SectionKind.HOW_IT_WORKS,
                      SectionKind.FEATURES, SectionKind.PROOF, SectionKind.FAQ, SectionKind.CTA, SectionKind.FOOTER),
    "proof_first": (SectionKind.HERO, SectionKind.PROOF, SectionKind.TESTIMONIALS, SectionKind.SECURITY,
                    SectionKind.SOLUTION, SectionKind.FEATURES, SectionKind.CTA, SectionKind.FOOTER),
    "story_first": (SectionKind.HERO, SectionKind.PROBLEM, SectionKind.HOW_IT_WORKS, SectionKind.SOLUTION,
                    SectionKind.TESTIMONIALS, SectionKind.PROOF, SectionKind.FAQ, SectionKind.CTA, SectionKind.FOOTER),
}
HEADINGS = {
    SectionKind.PROOF: "Verified facts", SectionKind.PROBLEM: "The challenge", SectionKind.SOLUTION: "The approach",
    SectionKind.FEATURES: "Capabilities", SectionKind.HOW_IT_WORKS: "How it works", SectionKind.SECURITY: "Security",
    SectionKind.TESTIMONIALS: "What customers say", SectionKind.FAQ: "Questions", SectionKind.CTA: "Next step",
}
_PREFIX = {
    SectionKind.PROBLEM: "problem", SectionKind.SOLUTION: "solution", SectionKind.FEATURES: "feature",
    SectionKind.SECURITY: "security", SectionKind.HOW_IT_WORKS: "step", SectionKind.FAQ: "faq",
}
# Sections that hold supporting content; single-focus hierarchies keep at most this many.
_SINGLE_FOCUS_BODY_SECTIONS = 3
_WORD = re.compile(r"\S+")


def _verified_copy(mission: MissionIR, prefix: str) -> list[tuple[str, str]]:
    return [(a.asset_id, a.ref) for a in sorted(mission.available_assets, key=lambda a: a.asset_id)
            if a.kind == "copy" and a.verified and a.asset_id.startswith(prefix)]


def verified_claims(mission: MissionIR) -> tuple[str, ...]:
    claims: list[str] = []
    for c in mission_constraint(mission, ConstraintKind.VERIFIED_CLAIMS_ONLY):
        claims += [str(x) for x in c.params.get("claims", [])]
    claims += [a.ref for a in mission.available_assets if a.verified and a.kind in {"metric", "copy", "testimonial"}]
    return tuple(dict.fromkeys(claims))


def _limit_words(text: str, limit: int | None) -> str:
    if not limit:
        return text
    words = _WORD.findall(text)
    return " ".join(words[:limit])


def _headline(mission: MissionIR, concept: ConceptSpec) -> str:
    brand, audience = mission.brand_name, mission.audience
    listed = [str(x) for c in mission_constraint(mission, ConstraintKind.VERIFIED_CLAIMS_ONLY) for x in c.params.get("claims", [])]
    first_claim = listed[0] if listed else None
    text = {
        "outcome_first": f"{brand} for {audience}",
        "problem_first": f"Built for {audience}",
        "proof_first": f"{brand}: {first_claim}" if first_claim else f"{brand}, on the evidence",
        "story_first": f"How {audience} work with {brand}",
    }[concept.narrative]
    limits = [int(c.params["max"]) for c in mission_constraint(mission, ConstraintKind.MAX_HEADLINE_WORDS)]
    return _limit_words(text, min(limits) if limits else None)


def _section(kind: SectionKind, mission: MissionIR, claims: tuple[str, ...]) -> Section | None:
    sid = kind.value.replace("_", "-")
    if kind is SectionKind.PROOF:
        items = tuple(claims)
        return Section(section_id=sid, kind=kind, heading=HEADINGS[kind], items=items, source_refs=("mission.verified_claims",)) if items else None
    if kind is SectionKind.TESTIMONIALS:
        quotes = tuple(a.ref for a in mission.available_assets
                       if a.kind == "testimonial" and a.verified and a.rights in {"owned", "licensed"})
        return Section(section_id=sid, kind=kind, heading=HEADINGS[kind], items=quotes,
                       source_refs=("mission.assets.testimonial",)) if quotes else None
    if kind is SectionKind.CTA:
        return Section(section_id=sid, kind=kind, heading=HEADINGS[kind], body=f"{mission.desired_action}.",
                       source_refs=("mission.desired_action",))
    if kind is SectionKind.FOOTER:
        return Section(section_id=sid, kind=kind, heading=mission.brand_name, source_refs=("mission.brand_name",))
    copy = _verified_copy(mission, _PREFIX[kind])
    if not copy:
        return None
    refs = tuple(f"asset:{aid}" for aid, _ in copy)
    if kind in {SectionKind.FEATURES, SectionKind.HOW_IT_WORKS, SectionKind.FAQ}:
        return Section(section_id=sid, kind=kind, heading=HEADINGS[kind], items=tuple(t for _, t in copy), source_refs=refs)
    return Section(section_id=sid, kind=kind, heading=HEADINGS[kind], body=" ".join(t for _, t in copy), source_refs=refs)


def generate_landing(mission: MissionIR, concept: ConceptSpec, *, candidate_id: str, version: int = 1,
                     provenance: dict[str, Any] | None = None, omit_sections: Iterable[str] = ()) -> ArtifactIR:
    claims = verified_claims(mission)
    required = {str(c.params["section"]) for c in mission_constraint(mission, ConstraintKind.REQUIRED_SECTION)}
    forbidden = {str(c.params["section"]) for c in mission_constraint(mission, ConstraintKind.FORBIDDEN_SECTION)}
    omit = set(omit_sections)
    order = list(NARRATIVE_ORDER[concept.narrative])
    for name in sorted(required):
        if name in SectionKind._value2member_map_ and SectionKind(name) not in order:
            order.insert(len(order) - 2, SectionKind(name))

    sections: list[Section] = []
    omitted: list[str] = []
    value = _verified_copy(mission, "value")
    hero_body = value[0][1] if value else f"For {mission.audience}: {mission.user_goal}."
    sections.append(Section(section_id="hero", kind=SectionKind.HERO, heading=_headline(mission, concept), body=hero_body,
                            source_refs=(f"asset:{value[0][0]}",) if value else ("mission.audience", "mission.user_goal")))
    body_sections = 0
    for kind in order[1:]:
        if kind.value in forbidden or kind.value in omit:
            omitted.append(f"{kind.value}: excluded")
            continue
        sec = _section(kind, mission, claims)
        if sec is None:
            if kind.value in required:
                sec = Section(section_id=kind.value.replace("_", "-"), kind=kind, heading=HEADINGS.get(kind, kind.value))
            else:
                omitted.append(f"{kind.value}: no verified content supplied")
                continue
        is_body = kind not in {SectionKind.CTA, SectionKind.FOOTER}
        if (is_body and concept.hierarchy == "single_focus" and body_sections >= _SINGLE_FOCUS_BODY_SECTIONS
                and kind.value not in required):
            omitted.append(f"{kind.value}: single-focus hierarchy")
            continue
        body_sections += int(is_body)
        sections.append(sec)

    cta_c = mission_constraint(mission, ConstraintKind.CTA_TRUTHFUL)
    params = cta_c[0].params if cta_c else {}
    cta = CallToAction(label=_limit_words(mission.desired_action, 6)[:60], action=mission.desired_action,
                       destination=params.get("destination"), integration_status=params.get("integration_status", "unavailable"))
    brand = mission_constraint(mission, ConstraintKind.BRAND_PALETTE)[0].params
    page = LandingPageIR(concept=concept, headline=sections[0].heading, subheadline=hero_body, sections=tuple(sections), cta=cta,
                         palette=dict(brand["palette"]), heading_font=brand["heading_font"], body_font=brand["body_font"])
    return seal_artifact(
        artifact_id=candidate_id, mission_id=mission.mission_id, artifact_type=mission.artifact_type,
        semantic_intent=f"{mission.desired_action} — {mission.business_goal}"[:500],
        hierarchy=tuple(s.kind.value for s in sections),
        content_structure={"omitted": omitted, "section_count": len(sections)},
        brand_bindings={"brand_name": mission.brand_name, "palette": dict(brand["palette"]),
                        "heading_font": brand["heading_font"], "body_font": brand["body_font"]},
        accessibility_requirements=tuple(sorted(c.kind.value for c in mission.accessibility_constraints)),
        implementation_requirements=tuple(sorted(c.kind.value for c in mission.implementation_constraints)),
        provenance={"generator": GENERATOR_VERSION, **(provenance or {})}, version=version, landing_page=page,
    )


# --------------------------------------------------------------------------- rendering

_METAPHOR_PATHS = {
    "shield": '<path d="M32 4 L58 14 V32 C58 46 46 56 32 60 C18 56 6 46 6 32 V14 Z" fill="{primary}"/>',
    "lens": '<circle cx="28" cy="28" r="20" fill="none" stroke="{primary}" stroke-width="6"/><path d="M42 42 L58 58" stroke="{primary}" stroke-width="6"/>',
    "control_room": '<rect x="4" y="8" width="24" height="18" fill="{primary}"/><rect x="36" y="8" width="24" height="18" fill="{secondary}"/>'
                    '<rect x="4" y="34" width="56" height="22" fill="{primary}"/>',
    "pathway": '<path d="M4 56 L22 30 L38 40 L60 8" fill="none" stroke="{primary}" stroke-width="6"/>',
}
_LAYOUT = {
    "split_hero": ".hero{display:grid;grid-template-columns:1fr;gap:2rem;align-items:center}"
                  "@media (min-width:48rem){.hero{grid-template-columns:3fr 2fr}}",
    "centered": ".hero{text-align:center;max-width:48rem;margin:0 auto}",
    "editorial": ".hero{max-width:38rem;border-left:0.5rem solid var(--color-secondary);padding-left:1.5rem}"
                 ".hero h1{font-size:clamp(2.25rem,6vw,4rem);line-height:1.05}",
    "full_bleed": ".hero{padding:4rem 1.5rem}",
}


def palette_css(palette: dict[str, str]) -> str:
    """Palette roles as CSS custom properties (``--color-<role>``), compiled by the
    repository's only DTCG compiler rather than formatted here."""
    document = {"color": {role: {"$type": "color", "$value": hex_to_color(value)} for role, value in sorted(palette.items())}}
    return compile_css(document, source_label="creative-landing")[1]


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _cta_link(page: LandingPageIR, *, primary: bool, target_size: bool, label: str | None = None) -> str:
    p = page.palette
    href = page.cta.destination or "#next-step"
    size = ";min-height:44px;min-width:44px" if target_size else ""
    style = (f"color:{p['surface']};background-color:{p['primary']}{size}" if primary
             else f"color:{p['primary']};background-color:{p['surface']}{size}")
    return f'<a class="cta" href="{_e(href)}" style="{style}">{_e(label or page.cta.label)}</a>'


def render_landing_html(artifact: ArtifactIR, requirements: Iterable[str] = ()) -> str:
    page = artifact.landing_page
    if page is None:
        raise ValueError("render_landing_html needs a landing_page artifact")
    req = set(requirements)
    p = page.palette
    c = page.concept
    brand = artifact.brand_bindings.get("brand_name", "")
    ink = f"color:{p['text']};background-color:{p['surface']}"
    css = [
        palette_css(p),
        f"body{{margin:0;font-family:{_e(page.body_font)},system-ui,sans-serif;line-height:1.6}}",
        f"h1,h2{{font-family:{_e(page.heading_font)},system-ui,sans-serif;line-height:1.2}}",
        "header,main>section,footer{padding:2rem 1.5rem}",
        ".cta{display:inline-flex;align-items:center;padding:0.75rem 1.25rem;border-radius:0.5rem;text-decoration:none;"
        "font-weight:600;transition:transform 0.2s ease}",
        ".cta:hover{transform:translateY(-2px)}",
        "html{scroll-behavior:smooth}",
        _LAYOUT[c.composition],
    ]
    if c.hierarchy == "modular":
        css.append(".items{display:grid;grid-template-columns:repeat(auto-fit,minmax(14rem,1fr));gap:1rem;list-style:none;padding:0}"
                   ".items li{border:1px solid var(--color-secondary);border-radius:0.5rem;padding:1rem}")
    if "reflow" in req:
        css.append("img,svg{max-width:100%;height:auto}main{overflow-wrap:anywhere}")
    if "visible_focus" in req:
        css.append("a:focus-visible,button:focus-visible{outline:3px solid var(--color-primary);outline-offset:3px}")
    if "reduced_motion" in req:
        css.append("@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;"
                   "transition:none!important;scroll-behavior:auto!important}.cta:hover{transform:none}}")
    if "target_size_24" in req:
        css.append(".cta{min-height:44px;min-width:44px}")

    mark = ""
    if c.metaphor != "none":
        mark = (f'<svg class="mark" width="64" height="64" viewBox="0 0 64 64" role="img" aria-label="{_e(brand)} {c.metaphor} mark">'
                + _METAPHOR_PATHS[c.metaphor].format(primary=p["primary"], secondary=p["secondary"]) + "</svg>")
    target = "target_size_24" in req
    hero_bg = f"color:{p['surface']};background-color:{p['primary']}" if c.composition == "full_bleed" else ink
    parts = [
        "<!doctype html>",
        f'<html lang="{_e(page.locale)}">',
        '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_e(brand)} — {_e(page.headline)}</title>",
        f"<style>{''.join(css)}</style></head>",
        f'<body style="{ink}">',
        '<a class="skip" href="#main">Skip to content</a>' if "landmarks" in req else "",
        f'<header style="{ink}"><nav aria-label="Primary"><a href="#main" style="{ink}">{_e(brand)}</a></nav></header>',
        '<main id="main">',
    ]
    for sec in page.sections:
        sid = _e(sec.section_id)
        if sec.kind is SectionKind.HERO:
            hero_cta = "" if c.interaction == "progressive" else _cta_link(page, primary=c.composition != "full_bleed", target_size=target)
            secondary = ""
            if c.interaction in {"guided_demo", "progressive"} and len(page.sections) > 2:
                nxt = page.sections[1]
                secondary = f' <a href="#{_e(nxt.section_id)}" style="{hero_bg}">{_e(nxt.heading)}</a>'
            parts.append(
                f'<section id="{sid}" class="hero" data-section="hero" aria-labelledby="{sid}-h" style="{hero_bg}">'
                f'<div><h1 id="{sid}-h" style="{hero_bg}">{_e(sec.heading)}</h1><p style="{hero_bg}">{_e(sec.body)}</p>'
                f"<p>{hero_cta}{secondary}</p></div>{mark}</section>"
            )
            continue
        if sec.kind is SectionKind.FOOTER:
            continue
        body = f'<p style="{ink}">{_e(sec.body)}</p>' if sec.body else ""
        items = ""
        if sec.items:
            tag = "ol" if sec.kind is SectionKind.HOW_IT_WORKS else "ul"
            items = f'<{tag} class="items">' + "".join(f'<li style="{ink}">{_e(i)}</li>' for i in sec.items) + f"</{tag}>"
        cta = ""
        if sec.kind is SectionKind.CTA or (c.interaction == "guided_demo" and sec.kind is SectionKind.HOW_IT_WORKS):
            cta = f"<p>{_cta_link(page, primary=True, target_size=target)}</p>"
        anchor = ' id="next-step"' if sec.kind is SectionKind.CTA else f' id="{sid}"'
        parts.append(f'<section{anchor} data-section="{sec.kind.value}" aria-labelledby="{sid}-h">'
                     f'<h2 id="{sid}-h" style="{ink}">{_e(sec.heading)}</h2>{body}{items}{cta}</section>')
    parts.append("</main>")
    parts.append(f'<footer style="{ink}"><p style="{ink}">{_e(brand)}</p></footer>')
    parts.append("</body></html>")
    return "".join(x for x in parts if x)


__all__ = ["GENERATOR_VERSION", "NARRATIVE_ORDER", "generate_landing", "render_landing_html", "verified_claims"]
