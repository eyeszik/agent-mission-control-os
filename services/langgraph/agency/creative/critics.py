"""Evaluator firebreak: a hard constraint validator plus independent critics.

Firebreak rules:

- critics see a ``BlindView`` (artifact content + rendering + mission), never
  lineage: no candidate id, parent, mutation, generator, seed or score from
  another critic. Identical artifacts with different lineage therefore
  evaluate identically (tested);
- ``ConstraintValidator`` is the hard gate. It returns FEASIBLE, INFEASIBLE
  or UNKNOWN per candidate; soft scores never compensate a hard failure;
- every evaluation records ``evaluator_id``, ``rubric_version``, confidence,
  per-objective uncertainty and the evidence it used. Disagreement between
  critics on the same objective is measured, not averaged away;
- nothing here is a human-preference or market-performance prediction: these
  are deterministic, explainable structural checks, and their ``not_verified``
  lists say what they could not check without a browser or a human.
"""

from __future__ import annotations

import re
import statistics
from functools import lru_cache
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency import design_corpus as dc
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.execution_fabric.adapters.uiux import TARGET_MIN_PX, dom_audit
from services.langgraph.agency.execution_fabric.verifiers import palette_conformance, parse_dom, svg_safety
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio
from services.langgraph.security.pii import PII_PATTERNS

from .ir import ArtifactIR, ConstraintKind, Finding, MissionIR
from .landing import verified_claims
from .search import ObjectiveEstimate

RUBRIC_VERSION = "amc-creative-rubric/v1"
_TEXT_TAGS = {"h1", "h2", "h3", "p", "li", "a", "title", "button"}
_NUMERIC = re.compile(r"[^.!?]*\d[^.!?]*")
_SUPERLATIVE = re.compile(r"\b(best|#1|number one|leading|fastest|only|unmatched|world[- ]class|guaranteed?|100%)\b", re.I)
_OVERPROMISE_CTA = re.compile(r"\b(instant(ly)?|now live|automatic(ally)?|integrated|one[- ]click)\b", re.I)
_SECRETS = (
    PII_PATTERNS["api_key_like"],
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b"),
)
# Reference categories whose "Inspired by X" names are style vocabulary, not marks.
_STYLE_CATEGORIES = frozenset({"bold-expressive", "creative-artistic", "layout-structure", "modern-minimal",
                               "morphism-effects", "professional-corporate", "retro-nostalgic", "starter"})
_GENERIC_STYLE_NAMES = frozenset({"Agentic", "Futuristic"})
_PLACEHOLDER = re.compile(r"\b(lorem ipsum|tbd|todo|placeholder|xxx)\b", re.I)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BlindView(_Strict):
    """What a critic may see. Built only through ``blind_view``."""

    handle: str
    mission: MissionIR
    artifact_type: str
    content: dict
    rendering: str
    requirements: tuple[str, ...] = ()


def blind_view(mission: MissionIR, artifact: ArtifactIR, rendering: str, requirements=()) -> BlindView:
    content = artifact.model_dump(mode="json", exclude={"artifact_id", "provenance", "hash", "version", "mission_id"})
    return BlindView(handle=canonical_hash([content, rendering])[:16], mission=mission, artifact_type=artifact.artifact_type,
                     content=content, rendering=rendering, requirements=tuple(sorted(requirements)))


class Feasibility(_Strict):
    verdict: Literal["FEASIBLE", "INFEASIBLE", "UNKNOWN"]
    violations: tuple[Finding, ...] = ()
    unknown: tuple[str, ...] = ()
    checked: tuple[str, ...] = ()
    validator_id: str = "constraint_validator"
    rubric_version: str = RUBRIC_VERSION


class Evaluation(_Strict):
    evaluator_id: str
    rubric_version: str = RUBRIC_VERSION
    handle: str
    scores: dict[str, ObjectiveEstimate]
    confidence: float = Field(ge=0.0, le=1.0)
    findings: tuple[Finding, ...] = ()
    evidence: tuple[str, ...] = ()
    not_verified: tuple[str, ...] = ()


def visible_text(rendering: str) -> str:
    dom = parse_dom(rendering)
    texts = [t for tag, _, t in dom.text_by_tag if tag in _TEXT_TAGS and t]
    return "\n".join(texts)


