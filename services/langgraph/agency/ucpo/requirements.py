"""WebsiteBrief -> RequirementsPackage: every promise in the brief becomes a requirement with a stable id.

Ids are structural (page slug + section position + field), not hashes of the text, so a
copy edit keeps its id and shows up as a change instead of an omission plus an addition.
Each requirement names the stages that must evidence it (``ir``, ``source``,
``rendered``) and the brief path it came from. Nothing here is inferred: a requirement
exists because the brief states it, or because the release contract (accessibility,
no external requests) always applies.
"""

from __future__ import annotations

from typing import Any

from .contracts import Requirement, RequirementsPackage, WebsiteBrief

ALL_STAGES = ("ir", "source", "rendered")
# Contract requirements every site carries. Rendered-only: they are properties of the built page.
CONTRACT = (
    ("req.a11y.automated", "A11Y_AUTOMATED", "No automated accessibility violations (axe-core, WCAG 2.2 A/AA rules)"),
    ("req.responsive.reflow", "RESPONSIVE_REFLOW", "No horizontal scrolling at 320, 768 and 1280 CSS px"),
    ("req.text.zoom", "TEXT_ZOOM", "Content reflows without horizontal scrolling with text at 200%"),
    ("req.motion.reduced", "REDUCED_MOTION", "With prefers-reduced-motion: reduce, nothing animates"),
    ("req.keyboard.focus", "KEYBOARD_FOCUS", "A skip link is the first focus stop and every focus stop shows a visible indicator"),
    ("req.console.clean", "NO_CONSOLE_ERRORS", "No console errors or uncaught page errors"),
    ("req.network.none", "NO_EXTERNAL_REQUESTS", "The page requests nothing outside its own origin"),
)


def route_of(slug: str) -> str:
    return "/" if slug == "index" else f"/{slug}/"


def section_req_prefix(slug: str, n: int) -> str:
    return f"req.{slug}.s{n + 1}"


def compile_requirements(brief: WebsiteBrief, *, project_ref: str) -> RequirementsPackage:
    reqs: list[Requirement] = []

    def add(req_id: str, kind: str, statement: str, subject: dict[str, Any], source_ref: str,
            stages: tuple[str, ...] = ALL_STAGES, mandatory: bool = True) -> None:
        reqs.append(Requirement(req_id=req_id, kind=kind, statement=statement, subject=subject, mandatory=mandatory,
                                source_ref=source_ref, stages=stages))

    add("req.lang", "LANG", f"Every page declares lang={brief.locale}", {"text": brief.locale, "routes": "*"},
        "brief.locale")
    add("req.brand", "BRAND_ON_PAGE", f"Every page names {brief.organization}", {"text": brief.organization, "routes": "*"},
        "brief.organization")
    for p_i, page in enumerate(brief.pages):
        route = route_of(page.slug)
        add(f"req.page.{page.slug}", "PAGE_EXISTS", f"Page {route} exists with title {page.title!r}",
            {"page": page.slug, "route": route, "text": page.title}, f"brief.pages[{p_i}].title")
        add(f"req.nav.{page.slug}", "NAV_LINK", f"Every page links to {route} as {page.title!r}",
            {"page": page.slug, "href": route, "text": page.title, "routes": "*"}, f"brief.pages[{p_i}]")
        for s_i, section in enumerate(page.sections):
            pre, path = section_req_prefix(page.slug, s_i), f"brief.pages[{p_i}].sections[{s_i}]"
            base = {"page": page.slug, "route": route, "section": s_i}
            add(f"{pre}.heading", "SECTION_HEADING", f"{route} shows the heading {section.heading!r}",
                {**base, "text": section.heading}, f"{path}.heading")
            if section.body:
                add(f"{pre}.body", "SECTION_BODY", f"{route} shows section {s_i + 1} body copy verbatim",
                    {**base, "text": section.body}, f"{path}.body")
            if section.label:
                add(f"{pre}.label", "LABEL_TEXT", f"{route} shows the label {section.label!r}",
                    {**base, "text": section.label}, f"{path}.label")
            for i_i, item in enumerate(section.items):
                add(f"{pre}.item{i_i}", "ITEM_TEXT", f"{route} shows the item {item.title!r}",
                    {**base, "item": i_i, "text": item.title, "body": item.body}, f"{path}.items[{i_i}]")
            if section.cta:
                href = route_of(brief.cta_target.partition("#")[0])
                anchor = brief.cta_target.partition("#")[2]
                add(f"{pre}.cta", "CTA", f"{route} offers {brief.cta_label!r} linking to {brief.cta_target}",
                    {**base, "text": brief.cta_label, "href": href + (f"#{anchor}" if anchor else "")}, f"{path}.cta")
    for i_i, image in enumerate(brief.images):
        add(f"req.image.{image.asset_id}.alt", "IMAGE_ALT", f"Image {image.asset_id} has its approved alt text",
            {"asset_id": image.asset_id, "text": image.alt}, f"brief.images[{i_i}].alt")
        add(f"req.image.{image.asset_id}.rights", "IMAGE_RIGHTS",
            f"Image {image.asset_id} ships only with recorded rights ({image.rights})",
            {"asset_id": image.asset_id, "rights": image.rights, "license_ref": image.license_ref or ""},
            f"brief.images[{i_i}].rights", stages=("ir", "source"))
    for i, phrase in enumerate(brief.required_phrases):
        add(f"req.phrase.{i}", "REQUIRED_PHRASE", f"The site says {phrase!r}", {"text": phrase},
            f"brief.required_phrases[{i}]")
    for i, phrase in enumerate(brief.forbidden_phrases):
        add(f"req.forbid.{i}", "FORBIDDEN_PHRASE", f"The site never says {phrase!r}", {"text": phrase},
            f"brief.forbidden_phrases[{i}]")
    add("req.psem.colour", "PSEM_COLOUR",
        "Only PSEM colours, only legal pairings, one accent per page", {"grammar": "psem_editorial"},
        "profile:psem_editorial", stages=("ir", "rendered"))
    for req_id, kind, statement in CONTRACT:
        add(req_id, kind, statement, {}, "contract:amc-ucpo-release/v1", stages=("rendered",))

    ids = [r.req_id for r in reqs]
    if len(set(ids)) != len(ids):  # structural ids cannot collide; this guards a future change to the scheme
        raise ValueError("duplicate requirement id")
    return RequirementsPackage(project_ref=project_ref, brief_hash=brief.content_hash, requirements=tuple(reqs))


def diff_requirements(old: RequirementsPackage, new: RequirementsPackage) -> dict[str, list[str]]:
    """Requirement ids added, removed and changed (same id, different subject) between two packages."""
    a, b = old.by_id(), new.by_id()
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": sorted(k for k in set(a) & set(b) if a[k].subject != b[k].subject or a[k].mandatory != b[k].mandatory),
    }


__all__ = ["ALL_STAGES", "CONTRACT", "compile_requirements", "diff_requirements", "route_of", "section_req_prefix"]
