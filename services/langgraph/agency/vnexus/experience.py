"""VNEXUS experience compiler: approved genome + audience + objective -> a verifiable experience package.

Stages, each hashed and citing what it was derived from:

    genome context -> creative intent graph -> experience architecture (UI/UX compiler)
    -> design tokens (the single DTCG compiler) -> component specs -> responsive rules
    -> interaction contracts -> accessibility validation -> implementation artifacts
    -> verification report

Reuse, not reinvention: architecture, components, states, responsive rules and
WCAG requirements come from ``agency.ui_ux.compile_uiux``; tokens from
``agency.design_tokens`` through the foundry token document; the implementation
artifact is the foundry experience twin's working HTML, verified in local
Chromium by the foundry's scenario suite when a browser is available.

A rendered image is never an experience. Targets with no implementation
renderer (SaaS dashboards, web applications) return the full specification and
say ``SPEC_ONLY``: the implementation must still be written and tested.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import Field

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.foundry import experience as twin
from services.langgraph.agency.foundry.tokens import compile_tokens
from services.langgraph.agency.ui_ux.compiler import compile_uiux
from services.langgraph.agency.ui_ux.models import Platform, SurfaceMode, UIUXRequest
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from .bridge import GenomeProjection, brand_context, creative_genome
from .genome import _Strict

EXPERIENCE_COMPILER = "amc-vnexus-experience/v1"


class ExperienceTarget(str, Enum):
    MARKETING_SITE = "MARKETING_SITE"
    LANDING_PAGE = "LANDING_PAGE"
    BRAND_MICROSITE = "BRAND_MICROSITE"
    CAMPAIGN_EXPERIENCE = "CAMPAIGN_EXPERIENCE"
    SAAS_DASHBOARD = "SAAS_DASHBOARD"
    WEB_APPLICATION = "WEB_APPLICATION"


SURFACE: dict[ExperienceTarget, SurfaceMode] = {
    ExperienceTarget.MARKETING_SITE: SurfaceMode.landing_page, ExperienceTarget.LANDING_PAGE: SurfaceMode.landing_page,
    ExperienceTarget.BRAND_MICROSITE: SurfaceMode.landing_page, ExperienceTarget.CAMPAIGN_EXPERIENCE: SurfaceMode.landing_page,
    ExperienceTarget.SAAS_DASHBOARD: SurfaceMode.dashboard, ExperienceTarget.WEB_APPLICATION: SurfaceMode.application,
}
RENDERABLE = frozenset({ExperienceTarget.MARKETING_SITE, ExperienceTarget.LANDING_PAGE, ExperienceTarget.BRAND_MICROSITE,
                        ExperienceTarget.CAMPAIGN_EXPERIENCE})


class ContentItem(_Strict):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=400)


class ExperienceRequest(_Strict):
    target: ExperienceTarget
    objective: str = Field(min_length=1, max_length=500)
    audience: str = Field(default="", max_length=300)
    primary_action: str = Field(default="", max_length=120)
    conversion_goal: str = Field(default="", max_length=300)
    headline: str = Field(default="", max_length=120)
    subhead: str = Field(default="", max_length=240)
    content: tuple[ContentItem, ...] = Field(default=(), max_length=12)
    content_requirements: tuple[str, ...] = Field(default=(), max_length=20)
    locale_rtl: bool = False


def _stage(name: str, payload: Any, derived_from: list[str]) -> dict[str, Any]:
    return {"stage": name, "derived_from": derived_from, "payload": payload, "stage_hash": canonical_hash(payload)}


def intent_graph(req: ExperienceRequest, p: GenomeProjection) -> dict[str, Any]:
    """Objective -> audience need -> action, with supporting intents. Each node cites its source field."""
    nodes = [{"id": "objective", "text": req.objective, "source": "request.objective"}]
    audience = req.audience or p.text("strategy.audience.primary")
    nodes.append({"id": "audience", "text": audience or "UNSTATED", "source": "request.audience" if req.audience else
                  ("genome:strategy.audience.primary" if audience else "assumption")})
    need = p.text("strategy.audience.needs")
    nodes.append({"id": "need", "text": need or "UNSTATED", "source": "genome:strategy.audience.needs" if need else "assumption"})
    action = req.primary_action or "UNSTATED"
    nodes.append({"id": "action", "text": action, "source": "request.primary_action" if req.primary_action else "assumption"})
    promise = p.text("strategy.positioning.promise")
    nodes += [{"id": "comprehension", "text": "understand the offer in one screen", "source": "compiler: landing-page convention"},
              {"id": "trust", "text": promise or "UNSTATED promise", "source": "genome:strategy.positioning.promise" if promise else "assumption"}]
    if req.conversion_goal:
        nodes.append({"id": "conversion", "text": req.conversion_goal, "source": "request.conversion_goal"})
    edges = [["audience", "objective"], ["need", "audience"], ["action", "objective"], ["comprehension", "action"], ["trust", "action"]]
    if req.conversion_goal:
        edges.append(["conversion", "action"])
    assumptions = [n["id"] for n in nodes if n["source"] == "assumption"]
    return {"nodes": nodes, "edges": edges, "assumptions": assumptions}


def accessibility_validation(palette: dict[str, str], ui_ir: Any, genome_rules: dict[str, Any]) -> dict[str, Any]:
    """Deterministic checks only (WCAG 2.2 ratios, sizes, motion preference). Not a conformance claim."""
    checks = []
    for fg, bg, floor, use in (("ink", "paper", 4.5, "body text"), ("paper", "ink", 4.5, "inverse text"),
                               ("accent", "paper", 3.0, "graphics and large text"), ("muted", "paper", 3.0, "secondary UI")):
        ratio = wcag_contrast_ratio(palette[fg], palette[bg])
        checks.append({"check": f"contrast.{fg}_on_{bg}", "use": use, "value": ratio, "threshold": floor, "passed": ratio >= floor,
                       "method": "WCAG 2.2 relative luminance"})
    checks.append({"check": "target.min_px", "value": genome_rules["interaction"]["min_target_px"], "threshold": 24,
                   "passed": genome_rules["interaction"]["min_target_px"] >= 24, "method": "WCAG 2.2 SC 2.5.8"})
    checks.append({"check": "motion.reduced_alternative", "value": genome_rules["motion"].get("reduced_motion"),
                   "passed": bool(genome_rules["motion"].get("reduced_motion")), "method": "prefers-reduced-motion fallback declared"})
    checks.append({"check": "text.min_body_px", "value": genome_rules["typography"].get("min_body_px"), "threshold": 16,
                   "passed": (genome_rules["typography"].get("min_body_px") or 0) >= 16, "method": "compiler floor"})
    spec = ui_ir.accessibility
    return {"checks": checks, "passed": all(c["passed"] for c in checks), "standard": spec.target,
            "acceptance_criteria": [r.model_dump(mode="json") for r in spec.requirements], "tests_required": list(spec.tests_required),
            "note": "deterministic checks; manual screen-reader and cognitive review remain human tasks"}


def compile_experience(p: GenomeProjection, req: ExperienceRequest, *, project_id: str) -> dict[str, Any]:
    """Compile every stage. Pure and deterministic for the same inputs; no browser, no storage."""
    p = p.fresh()
    genome = creative_genome(p, project_id=project_id, deliverables=("genome", "website_section", "design_tokens"),
                             desired_action=req.primary_action, objective=req.objective, audience=req.audience)
    stages: list[dict[str, Any]] = []
    intents = intent_graph(req, p)
    stages.append(_stage("creative_intent_graph", intents, ["request", "genome:strategy.*"]))
    ui_req = UIUXRequest(project_ref=project_id, surface=SURFACE[req.target], platform=Platform.web_responsive, purpose=req.objective,
                         primary_user=req.audience or p.text("strategy.audience.primary"), primary_task=req.primary_action,
                         business_goal=req.conversion_goal, content_requirements=list(req.content_requirements),
                         locale_rtl=req.locale_rtl, brand=brand_context(p))
    ui_ir = compile_uiux(ui_req)
    stages.append(_stage("experience_architecture", {"mode": ui_ir.mode.value, "information_architecture":
                                                     ui_ir.information_architecture.model_dump(mode="json"),
                                                     "flows": [f.model_dump(mode="json") for f in ui_ir.flows],
                                                     "screens": [s.model_dump(mode="json") for s in ui_ir.screens]},
                         ["agency.ui_ux.compile_uiux", "creative_intent_graph"]))
    token_doc, css, token_src = compile_tokens(genome)
    stages.append(_stage("design_tokens", {"dtcg": token_doc, "source_hash": token_src, "css_sha256": canonical_hash(css)},
                         ["agency.design_tokens via foundry token document", "genome:visual.color.*", "genome:visual.typography.*"]))
    stages.append(_stage("component_specifications", {"components": [c.model_dump(mode="json") for c in ui_ir.components],
                                                      "states": [s.model_dump(mode="json") for s in ui_ir.states]},
                         ["experience_architecture"]))
    stages.append(_stage("responsive_layout_rules", {"rules": [r.model_dump(mode="json") for r in ui_ir.responsive_rules],
                                                     "reflow_min_width_px": genome.accessibility_constraints["reflow_min_width_px"]},
                         ["experience_architecture", "genome accessibility constraints"]))
    stages.append(_stage("interaction_contracts", {"interactions": [i.model_dump(mode="json") for i in ui_ir.interactions],
                                                   "motion": {**genome.motion_rules}}, ["component_specifications"]))
    a11y = accessibility_validation(genome.palette.roles(), ui_ir, {"interaction": genome.interaction_rules, "motion": genome.motion_rules,
                                                                    "typography": genome.typography_rules})
    stages.append(_stage("accessibility_validation", a11y, ["design_tokens", "interaction_contracts"]))
    implementation: dict[str, Any]
    html: Optional[str] = None
    if req.target in RENDERABLE:
        ir = twin.compile_experience(genome, _brief_for(p, req), headline=req.headline or req.objective[:60],
                                     subhead=req.subhead or p.text("strategy.positioning.statement")[:160],
                                     cta=(req.primary_action or "Learn more")[:28])
        offerings = tuple((c.title, c.body) for c in req.content) or (("Offering", "Describe this offering."),)
        html = twin.render_html(ir, genome, offerings=offerings)
        implementation = {"status": "IMPLEMENTED", "kind": "working HTML/CSS/JS section with form states", "experience_ir_hash":
                          ir.content_hash, "html_sha256": canonical_hash(html), "tokens_css_sha256": canonical_hash(css),
                          "placeholder_content": not req.content}
    else:
        implementation = {"status": "SPEC_ONLY", "kind": "no renderer for this target; implement from the compiled specification",
                          "implementation_mapping": ui_ir.implementation_mapping.model_dump(mode="json")}
    stages.append(_stage("implementation_artifacts", implementation, ["component_specifications", "design_tokens"]))
    stages.insert(0, _stage("genome_context", p.trace(), ["vnexus genome resolution"]))
    package = {"compiler": EXPERIENCE_COMPILER, "target": req.target.value, "request_hash": canonical_hash(req.model_dump(mode="json")),
               "genome_ref": p.genome_ref, "resolution_hash": p.resolution_hash, "creative_genome_hash": genome.content_hash,
               "stages": stages, "assumptions": intents["assumptions"] + [f"genome key missing: {k}" for k in p.trace()["keys_missing"]]}
    package["package_hash"] = canonical_hash(package)
    return {"package": package, "html": html, "tokens_css": css, "genome": genome}


def _brief_for(p: GenomeProjection, req: ExperienceRequest):
    from .bridge import foundry_brief

    return foundry_brief(p, deliverables=("website_section",), desired_action=req.primary_action, objective=req.objective,
                         audience=req.audience)


def verify(html: Optional[str], genome: Any, *, out_dir: Path, first_offering: str = "Offering") -> dict[str, Any]:
    """Run the foundry scenario suite in local Chromium. NOT_RUN is reported, never treated as a pass."""
    if html is None:
        return {"status": "NOT_APPLICABLE", "reason": "SPEC_ONLY target has no implementation to run"}
    from services.langgraph.agency.visual.browser import probe_browser

    probe = probe_browser()
    if not probe.get("available"):
        return {"status": "NOT_RUN", "reason": "local Chromium unavailable", "blockers": probe.get("blockers", [])}
    result = twin.evaluate(html, out_dir=out_dir, primary_font=genome.typography_rules["stacks"]["display"][0],
                           first_offering=first_offering)
    return {"status": result["status"], "findings": result["findings"], "scenarios": [{"id": s["id"], "passed": s["passed"]}
                                                                                       for s in result["scenarios"]],
            "network_isolated": result["network_isolated"], "browser": result["browser"]}


__all__ = ["ContentItem", "EXPERIENCE_COMPILER", "ExperienceRequest", "ExperienceTarget", "RENDERABLE", "accessibility_validation",
           "compile_experience", "intent_graph", "verify"]
