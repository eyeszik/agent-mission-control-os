"""T13 — AutonomyClassifier (L0-L6) and task routing.

The classifier routes on *task properties*. A performance score, model
confidence or evaluation history can never, on its own, move consequential
work above L5 (exact approval); L6 bounded autonomy additionally requires an
explicit governance approval ref (AUTONOMY_ESCROW) and a proven narrow scope.
"Lead" is never granted universally.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

_FROZEN = {"frozen": True, "extra": "forbid"}


class AutonomyLevel(str, Enum):
    L0_OBSERVE = "L0_OBSERVE"
    L1_ASSIST = "L1_ASSIST"
    L2_ENHANCE = "L2_ENHANCE"
    L3_SUPERCHARGE = "L3_SUPERCHARGE"
    L4_DRIVE = "L4_DRIVE"
    L5_APPROVED_EXTERNAL = "L5_APPROVED_EXTERNAL"
    L6_BOUNDED_AUTONOMY = "L6_BOUNDED_AUTONOMY"


SOURCE_TERMINOLOGY = {
    "Assist": AutonomyLevel.L1_ASSIST,
    "Enhance": AutonomyLevel.L2_ENHANCE,
    "Supercharge": AutonomyLevel.L3_SUPERCHARGE,
    "Drive": AutonomyLevel.L4_DRIVE,
    # "Lead" maps to L5 or L6 depending on consequence and governance; never universal.
}


class AutonomyRoute(str, Enum):
    AUTOMATE = "AUTOMATE"
    AI_EXECUTE_MACHINE_VALIDATE = "AI_EXECUTE_MACHINE_VALIDATE"
    AI_GENERATE_HUMAN_SELECT = "AI_GENERATE_HUMAN_SELECT"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    SPECIALIST_REVIEW = "SPECIALIST_REVIEW"
    BLOCK_RESEARCH = "BLOCK_RESEARCH"


class Level(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskSuitability(BaseModel):
    model_config = _FROZEN

    determinism: Level
    ambiguity: Level
    consequence: Level
    reversible: bool
    data_sensitivity: Level
    creative_judgment: Level
    factual_verifiability: Level
    tool_reliability: Level
    evaluation_history: int = Field(default=0, ge=0)
    # Domain flags that force specialist/human handling regardless of scores.
    legal_public_financial_or_client_binding: bool = False
    rights_privacy_security_uncertain: bool = False
    evidence_sufficient: bool = True
    # Model/eval score — recorded, but never an authority input on its own.
    performance_score: float | None = None
    governance_approval_ref: str | None = None
    proven_narrow_scope: bool = False


class AutonomyDecision(BaseModel):
    model_config = _FROZEN

    route: AutonomyRoute
    level: AutonomyLevel
    reasons: tuple[str, ...]


def classify(task: TaskSuitability) -> AutonomyDecision:
    reasons: list[str] = []
    if not task.evidence_sufficient:
        return AutonomyDecision(route=AutonomyRoute.BLOCK_RESEARCH, level=AutonomyLevel.L0_OBSERVE,
                                reasons=("insufficient evidence",))
    if task.rights_privacy_security_uncertain:
        return AutonomyDecision(route=AutonomyRoute.SPECIALIST_REVIEW, level=AutonomyLevel.L1_ASSIST,
                                reasons=("rights/privacy/security uncertainty",))
    if task.legal_public_financial_or_client_binding or not task.reversible or task.consequence is Level.HIGH:
        reasons.append("consequential, public, binding or irreversible")
        level = AutonomyLevel.L5_APPROVED_EXTERNAL
        # AUTONOMY_ESCROW: L6 needs evaluated history + governance approval +
        # a proven narrow subprocess. A score alone is never enough.
        if task.governance_approval_ref and task.proven_narrow_scope and task.evaluation_history >= 1:
            level = AutonomyLevel.L6_BOUNDED_AUTONOMY
            reasons.append("governance-approved bounded subprocess")
        return AutonomyDecision(route=AutonomyRoute.HUMAN_APPROVAL_REQUIRED, level=level, reasons=tuple(reasons))
    if (
        task.determinism is Level.HIGH
        and task.factual_verifiability is Level.HIGH
        and task.consequence is Level.LOW
        and task.tool_reliability is not Level.LOW
    ):
        return AutonomyDecision(route=AutonomyRoute.AUTOMATE, level=AutonomyLevel.L4_DRIVE,
                                reasons=("deterministic, verifiable, reversible, low consequence",))
    if task.factual_verifiability is Level.HIGH and task.ambiguity is not Level.HIGH:
        return AutonomyDecision(route=AutonomyRoute.AI_EXECUTE_MACHINE_VALIDATE, level=AutonomyLevel.L3_SUPERCHARGE,
                                reasons=("structured and machine-verifiable",))
    if task.creative_judgment is not Level.LOW:
        return AutonomyDecision(route=AutonomyRoute.AI_GENERATE_HUMAN_SELECT, level=AutonomyLevel.L2_ENHANCE,
                                reasons=("creative/judgment work; human selects",))
    return AutonomyDecision(route=AutonomyRoute.AI_GENERATE_HUMAN_SELECT, level=AutonomyLevel.L2_ENHANCE,
                            reasons=("default: draft for expert refinement",))


_CREATIVE = {"creative_concept", "copy_variant", "asset_prompt_set", "naming_candidate", "brand_platform",
             "identity_guidelines", "design_brief", "positioning_statement"}
_STRUCTURED = {"design_token_set", "design_system_spec", "implementation_plan", "app_build_spec", "automation_spec",
               "measurement_plan", "qa_report", "website_lockup_spec"}
_RESEARCH = {"research_brief", "market_analysis", "knowledge_capsule"}


def suitability_for_node(
    *,
    artifact_type: str | None,
    side_effect_class: str,
    evidence_sufficient: bool = True,
    rights_uncertain: bool = False,
) -> TaskSuitability:
    """Derive task properties from the compiled node. Deterministic and conservative."""
    consequential = side_effect_class in {"REVERSIBLE_WRITE", "IRREVERSIBLE_WRITE"}
    creative = artifact_type in _CREATIVE
    structured = artifact_type in _STRUCTURED
    return TaskSuitability(
        determinism=Level.HIGH if structured else Level.LOW if creative else Level.MEDIUM,
        ambiguity=Level.HIGH if creative else Level.MEDIUM,
        consequence=Level.HIGH if consequential else Level.MEDIUM if artifact_type in {"release_record", "media_plan"} else Level.LOW,
        reversible=side_effect_class != "IRREVERSIBLE_WRITE",
        data_sensitivity=Level.MEDIUM if artifact_type in {"measurement_plan", "media_plan"} else Level.LOW,
        creative_judgment=Level.HIGH if creative else Level.LOW,
        factual_verifiability=Level.HIGH if structured else Level.MEDIUM if artifact_type in _RESEARCH else Level.LOW,
        tool_reliability=Level.MEDIUM,
        legal_public_financial_or_client_binding=consequential,
        rights_privacy_security_uncertain=rights_uncertain,
        evidence_sufficient=evidence_sufficient,
    )
