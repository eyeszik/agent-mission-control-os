"""Brief -> MissionIR.

Critical unknowns (goal, audience, artifact type, desired action, brand name)
stop compilation with ``HITL_REQUIRED`` and the questions to ask. Noncritical
unknowns become explicit, recorded assumptions. Contradictory hard
constraints stop with ``CONTRADICTORY_CONSTRAINTS``: nothing downstream may
try to "average" them away.

The compiler adds the repository's standing hard constraints (WCAG 2.2 AA
contrast, landmarks, image alternatives, truthful CTA, verified claims only,
abstract-only references, no secrets, human approval before delivery) so they
are part of the hashed mission rather than implicit behaviour.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.execution.canonical import canonical_hash

from .ir import (
    ApprovalPolicy,
    Asset,
    Constraint,
    ConstraintKind,
    ExplorationPolicy,
    MissionIR,
    Objective,
    Provenance,
    ResourceBudget,
    mission_hash_of,
)

COMPILER_VERSION = "amc-creative-mission/v1"
_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")

FAMILY: dict[str, str] = {
    "brand_identity": "brand", "logo": "visual", "image": "visual", "illustration": "visual",
    "landing_page": "interface", "marketing_site": "interface", "dashboard": "interface", "mobile_ui": "interface",
    "social_post": "content", "motion": "motion", "video": "motion",
    "design_system": "system", "design_handoff": "system",
}
INTERFACE_TYPES = frozenset({"landing_page", "marketing_site", "dashboard", "mobile_ui"})
# Artifact types whose quality benefits from comparing materially different concepts.
EXPLORATORY_TYPES = frozenset({"landing_page", "marketing_site", "brand_identity", "logo"})
EXPLORATION_CUES = re.compile(r"\b(premium|distinctive|explore|concepts?|options|variations?|bold|differentiat\w*)\b", re.I)
DEFAULT_PALETTE = {"primary": "#1f3a5f", "secondary": "#2f7d6d", "surface": "#ffffff", "text": "#16181d"}


class MissionCompilation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["READY", "HITL_REQUIRED", "CONTRADICTORY_CONSTRAINTS"]
    mission: Optional[MissionIR] = None
    unresolved_questions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) else ""


def _list(value: Any) -> list[str]:
    return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, (list, tuple)) else []


def _c(cid: str, kind: ConstraintKind, source: str, description: str = "", **params: Any) -> Constraint:
    return Constraint(constraint_id=cid, kind=kind, source=source, description=description, params=params)


def compile_mission(brief: Mapping[str, Any], *, run_id: str) -> MissionCompilation:
    brand = brief.get("brand") if isinstance(brief.get("brand"), Mapping) else {}
    req = brief.get("requirements") if isinstance(brief.get("requirements"), Mapping) else {}
    artifact_type = _text(brief.get("artifact_type"))

    questions: list[str] = []
    critical = {
        "business_goal": "What business outcome should this artifact move?",
        "audience": "Who is the primary audience?",
        "desired_action": "What single action should the audience take?",
    }
    for key, question in critical.items():
        if not _text(brief.get(key)):
            questions.append(question)
    if artifact_type not in FAMILY:
        questions.append(f"Which artifact is needed? Supported: {', '.join(sorted(FAMILY))}.")
    if not _text(brand.get("name")):
        questions.append("What is the brand name to use?")
    if questions:
        return MissionCompilation(status="HITL_REQUIRED", unresolved_questions=tuple(questions))

    assumptions: list[str] = []
    user_goal = _text(brief.get("user_goal"))
    if not user_goal:
        user_goal = _text(brief.get("desired_action"))
        assumptions.append("user_goal not supplied; assumed equal to desired_action")
    channel = _text(brief.get("channel"))
    if not channel:
        channel = "web"
        assumptions.append("channel not supplied; assumed web")
    palette_in = brand.get("palette") if isinstance(brand.get("palette"), Mapping) else {}
    palette = {k: str(v).lower() for k, v in palette_in.items() if _HEX6.match(str(v))}
    palette_supplied = all(role in palette for role in DEFAULT_PALETTE)
    if not palette_supplied:
        palette = {**DEFAULT_PALETTE, **palette}
        assumptions.append("brand palette incomplete; neutral house palette fills missing roles and brand fidelity is unverified")
    heading_font = _text(brand.get("heading_font")) or "Inter"
    body_font = _text(brand.get("body_font")) or "Inter"
    if not _text(brand.get("heading_font")):
        assumptions.append("heading font not supplied; assumed Inter")

    required_sections = _list(req.get("required_sections"))
    forbidden_sections = _list(req.get("forbidden_sections"))
    required_text = _list(req.get("required_text"))
    forbidden = _list(req.get("forbidden_phrases"))
    verified_claims = _list(req.get("verified_claims"))

    contradictions = sorted(
        [f"section '{s}' is both required and forbidden" for s in set(required_sections) & set(forbidden_sections)]
        + [f"required text '{t}' contains forbidden phrase '{f}'" for t in required_text for f in forbidden if f.lower() in t.lower()]
    )
    if contradictions:
        return MissionCompilation(status="CONTRADICTORY_CONSTRAINTS", contradictions=tuple(contradictions), assumptions=tuple(assumptions))

    hard: list[Constraint] = [_c(f"req.section.{s}", ConstraintKind.REQUIRED_SECTION, "user", section=s) for s in required_sections]
    hard += [_c(f"req.no_section.{s}", ConstraintKind.FORBIDDEN_SECTION, "user", section=s) for s in forbidden_sections]
    hard += [_c(f"req.text.{i}", ConstraintKind.REQUIRED_TEXT, "user", text=t) for i, t in enumerate(required_text)]
    hard += [_c(f"req.forbidden.{i}", ConstraintKind.FORBIDDEN_PHRASE, "user", phrase=f) for i, f in enumerate(forbidden)]
    hard.append(_c("req.verified_claims", ConstraintKind.VERIFIED_CLAIMS_ONLY, "user",
                   "Quantified or comparative claims must come from the verified claim list.", claims=verified_claims))
    if "max_headline_words" in req:
        hard.append(_c("req.headline_words", ConstraintKind.MAX_HEADLINE_WORDS, "user", max=int(req["max_headline_words"])))
    cta = brief.get("cta") if isinstance(brief.get("cta"), Mapping) else {}
    hard.append(_c("req.cta", ConstraintKind.CTA_TRUTHFUL, "user", "The CTA never implies an integration that is not verified.",
                   destination=_text(cta.get("destination")) or None,
                   integration_status=_text(cta.get("integration_status")) or "unavailable"))

    brand_constraints = [_c("brand.name", ConstraintKind.BRAND_NAME, "brand", name=_text(brand.get("name")))]
    brand_constraints.append(_c("brand.palette", ConstraintKind.BRAND_PALETTE, "brand",
                                "Every literal colour within dE76 2.3 of the palette.", palette=palette, supplied=palette_supplied,
                                heading_font=heading_font, body_font=body_font))
    accessibility: list[Constraint] = []
    implementation: list[Constraint] = []
    if artifact_type in INTERFACE_TYPES:
        accessibility = [
            _c("a11y.contrast", ConstraintKind.WCAG_CONTRAST, "accessibility", "WCAG 2.2 AA 4.5:1 for text.", min_ratio=4.5),
            _c("a11y.landmarks", ConstraintKind.SEMANTIC_LANDMARKS, "accessibility", landmarks=["header", "main", "footer"]),
            _c("a11y.alt", ConstraintKind.IMAGE_ALT, "accessibility"),
        ]
        implementation = [
            _c("impl.no_external_scripts", ConstraintKind.NO_EXTERNAL_SCRIPTS, "implementation"),
            _c("impl.max_bytes", ConstraintKind.MAX_HTML_BYTES, "implementation", max=int(req.get("max_html_bytes", 200_000))),
        ]
    rights = [_c("rights.references", ConstraintKind.RIGHTS_ABSTRACT_REFERENCES, "rights",
                 "Reference sources contribute abstract principles only; unknown rights are excluded.")]
    security = [_c("security.no_secrets", ConstraintKind.SECURITY_NO_SECRETS, "security")]
    hard.append(_c("approval.delivery", ConstraintKind.HUMAN_APPROVAL_BEFORE_DELIVERY, "approval"))

    objectives = tuple(Objective(name=n) for n in (
        "brand_fidelity", "distinctiveness", "clarity", "accessibility_quality",
        "visual_coherence", "implementation_feasibility", "conversion_clarity", "content_quality",
    ))
    exploration_in = brief.get("exploration") if isinstance(brief.get("exploration"), Mapping) else {}
    requested = exploration_in.get("candidates")
    mode = exploration_in.get("mode") or "auto"
    budget = ResourceBudget(**{k: v for k, v in (brief.get("budget") or {}).items() if k in ResourceBudget.model_fields})
    # Asset order carries no meaning; canonical order keeps the mission hash (and so
    # every seeded choice downstream) independent of how the brief listed them.
    assets = tuple(sorted((Asset.model_validate(a) for a in brief.get("assets") or []), key=lambda a: (a.asset_id, a.ref)))

    body: dict[str, Any] = dict(
        business_goal=_text(brief.get("business_goal")),
        user_goal=user_goal,
        audience=_text(brief.get("audience")),
        artifact_family=FAMILY[artifact_type],
        artifact_type=artifact_type,
        channel=channel,
        desired_action=_text(brief.get("desired_action")),
        brand_name=_text(brand.get("name")),
        hard_constraints=tuple(hard),
        soft_objectives=objectives,
        brand_constraints=tuple(brand_constraints),
        accessibility_constraints=tuple(accessibility),
        implementation_constraints=tuple(implementation),
        rights_constraints=tuple(rights),
        security_constraints=tuple(security),
        available_assets=assets,
        approved_sources=tuple(_list(brief.get("approved_sources"))),
        exploration_policy=ExplorationPolicy(mode=mode, candidates_requested=requested),
        resource_budget=budget,
        approval_policy=ApprovalPolicy(),
        assumptions=tuple(assumptions),
        unresolved_questions=(),
        provenance=Provenance(brief_hash=canonical_hash({**dict(brief), "assets": [a.model_dump(mode="json") for a in assets]}),
                              compiler_version=COMPILER_VERSION),
    )
    draft = MissionIR.model_construct(**body)
    digest = mission_hash_of(draft)
    mission = MissionIR(**body, mission_id=f"mission-{digest[:16]}", run_id=run_id, mission_hash=digest)
    return MissionCompilation(status="READY", mission=mission, assumptions=tuple(assumptions))


def wants_exploration(mission: MissionIR, brief_text: str = "") -> bool:
    policy = mission.exploration_policy
    if policy.mode == "single":
        return False
    if policy.mode == "explore" or (policy.candidates_requested or 0) > 1:
        return True
    return mission.artifact_type in EXPLORATORY_TYPES and bool(
        EXPLORATION_CUES.search(" ".join([mission.business_goal, mission.user_goal, brief_text]))
    )


def mission_constraint(mission: MissionIR, kind: ConstraintKind) -> list[Constraint]:
    return [c for c in mission.all_constraints() if c.kind is kind]


__all__ = ["COMPILER_VERSION", "MissionCompilation", "compile_mission", "mission_constraint", "wants_exploration"]