def _f(code: str, severity: str, ref: str, *, confidence: float = 1.0, scope: Optional[str] = None) -> Finding:
    return Finding(code=code, severity=severity, confidence=confidence, evidence_ref=ref[:300], repair_scope=scope)


@lru_cache(maxsize=1)
def reference_names() -> frozenset[str]:
    """Third-party names carried by reference-only corpus entries (for leak checks)."""
    try:
        _, loaded = dc.load_validated_corpus()
    except (dc.CorpusIntegrityError, OSError):
        return frozenset()
    names = set()
    for entry, _ in loaded:
        if entry["source_class"] == dc.SOURCE_CLASS_STANDARD:
            continue
        category = next((t.split(":", 1)[1] for t in entry["tags"] if t.startswith("category:")), "")
        if category in _STYLE_CATEGORIES:
            continue  # style names ("Minimal", "Retro"), not third-party marks
        m = re.match(r"^Design System Inspired by (.+)$", entry["title"])
        if m:
            name = re.sub(r"\s*\(.*\)$", "", m.group(1)).strip()
            if name and name[0].isupper() and name not in _GENERIC_STYLE_NAMES:
                names.add(name)
    return frozenset(names)


def _mission_text(mission: MissionIR) -> str:
    parts = [mission.business_goal, mission.user_goal, mission.audience, mission.desired_action, mission.brand_name]
    parts += [a.ref for a in mission.available_assets]
    for c in mission.all_constraints():
        parts += [str(v) for v in c.params.values()]
    return " ".join(parts)


# Constraints that can only be judged on rendered HTML.
_RENDER_ONLY = frozenset({ConstraintKind.SEMANTIC_LANDMARKS, ConstraintKind.IMAGE_ALT, ConstraintKind.NO_EXTERNAL_SCRIPTS,
                          ConstraintKind.MAX_HTML_BYTES})


