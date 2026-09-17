from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CampaignBrief(BaseModel):
    brand_name: str
    industry: Optional[str] = None
    goals: List[str] = Field(default_factory=list)
    target_audience: str
    tone: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)


class BrandStrategy(BaseModel):
    positioning_statement: str
    brand_pillars: List[str]
    tone_of_voice: str
    target_audience_summary: str


class CreativeConcept(BaseModel):
    id: str
    name: str
    tagline: str
    rationale: str


class CopyVariant(BaseModel):
    concept_id: str
    headline: str
    body: str
    cta: str


class DesignBrief(BaseModel):
    palette: List[str]
    typography_direction: str
    imagery_style: str
    layout_notes: str


class QAReport(BaseModel):
    brand_safety_passed: bool
    flagged_terms: List[str] = Field(default_factory=list)
    quality_metrics: Dict[str, Any] = Field(default_factory=dict)
    brand_compliance: Dict[str, Any] = Field(default_factory=dict)
    notes: str
    release_blocked: bool = False
    degradation_reasons: List[str] = Field(default_factory=list)


class CampaignPackage(BaseModel):
    brief: CampaignBrief
    strategy: BrandStrategy
    concepts: List[CreativeConcept]
    copy_variants: List[CopyVariant]
    design_brief: DesignBrief
    qa_report: Optional[QAReport] = None
