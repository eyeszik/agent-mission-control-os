from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CampaignBrief(BaseModel):
    brand_name: str
    industry: Optional[str] = None
    business_idea: Optional[str] = None
    offer_summary: Optional[str] = None
    product_type: Optional[str] = None
    goals: List[str] = Field(default_factory=list)
    target_audience: str
    tone: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    business_model: Optional[str] = None
    affiliate_model: Optional[bool] = None
    workflow_idea: Optional[str] = None
    differentiators: List[str] = Field(default_factory=list)
    brand_style_notes: List[str] = Field(default_factory=list)


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


class WorkspaceDocument(BaseModel):
    path: str
    title: str
    kind: str
    body: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BusinessWorkspace(BaseModel):
    overview: Dict[str, Any] = Field(default_factory=dict)
    internal_docs: List[WorkspaceDocument] = Field(default_factory=list)
    production_docs: List[WorkspaceDocument] = Field(default_factory=list)
    prompt_library: List[WorkspaceDocument] = Field(default_factory=list)


class BrandingWorkspace(BaseModel):
    raw_brand_data: Dict[str, Any] = Field(default_factory=dict)
    internal_assets: List[WorkspaceDocument] = Field(default_factory=list)
    external_assets: List[WorkspaceDocument] = Field(default_factory=list)
    visual_asset_prompts: List[WorkspaceDocument] = Field(default_factory=list)


class DesignSystemPackage(BaseModel):
    tokens_json: Dict[str, Any] = Field(default_factory=dict)
    tailwind_config: Dict[str, Any] = Field(default_factory=dict)
    global_tokens_css: str
    component_scaffolds: List[WorkspaceDocument] = Field(default_factory=list)
    asset_recipes: List[WorkspaceDocument] = Field(default_factory=list)
    validation_notes: List[str] = Field(default_factory=list)


class RenderedAsset(BaseModel):
    asset_id: str
    asset_type: str
    title: str
    prompt_path: str
    spec_path: str
    output_path: str
    format: str
    review_status: str
    approval_required: bool = True
    generation_mode: str
    lineage_refs: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class AssetReviewQueue(BaseModel):
    review_status: str
    approval_required: bool = True
    review_artifact_path: str
    checklist: List[str] = Field(default_factory=list)
    blocking_issues: List[str] = Field(default_factory=list)


class PublishingAdapter(BaseModel):
    adapter_id: str
    target: str
    status: str
    approval_required: bool = True
    exported_asset_types: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class AssetExecutionPackage(BaseModel):
    rendered_assets: List[RenderedAsset] = Field(default_factory=list)
    review_queue: AssetReviewQueue
    publishing_adapters: List[PublishingAdapter] = Field(default_factory=list)
    execution_notes: List[str] = Field(default_factory=list)


class WorkspaceExport(BaseModel):
    root_folder: str
    business_folder: str
    branding_folder: str
    design_system_folder: str
    rendered_assets_folder: str
    files_written: List[str] = Field(default_factory=list)


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
    business_workspace: Optional[BusinessWorkspace] = None
    branding_workspace: Optional[BrandingWorkspace] = None
    design_system: Optional[DesignSystemPackage] = None
    asset_execution: Optional[AssetExecutionPackage] = None
    workspace_export: Optional[WorkspaceExport] = None