class ConstraintValidator:
    validator_id = "constraint_validator"

    def check(self, view: BlindView) -> Feasibility:
        m, html_text = view.mission, view.rendering
        is_html = html_text.lstrip()[:15].lower() == "<!doctype html>"
        # HTML artifacts are judged on visible text; specs and SVG on their full source.
        text = visible_text(html_text) if is_html else html_text
        lower = text.lower()
        content = view.content
        page = content.get("landing_page") or {}
        sections = [s["kind"] for s in page.get("sections", [])]
        violations: list[Finding] = []
        unknown: list[str] = []
        checked: list[str] = []
        audit = dom_audit(html_text) if view.artifact_type in {"landing_page", "marketing_site"} else None
        claims = verified_claims(m)
        for c in m.all_constraints():
            checked.append(c.constraint_id)
            k, p = c.kind, c.params
            if k is ConstraintKind.REQUIRED_SECTION and p["section"] not in sections:
                violations.append(_f("REQUIRED_SECTION_MISSING", "critical", c.constraint_id))
            elif k is ConstraintKind.FORBIDDEN_SECTION and p["section"] in sections:
                violations.append(_f("FORBIDDEN_SECTION_PRESENT", "critical", c.constraint_id))
            elif k is ConstraintKind.REQUIRED_TEXT and p["text"].lower() not in lower:
                violations.append(_f("REQUIRED_TEXT_MISSING", "critical", c.constraint_id))
            elif k is ConstraintKind.FORBIDDEN_PHRASE and re.search(rf"\b{re.escape(p['phrase'].lower())}\b", lower):
                violations.append(_f("FORBIDDEN_PHRASE_PRESENT", "critical", c.constraint_id))
            elif k is ConstraintKind.VERIFIED_CLAIMS_ONLY:
                # Audience-facing copy only: HTML visible text, SVG <text> nodes; specs carry none.
                copy = text if is_html else "\n".join(t for tag, _, t in parse_dom(html_text).text_by_tag if tag == "text")
                for line in copy.splitlines():
                    # Remove every verified claim verbatim; whatever numeric or
                    # superlative statement remains is unverified.
                    rest = line
                    for cl in sorted(claims, key=len, reverse=True):
                        rest = re.sub(re.escape(cl), " ", rest, flags=re.I)
                    for seg in _NUMERIC.findall(rest) + [mm.group(0) for mm in _SUPERLATIVE.finditer(rest)]:
                        if seg.strip():
                            violations.append(_f("UNVERIFIED_CLAIM", "critical", f"{c.constraint_id}: {seg.strip()[:120]}"))
            elif k is ConstraintKind.BRAND_NAME and p["name"].lower() not in lower:
                violations.append(_f("BRAND_NAME_MISSING", "critical", c.constraint_id))
            elif k is ConstraintKind.BRAND_PALETTE:
                verdict = palette_conformance(html_text, p["palette"].values())
                if not verdict.passed:
                    violations.append(_f("OFF_PALETTE", "critical", f"{c.constraint_id}: {verdict.detail}"))
            elif k is ConstraintKind.WCAG_CONTRAST:
                pal = (content.get("brand_bindings") or {}).get("palette") or {}
                pairs = [(pal.get("text"), pal.get("surface")), (pal.get("surface"), pal.get("primary")), (pal.get("primary"), pal.get("surface"))]
                for fg, bg in pairs:
                    if fg and bg and wcag_contrast_ratio(fg, bg) < float(p["min_ratio"]):
                        violations.append(_f("CONTRAST_BELOW_AA", "critical", f"{c.constraint_id}: {fg} on {bg}"))
                if audit:
                    violations += [_f("CONTRAST_BELOW_AA", "critical", f["detail"]) for f in audit["findings"] if f["rule"] == "contrast-aa"]
            elif k in _RENDER_ONLY and not is_html:
                unknown.append(f"{c.constraint_id}: not verifiable on a {view.artifact_type} specification; verify when implemented")
            elif k is ConstraintKind.SEMANTIC_LANDMARKS:
                tags = set(parse_dom(html_text).tags)
                missing = [t for t in p["landmarks"] if t not in tags]
                if missing:
                    violations.append(_f("LANDMARKS_MISSING", "critical", f"{c.constraint_id}: {missing}"))
            elif k is ConstraintKind.IMAGE_ALT:
                dom = parse_dom(html_text)
                bad = [t for t, a in dom.elements if (t == "img" and "alt" not in a)
                       or (t == "svg" and a.get("role") == "img" and not a.get("aria-label"))]
                if bad:
                    violations.append(_f("TEXT_ALTERNATIVE_MISSING", "critical", f"{c.constraint_id}: {bad}"))
            elif k is ConstraintKind.MAX_HEADLINE_WORDS and page:
                if len(page.get("headline", "").split()) > int(p["max"]):
                    violations.append(_f("HEADLINE_TOO_LONG", "critical", c.constraint_id, scope="headline"))
            elif k is ConstraintKind.NO_EXTERNAL_SCRIPTS:
                dom = parse_dom(html_text)
                bad = [t for t, a in dom.elements if t in {"script", "iframe", "object", "embed"}
                       or (t == "link" and a.get("href", "").startswith(("http:", "https:", "//")))
                       or any(name.startswith("on") for name in a)]
                if bad:
                    violations.append(_f("ACTIVE_OR_EXTERNAL_CODE", "critical", f"{c.constraint_id}: {sorted(set(bad))}"))
            elif k is ConstraintKind.MAX_HTML_BYTES and len(html_text.encode("utf-8")) > int(p["max"]):
                violations.append(_f("HTML_TOO_LARGE", "critical", c.constraint_id))
            elif k is ConstraintKind.CTA_TRUTHFUL and page:
                cta = page.get("cta") or {}
                dom = parse_dom(html_text)
                if any(t == "form" for t in dom.tags) and p.get("integration_status") != "verified":
                    violations.append(_f("CTA_IMPLIES_UNVERIFIED_INTEGRATION", "critical", c.constraint_id))
                if p.get("integration_status") != "verified" and _OVERPROMISE_CTA.search(cta.get("label", "")):
                    violations.append(_f("CTA_OVERPROMISES", "critical", c.constraint_id, scope="cta"))
                if p.get("destination") and cta.get("destination") != p.get("destination"):
                    violations.append(_f("CTA_DESTINATION_MISMATCH", "critical", c.constraint_id))
                if not p.get("destination"):
                    unknown.append(f"{c.constraint_id}: CTA destination not supplied; link target unverifiable")
            elif k is ConstraintKind.RIGHTS_ABSTRACT_REFERENCES:
                own = _mission_text(m)
                leaked = sorted(n for n in reference_names()
                                if re.search(rf"\b{re.escape(n)}\b", text) and not re.search(rf"\b{re.escape(n)}\b", own))
                if leaked:
                    violations.append(_f("REFERENCE_LEAK", "critical", f"{c.constraint_id}: {leaked}"))
            elif k is ConstraintKind.SECURITY_NO_SECRETS:
                if any(rx.search(html_text) for rx in _SECRETS):
                    violations.append(_f("SECRET_IN_ARTIFACT", "critical", c.constraint_id))
            elif k is ConstraintKind.HUMAN_APPROVAL_BEFORE_DELIVERY:
                pass  # enforced structurally by the delivery gate, never by the artifact
        if view.artifact_type == "logo":
            verdict = svg_safety(html_text)
            checked.append("svg_safety")
            if not verdict.passed:
                violations.append(_f("SVG_UNSAFE", "critical", verdict.detail))
        if violations:
            status = "INFEASIBLE"
        elif unknown:
            status = "UNKNOWN"
        else:
            status = "FEASIBLE"
        return Feasibility(verdict=status, violations=tuple(sorted(violations, key=lambda f: (f.code, f.evidence_ref))),
                           unknown=tuple(unknown), checked=tuple(checked))


