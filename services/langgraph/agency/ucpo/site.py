"""Brief + requirements + PSEM genome -> SiteArchitecture and WebsiteIR.

The IR is the single description the source generator renders and the verifier checks
against. Copy is copied from the brief, never written here. PSEM decides the ground of
each section (charcoal / paper alternation, opening on charcoal) and one accent per
page; ``colour_plan`` lists every foreground/background pairing a section will use, and
``check_colour_plan`` runs each one through ``psem.check_usage`` so an illegal pairing is
a compile error, not a QA finding.
"""

from __future__ import annotations

from typing import Iterable

from services.langgraph.agency.foundry import psem
from services.langgraph.agency.foundry.contracts import CreativeGenome

from .contracts import (
    ComponentSpec,
    PageSpec,
    RequirementsPackage,
    RouteSpec,
    SectionSpec,
    SiteArchitecture,
    WebsiteBrief,
    WebsiteIR,
)
from .requirements import route_of, section_req_prefix

INTERACTIONS = ("skip_link", "focus_visible", "reduced_motion", "in_page_anchor")
RESPONSIVE_RULES = {
    "320": "one column; display type clamps to the viewport; no fixed widths",
    "768": "one column with wider measure; plates span the column",
    "1280": "12-column editorial grid; text measure capped at 68ch",
}
_KINDS = ("hero", "editorial", "statement", "index", "gallery", "contact")


def _component(kind: str) -> ComponentSpec:
    return ComponentSpec(
        component_id=f"psem.{kind}", version="1",
        props=("section_id", "scheme", "accent", "serial", "label", "heading", "body", "items", "image", "cta", "req_refs"),
        variants=("paper", "charcoal"), states=("default", "focus-visible", "reduced-motion"),
        responsive={"320": "stack", "768": "stack", "1280": "grid"},
        accessibility=("one heading per section at h2 (h1 for the first section of a page)", "text alternatives for images",
                       "visible focus on links"),
        invariants=("copy is rendered verbatim from the IR", "data-req attributes carry requirement ids",
                    "PSEM pairings only"),
        mutable_axes=("scheme", "accent", "serial"))


COMPONENTS = tuple(_component(k) for k in _KINDS) + tuple(
    ComponentSpec(component_id=f"psem.{name}", version="1", props=props, variants=("paper",) if name == "header" else ("charcoal",),
                  states=("default", "focus-visible"), responsive={"320": "wrap", "768": "row", "1280": "row"},
                  accessibility=access, invariants=("copy is rendered verbatim from the IR",), mutable_axes=())
    for name, props, access in (
        ("header", ("organization", "navigation"), ("skip link first", "nav landmark with an accessible name",
                                                     "aria-current on the current page")),
        ("footer", ("organization", "tagline"), ("contentinfo landmark",)),
    ))


def colour_plan(scheme: str, accent: str) -> tuple[tuple[str, str, str, str], ...]:
    """(fg, bg, use, role) for every pairing a section on this ground renders."""
    if scheme == "paper":
        return (("charcoal", "paper", "text", "heading/body"), ("graphite", "paper", "text", "label/serial"),
                ("fog", "paper", "graphic", "rule"), ("paper", "charcoal", "text", "cta"))
    plan = [("paper", "charcoal", "text", "heading/body"), ("fog", "charcoal", "text", "label")]
    if accent != "none":
        plan += [(accent, "charcoal", "text", "serial"), (accent, "charcoal", "graphic", "rule"),
                 ("charcoal", accent, "text", "cta")]
    else:
        plan += [("paper", "charcoal", "text", "serial"), ("fog", "charcoal", "graphic", "rule")]
    return tuple(plan)


CHROME_PLAN = (("charcoal", "paper", "text", "header"), ("graphite", "paper", "text", "nav"),
               ("paper", "charcoal", "text", "footer"), ("fog", "charcoal", "text", "footer-small"))


def check_colour_plan(ir: WebsiteIR) -> list[str]:
    """Every pairing the IR implies, checked with ``psem.check_usage``; one accent per page. Returns violations."""
    errors: list[str] = []
    for fg, bg, use, role in CHROME_PLAN:
        try:
            psem.check_usage(fg, bg, use)
        except psem.PsemUsageError as exc:
            errors.append(f"chrome {role}: {exc}")
    for page in ir.pages:
        colours: set[str] = set()
        for s in page.sections:
            for fg, bg, use, role in colour_plan(s.scheme, s.accent):
                colours |= {fg, bg}
                try:
                    psem.check_usage(fg, bg, use)
                except psem.PsemUsageError as exc:
                    errors.append(f"{s.section_id} {role}: {exc}")
        try:
            psem.one_accent(colours)
        except psem.PsemUsageError as exc:
            errors.append(f"{page.page_id}: {exc}")
    return errors


