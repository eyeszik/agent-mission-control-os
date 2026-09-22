"""Typed contracts for selectively retrieved expert guidance.

Guidance is advisory data. It can improve how a prompt is compiled, but it can
never redefine runtime policy, verified facts, canonical BrandCore state,
permissions, provider capabilities, or terminal-state semantics.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class GuidanceDomain(str, Enum):
    branding = "BRANDING"
    graphic_design = "GRAPHIC_DESIGN"
    design_system = "DESIGN_SYSTEM"
    ui_ux = "UI_UX"
    web_design = "WEB_DESIGN"
    web_development = "WEB_DEVELOPMENT"
    motion = "MOTION"
    video = "VIDEO"
    storyboard = "STORYBOARD"
    marketing = "MARKETING"
    advertising = "ADVERTISING"
    social = "SOCIAL"
    copywriting = "COPYWRITING"
    presentation = "PRESENTATION"
    print = "PRINT"
    packaging = "PACKAGING"
    creative_tech = "CREATIVE_TECH"
    design_trends = "DESIGN_TRENDS"


class GuidanceClass(str, Enum):
    methodology = "METHODOLOGY"
    trend_intelligence = "TREND_INTELLIGENCE"


class AuthorityClass(str, Enum):
    advisory = "ADVISORY"
    evidence_bound_advisory = "EVIDENCE_BOUND_ADVISORY"


class DirectiveClass(str, Enum):
    advisory_method = "ADVISORY_METHOD"
    evidence_bound_advisory = "EVIDENCE_BOUND_ADVISORY"
    quality_criterion = "QUALITY_CRITERION"
    anti_pattern = "ANTI_PATTERN"
    trend_suggestion = "TREND_SUGGESTION"


class GuidanceActivation(BaseModel):
    asset_families: list[str] = Field(default_factory=list)
    asset_types: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    brand_domains: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    task_tags: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ContextBudget(BaseModel):
    max_sections: int = Field(default=5, ge=1, le=50)
    max_chars: int = Field(default=12000, ge=256, le=100000)

    model_config = {"extra": "forbid"}


class GuidanceProvenance(BaseModel):
    source: str = Field(min_length=1)
    version: str = Field(min_length=1)
    author: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    license_or_ip_status: str | None = None

    model_config = {"extra": "forbid"}


class ActivationPredicate(BaseModel):
    any: list[str] = Field(default_factory=list)
    all: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class GuidanceSection(BaseModel):
    id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    directive_class: DirectiveClass = DirectiveClass.advisory_method
    activate_when: ActivationPredicate = Field(default_factory=ActivationPredicate)
    directives: list[str] = Field(default_factory=list)
    evaluation_criteria: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    output_targets: list[str] = Field(default_factory=list)
    patterns: dict[str, str] = Field(default_factory=dict)
    dimensions: list[str] = Field(default_factory=list)
    possible_outputs: list[str] = Field(default_factory=list)
    subsections: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _requires_actionable_content(self) -> "GuidanceSection":
        if not (
            self.directives
            or self.evaluation_criteria
            or self.anti_patterns
            or self.patterns
            or self.dimensions
            or self.subsections
        ):
            raise ValueError("guidance section must contain actionable content")
        return self


class TrendMetadata(BaseModel):
    observed_at: str
    expires_at: str
    source_refs: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    trend_status: str = Field(min_length=1)
    applicability: list[str] = Field(default_factory=list)
    avoid_when: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class GuidancePack(BaseModel):
    id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    pack_version: str = Field(min_length=1)
    domain: GuidanceDomain
    guidance_class: GuidanceClass = GuidanceClass.methodology
    authority_class: AuthorityClass
    description: str = Field(min_length=1)
    activation: GuidanceActivation
    excludes: GuidanceActivation = Field(default_factory=GuidanceActivation)
    dependencies: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    context_budget: ContextBudget = Field(default_factory=ContextBudget)
    sections: list[GuidanceSection] = Field(min_length=1)
    provenance: GuidanceProvenance
    trend: TrendMetadata | None = None
    content_hash: str = ""

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _section_ids_are_unique(self) -> "GuidancePack":
        ids = [section.id for section in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("guidance section ids must be unique within a pack")
        if self.guidance_class is GuidanceClass.trend_intelligence and self.trend is None:
            raise ValueError("TREND_INTELLIGENCE packs require trend freshness metadata")
        if self.guidance_class is GuidanceClass.methodology and self.trend is not None:
            raise ValueError("METHODOLOGY packs cannot declare trend freshness metadata")
        return self


class GuidanceOverride(BaseModel):
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class GuidanceSelection(BaseModel):
    registry_version: str
    router_version: str
    selected_pack_ids: list[str] = Field(default_factory=list)
    selected_section_ids: list[str] = Field(default_factory=list)
    activation_reasons: list[str] = Field(default_factory=list)
    rejected_pack_ids: list[str] = Field(default_factory=list)
    exclusion_reasons: list[str] = Field(default_factory=list)
    guidance_context: dict[str, Any] = Field(default_factory=dict)
    guidance_hash: str

    model_config = {"extra": "forbid"}