# --------------------------------------------------------------------------- critics


def _score(value: float, uncertainty: float) -> ObjectiveEstimate:
    return ObjectiveEstimate(value=round(max(0.0, min(1.0, value)), 4), uncertainty=round(uncertainty, 4))


def _css(rendering: str) -> str:
    m = re.search(r"<style>(.*?)</style>", rendering, re.S)
    return m.group(1) if m else ""


class AccessibilityCritic:
    evaluator_id = "accessibility_critic"

    def evaluate(self, view: BlindView) -> Evaluation:
        html_text, css = view.rendering, _css(view.rendering)
        audit = dom_audit(html_text)
        findings: list[Finding] = [_f(f"A11Y_{f['rule'].upper()}", "major", f["detail"]) for f in audit["findings"]]
        checks = 6
        passed = checks - min(checks, len(findings))
        has_motion = bool(re.search(r"transition|animation|scroll-behavior:smooth", css))
        if has_motion and "prefers-reduced-motion" not in css:
            findings.append(_f("MOTION_WITHOUT_REDUCED_MOTION_GUARD", "major", "SC 2.3.3 / Contract 02 reduced motion", scope="style"))
        else:
            passed += 1
        if ":focus-visible" not in css:
            findings.append(_f("FOCUS_STYLE_NOT_DECLARED", "major", "SC 2.4.7 / 2.4.11 visible focus", scope="style"))
        else:
            passed += 1
        declared = [int(x) for x in re.findall(r"\.cta\{[^}]*?min-height:\s*(\d+)px", css)]
        if not declared or min(declared) < TARGET_MIN_PX:
            findings.append(_f("TARGET_SIZE_UNVERIFIED", "minor", f"SC 2.5.8 targets >= {TARGET_MIN_PX}px not declared", scope="style"))
        else:
            passed += 1
        dom = parse_dom(html_text)
        heads = [t for t in dom.tags if re.fullmatch(r"h[1-6]", t)]
        levels = [int(h[1]) for h in heads]
        if levels.count(1) != 1 or any(b - a > 1 for a, b in zip(levels, levels[1:])):
            findings.append(_f("HEADING_STRUCTURE", "major", f"heading levels {levels}"))
        else:
            passed += 1
        total = checks + 4
        score = passed / total
        return Evaluation(evaluator_id=self.evaluator_id, handle=view.handle,
                          scores={"accessibility_quality": _score(score, 0.05)}, confidence=0.8,
                          findings=tuple(findings), evidence=(f"dom_audit passed={audit['passed']}", f"contrast_pairs={len(audit['contrast_pairs'])}"),
                          not_verified=tuple(audit["not_verified"]))