def _page_accent(index: int) -> str:
    return psem.ACCENTS[index % len(psem.ACCENTS)]


def compile_site(brief: WebsiteBrief, requirements: RequirementsPackage, genome: CreativeGenome, *,
                 token_refs: dict[str, str]) -> tuple[SiteArchitecture, WebsiteIR]:
    if requirements.brief_hash != brief.content_hash:
        raise ValueError("requirements were compiled from a different brief")
    if genome.composition_rules.get("dominant_grammar") != psem.GRAMMAR_ID:
        raise ValueError("the website compiler renders PSEM genomes only")
    known = set(requirements.by_id())
    cta_href = ""
    if brief.cta_target:
        page, _, anchor = brief.cta_target.partition("#")
        cta_href = route_of(page) + (f"#{anchor}" if anchor else "")
    images = {i.asset_id: i for i in brief.images}

    pages: list[PageSpec] = []
    for p_i, page in enumerate(brief.pages):
        accent = _page_accent(p_i)
        sections: list[SectionSpec] = []
        for s_i, sb in enumerate(page.sections):
            pre = section_req_prefix(page.slug, s_i)
            refs = {"heading": f"{pre}.heading"}
            if sb.body:
                refs["body"] = f"{pre}.body"
            if sb.label:
                refs["label"] = f"{pre}.label"
            for i in range(len(sb.items)):
                refs[f"item:{i}"] = f"{pre}.item{i}"
            if sb.cta:
                refs["cta"] = f"{pre}.cta"
            if sb.image:
                refs["image"] = f"req.image.{sb.image}.alt"
            missing = sorted(set(refs.values()) - known)
            if missing:
                raise ValueError(f"section {pre} references unknown requirements {missing}")
            scheme = "charcoal" if s_i % 2 == 0 else "paper"
            sections.append(SectionSpec(
                section_id=sb.anchor or f"{page.slug}-s{s_i + 1}", kind=sb.kind, component_id=f"psem.{sb.kind}",
                scheme=scheme, accent=accent if scheme == "charcoal" else "none",
                serial=f"{s_i + 1:02d} / {len(page.sections):02d}", label=sb.label, heading=sb.heading, body=sb.body,
                items=sb.items, image=sb.image, cta={"label": brief.cta_label, "href": cta_href} if sb.cta else None,
                req_refs=refs))
        pages.append(PageSpec(page_id=page.slug, route=route_of(page.slug), title=page.title, description=page.description,
                              sections=tuple(sections), req_refs={"page": f"req.page.{page.slug}"}))

    arch = SiteArchitecture(
        routes=tuple(RouteSpec(page_id=p.page_id, path=p.route, title=p.title) for p in pages),
        navigation=tuple(p.page_id for p in pages),
        components=tuple(c.component_id for c in COMPONENTS),
        assets=tuple(sorted(images)),
        interactions=INTERACTIONS,
        metadata={p.page_id: {"title": p.title, "description": p.description} for p in pages},
        responsive_rules=RESPONSIVE_RULES,
        accessibility_contracts=tuple(r.req_id for r in requirements.requirements if r.stages == ("rendered",)),
    )
    ir = WebsiteIR(
        project_ref=requirements.project_ref, organization=brief.organization, tagline=brief.tagline, locale=brief.locale,
        requirements_ref=requirements.content_hash, site_architecture_ref=arch.content_hash, genome_ref=genome.content_hash,
        token_refs=dict(token_refs), pages=tuple(pages), components=COMPONENTS, images=tuple(brief.images),
        interaction_specs=INTERACTIONS,
        verification_contract=tuple(r.req_id for r in requirements.requirements if "rendered" in r.stages))
    errors = check_colour_plan(ir)
    if errors:
        raise psem.PsemUsageError("; ".join(errors))
    return arch, ir


def ir_texts(ir: WebsiteIR) -> Iterable[str]:
    """All copy the IR will render, for phrase checks."""
    yield ir.organization
    if ir.tagline:
        yield ir.tagline
    for page in ir.pages:
        yield page.title
        yield page.description
        for s in page.sections:
            yield from (t for t in (s.label, s.heading, s.body) if t)
            for item in s.items:
                yield item.title
                if item.body:
                    yield item.body
            if s.cta:
                yield s.cta["label"]
    for image in ir.images:
        yield image.alt


__all__ = ["CHROME_PLAN", "COMPONENTS", "INTERACTIONS", "RESPONSIVE_RULES", "check_colour_plan", "colour_plan",
           "compile_site", "ir_texts"]