class BrandCritic:
    evaluator_id = "brand_critic"

    def evaluate(self, view: BlindView) -> Evaluation:
        bindings = view.content.get("brand_bindings") or {}
        palette = bindings.get("palette") or {}
        brand_c = next((c for c in view.mission.brand_constraints if c.kind is ConstraintKind.BRAND_PALETTE), None)
        supplied = bool(brand_c and brand_c.params.get("supplied"))
        findings: list[Finding] = []
        verdict = palette_conformance(view.rendering, palette.values()) if palette else None
        score = 0.0
        score += 0.4 if verdict and verdict.passed else 0.0
        name = view.mission.brand_name
        score += 0.2 if name.lower() in view.rendering.lower() else 0.0
        fonts = [bindings.get("heading_font"), bindings.get("body_font")]
        score += 0.2 if all(f and f in view.rendering for f in fonts) else (0.2 if view.artifact_type == "logo" else 0.0)
        used_roles = sum(1 for v in palette.values() if v in view.rendering.lower())
        score += 0.2 * (used_roles / max(1, len(palette)))
        if not supplied:
            findings.append(_f("BRAND_FIDELITY_UNVERIFIED", "minor", "brand palette incomplete; house palette filled missing roles"))
        if verdict and not verdict.passed:
            findings.append(_f("OFF_PALETTE", "major", verdict.detail))
        return Evaluation(evaluator_id=self.evaluator_id, handle=view.handle,
                          scores={"brand_fidelity": _score(score, 0.05 if supplied else 0.25)},
                          confidence=0.85 if supplied else 0.4, findings=tuple(findings),
                          evidence=(verdict.detail if verdict else "no palette",),
                          not_verified=("logo/mark fidelity to an approved master", "tone of voice"))


class ArtifactCritic:
    """Design critic: hierarchy, clarity and coherence from structure only."""

    evaluator_id = "artifact_critic"

    def evaluate(self, view: BlindView) -> Evaluation:
        page = view.content.get("landing_page") or {}
        findings: list[Finding] = []
        sections = page.get("sections", [])
        concept = page.get("concept", {})
        headline_words = len(page.get("headline", "").split())
        clarity = 1.0 - 0.08 * max(0, headline_words - 8)
        sub_words = len(page.get("subheadline", "").split())
        if sub_words > 30:
            clarity -= 0.2
            findings.append(_f("SUBHEADLINE_LONG", "minor", f"{sub_words} words", scope="subheadline"))
        body_sections = [s for s in sections if s["kind"] not in {"hero", "cta", "footer"}]
        if concept.get("hierarchy") == "single_focus" and len(body_sections) > 4:
            findings.append(_f("HIERARCHY_DILUTED", "minor", f"{len(body_sections)} supporting sections for single focus",
                               scope="structure"))
        empty = [s["kind"] for s in sections if s["kind"] not in {"footer"} and not (s.get("body") or s.get("items"))]
        if empty:
            findings.append(_f("EMPTY_SECTION", "major", f"sections without content: {empty}", scope="brief"))
        coherence = 1.0 - 0.15 * len(empty) - (0.1 if len(body_sections) > 6 else 0.0)
        css = _css(view.rendering)
        if concept.get("composition") == "editorial" and "border-left" not in css:
            coherence -= 0.1
        # Distinct literal colours beyond the four palette roles hurt coherence.
        colours = set(re.findall(r"#[0-9a-fA-F]{6}\b", view.rendering.lower()))
        coherence -= 0.05 * max(0, len(colours) - 4)
        return Evaluation(evaluator_id=self.evaluator_id, handle=view.handle,
                          scores={"clarity": _score(clarity, 0.1), "visual_coherence": _score(coherence, 0.15)},
                          confidence=0.6, findings=tuple(findings),
                          evidence=(f"headline_words={headline_words}", f"sections={len(sections)}"),
                          not_verified=("rendered visual balance", "imagery quality", "human aesthetic preference"))


class ImplementationCritic:
    evaluator_id = "implementation_critic"

    def evaluate(self, view: BlindView) -> Evaluation:
        html_text = view.rendering
        findings: list[Finding] = []
        size = len(html_text.encode("utf-8"))
        score = 1.0
        if size > 60_000:
            score -= 0.2
            findings.append(_f("PAGE_HEAVY", "minor", f"{size} bytes"))
        dom = parse_dom(html_text)
        if any(name.startswith("on") for _, a in dom.elements for name in a):
            score -= 0.5
            findings.append(_f("INLINE_HANDLER", "major", "inline event handler"))
        css = _css(html_text)
        if not re.search(r":root\s*\{[^}]*--color-", css):
            score -= 0.1
            findings.append(_f("NO_CUSTOM_PROPERTIES", "minor", "palette not exposed as CSS custom properties", scope="style"))
        if re.search(r"width:\s*\d{3,}px", html_text):
            score -= 0.2
            findings.append(_f("FIXED_WIDTH", "major", "fixed pixel width", scope="style"))
        ids = [a.get("id") for _, a in dom.elements if a.get("id")]
        if len(ids) != len(set(ids)):
            score -= 0.3
            findings.append(_f("DUPLICATE_ID", "major", "duplicate element ids", scope="structure"))
        return Evaluation(evaluator_id=self.evaluator_id, handle=view.handle,
                          scores={"implementation_feasibility": _score(score, 0.05)}, confidence=0.9,
                          findings=tuple(findings), evidence=(f"bytes={size}", f"elements={len(dom.elements)}"),
                          not_verified=("browser rendering", "build integration"))


class ContentCritic:
    evaluator_id = "content_critic"

    def evaluate(self, view: BlindView) -> Evaluation:
        page = view.content.get("landing_page") or {}
        text = visible_text(view.rendering)
        findings: list[Finding] = []
        cta = (page.get("cta") or {}).get("label", "")
        cta_count = view.rendering.count('class="cta"')
        conversion = 0.4 + (0.3 if cta_count >= 2 else 0.15 if cta_count == 1 else 0.0)
        if cta and cta.split()[0][:1].isupper() and not cta.lower().startswith(("learn", "click", "submit")):
            conversion += 0.3
        else:
            findings.append(_f("CTA_NOT_ACTION_LED", "minor", cta, scope="cta"))
        if cta_count == 0:
            findings.append(_f("NO_CTA", "major", "no call to action rendered", scope="structure"))
        quality = 1.0
        if _PLACEHOLDER.search(text):
            quality -= 0.5
            findings.append(_f("PLACEHOLDER_TEXT", "major", "placeholder copy", scope="brief"))
        sentences = [s for s in re.split(r"[.!?]\s", text) if s.strip()]
        avg = statistics.mean(len(s.split()) for s in sentences) if sentences else 0
        if avg > 22:
            quality -= 0.2
            findings.append(_f("LONG_SENTENCES", "minor", f"mean {avg:.1f} words"))
        sourced = sum(1 for s in page.get("sections", []) if s.get("source_refs"))
        quality -= 0.1 * max(0, len(page.get("sections", [])) - sourced)
        return Evaluation(evaluator_id=self.evaluator_id, handle=view.handle,
                          scores={"conversion_clarity": _score(conversion, 0.15), "content_quality": _score(quality, 0.1)},
                          confidence=0.6, findings=tuple(findings),
                          evidence=(f"cta_count={cta_count}", f"mean_sentence_words={avg:.1f}"),
                          not_verified=("persuasiveness for the audience", "market performance"))


CRITICS: dict[str, type] = {
    "cap.critic.accessibility": AccessibilityCritic,
    "cap.critic.brand": BrandCritic,
    "cap.critic.design": ArtifactCritic,
    "cap.critic.implementation": ImplementationCritic,
    "cap.critic.content": ContentCritic,
}
EVALUATOR_VERSIONS = tuple(sorted(f"{c.evaluator_id}@{RUBRIC_VERSION}" for c in CRITICS.values())) + (
    f"constraint_validator@{RUBRIC_VERSION}",)


def aggregate(evaluations: list[Evaluation]) -> tuple[dict[str, ObjectiveEstimate], dict[str, float]]:
    """Per objective: mean value, uncertainty = max(declared, critic spread). Returns (scores, disagreement)."""
    buckets: dict[str, list[ObjectiveEstimate]] = {}
    for ev in evaluations:
        for name, est in ev.scores.items():
            buckets.setdefault(name, []).append(est)
    scores: dict[str, ObjectiveEstimate] = {}
    disagreement: dict[str, float] = {}
    for name, ests in sorted(buckets.items()):
        values = [e.value for e in ests]
        spread = round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0
        disagreement[name] = spread
        scores[name] = _score(statistics.mean(values), max(max(e.uncertainty for e in ests), spread))
    return scores, disagreement


def run_critics(view: BlindView, critic_ids: list[str] | tuple[str, ...]) -> list[Evaluation]:
    return [CRITICS[c]().evaluate(view) for c in sorted(critic_ids) if c in CRITICS]


__all__ = [
    "AccessibilityCritic", "ArtifactCritic", "BlindView", "BrandCritic", "CRITICS", "ConstraintValidator", "ContentCritic",
    "EVALUATOR_VERSIONS", "Evaluation", "Feasibility", "ImplementationCritic", "RUBRIC_VERSION", "aggregate",
    "blind_view", "reference_names", "run_critics", "visible_text",
]
