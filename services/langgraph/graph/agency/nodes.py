import json
import logging
import re
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from services.langgraph.agency.assets import (
    render_background_pattern_svg,
    render_hero_svg,
    render_logo_svg,
)
from services.langgraph.graph.agency.llm import GenerationOutcome, generate_structured
from services.langgraph.graph.agency.models import (
    AssetExecutionPackage,
    AssetReviewQueue,
    BrandStrategy,
    BrandingWorkspace,
    BusinessWorkspace,
    CampaignBrief,
    CampaignPackage,
    CopyVariant,
    CreativeConcept,
    DesignSystemPackage,
    DesignBrief,
    PublishingAdapter,
    QAReport,
    RenderedAsset,
    WorkspaceDocument,
)
from services.langgraph.graph.state import GraphState
from services.langgraph.persistence.approvals import create_approval_request
from services.langgraph.quality.brand_safety import check_brand_safety
from services.langgraph.quality.evaluator import evaluate_quality
from services.langgraph.security.pii import quarantine_payload
from services.langgraph.security.preprocess import sanitize_deep

logger = logging.getLogger(__name__)

AGENCY_PIPELINE_STAGES = [
    "brief_intake",
    "brand_strategy",
    "creative_concepting",
    "copywriting",
    "design_brief",
    "campaign_assembly",
    "brand_safety_qa",
    "hitl_gate",
    "delivery",
]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "idea"


def _workspace_doc(path: str, title: str, kind: str, body: str, **metadata) -> WorkspaceDocument:
    return WorkspaceDocument(path=path, title=title, kind=kind, body=body, metadata=metadata)


def _build_business_workspace(brief: CampaignBrief, strategy: BrandStrategy, concepts: list[CreativeConcept]) -> BusinessWorkspace:
    idea = brief.business_idea or brief.offer_summary or f"{brief.brand_name} business concept"
    overview = {
        "idea_name": brief.brand_name,
        "business_idea": idea,
        "product_type": brief.product_type or "digital_product",
        "business_model": brief.business_model or ("affiliate" if brief.affiliate_model else "direct"),
        "workflow_idea": brief.workflow_idea,
        "target_audience": brief.target_audience,
        "goals": brief.goals,
        "differentiators": brief.differentiators,
    }
    internal_docs = [
        _workspace_doc(
            "business/overview.md",
            "Business Overview",
            "document",
            "\n".join(
                [
                    f"# {brief.brand_name} — Business Overview",
                    "",
                    "## Concept",
                    idea,
                    "",
                    "## Offer",
                    brief.offer_summary or "Offer not explicitly provided; derive from strategy and concept package.",
                    "",
                    "## Audience",
                    brief.target_audience,
                    "",
                    "## Goals",
                    *(
                        [f"- {goal}" for goal in brief.goals]
                        if brief.goals
                        else [
                            "- Establish positioning",
                            "- Validate offer",
                            "- Prepare brand and product system",
                        ]
                    ),
                ]
            ),
        ),
        _workspace_doc(
            "business/operations/production-plan.md",
            "Production Plan",
            "document",
            "\n".join(
                [
                    "# Production Plan",
                    "",
                    "1. Finalize product scope and deliverables.",
                    "2. Generate branded product prompts, workflows, and internal SOPs.",
                    "3. Approve design system, asset prompts, and implementation scaffolds.",
                    "4. Build the product/app on the approved brand system.",
                    "5. Prepare launch, measurement, and iteration loops.",
                ]
            ),
        ),
    ]
    production_docs = [
        _workspace_doc(
            "business/production/product-requirements.md",
            "Product Requirements",
            "document",
            "\n".join(
                [
                    f"# {brief.brand_name} Product Requirements",
                    "",
                    f"- Product type: {brief.product_type or 'digital_product'}",
                    f"- Workflow idea: {brief.workflow_idea or 'To be refined'}",
                    f"- Core positioning: {strategy.positioning_statement}",
                    "",
                    "## Launch-ready deliverables",
                    "- branded landing copy",
                    "- user journey and feature outline",
                    "- internal operating docs",
                    "- marketing asset prompts",
                ]
            ),
        ),
    ]
    prompt_library = [
        _workspace_doc(
            "business/prompts/product-generation.prompt.md",
            "Product Generation Prompt",
            "prompt",
            "\n".join(
                [
                    f"Build a {brief.product_type or 'digital product'} for {brief.brand_name}.",
                    f"Audience: {brief.target_audience}.",
                    f"Positioning: {strategy.positioning_statement}.",
                    f"Differentiators: {', '.join(brief.differentiators) or 'clarity, speed, trust'}.",
                    "Return feature spec, user flow, launch copy, and internal operations checklist.",
                ]
            ),
        ),
        _workspace_doc(
            "business/prompts/marketing-automation.prompt.md",
            "Marketing Automation Prompt",
            "prompt",
            "\n".join(
                [
                    f"Generate internal and external marketing assets for {brief.brand_name}.",
                    f"Use tone: {strategy.tone_of_voice}.",
                    f"Channels: {', '.join(brief.channels) or 'web, email, social'}.",
                    "Output campaign plan, copy matrix, CTA variants, and approval checkpoints.",
                ]
            ),
        ),
    ]
    return BusinessWorkspace(
        overview=overview,
        internal_docs=internal_docs,
        production_docs=production_docs,
        prompt_library=prompt_library,
    )


def _build_branding_workspace(brief: CampaignBrief, strategy: BrandStrategy, design_brief: DesignBrief, concepts: list[CreativeConcept]) -> BrandingWorkspace:
    raw_brand_data = {
        "brand_name": brief.brand_name,
        "industry": brief.industry,
        "style_notes": brief.brand_style_notes,
        "tone": strategy.tone_of_voice,
        "brand_pillars": strategy.brand_pillars,
        "palette": design_brief.palette,
        "typography_direction": design_brief.typography_direction,
        "imagery_style": design_brief.imagery_style,
        "concept_angles": [item.model_dump() for item in concepts],
    }
    internal_assets = [
        _workspace_doc(
            "branding/raw/brand-foundation.md",
            "Brand Foundation",
            "document",
            "\n".join(
                [
                    f"# {brief.brand_name} Brand Foundation",
                    "",
                    f"Positioning: {strategy.positioning_statement}",
                    "",
                    "Pillars:",
                    *(f"- {pillar}" for pillar in strategy.brand_pillars),
                    "",
                    f"Typography: {design_brief.typography_direction}",
                    f"Imagery: {design_brief.imagery_style}",
                ]
            ),
        ),
        _workspace_doc(
            "branding/raw/messaging-house.md",
            "Messaging House",
            "document",
            "\n".join(
                [
                    "# Messaging House",
                    "",
                    "Core claim:",
                    strategy.positioning_statement,
                    "",
                    "Proof themes:",
                    *[f"- {concept.rationale}" for concept in concepts],
                ]
            ),
        ),
    ]
    external_assets = [
        _workspace_doc(
            "branding/external/style-guide.md",
            "Brand Style Guide",
            "document",
            "\n".join(
                [
                    f"# {brief.brand_name} Style Guide",
                    "",
                    f"Tone: {strategy.tone_of_voice}",
                    f"Palette: {', '.join(design_brief.palette)}",
                    f"Layout notes: {design_brief.layout_notes}",
                ]
            ),
        ),
    ]
    visual_asset_prompts = [
        _workspace_doc(
            "branding/prompts/logo-mark.prompt.md",
            "Logo Mark Prompt",
            "prompt",
            f"Create a flat vector geometric silhouette logo for {brief.brand_name}. Palette anchor {design_brief.palette[0]}. Avoid rendered text, noise, gradients, or malformed glyphs.",
            asset_type="logo_mark",
        ),
        _workspace_doc(
            "branding/prompts/background-pattern.prompt.md",
            "Background Pattern Prompt",
            "prompt",
            f"Create a repeating abstract line-art pattern for {brief.brand_name} using {', '.join(design_brief.palette[:3])}. Keep it modular and crop-safe across mobile through ultrawide layouts.",
            asset_type="background_pattern",
        ),
        _workspace_doc(
            "branding/prompts/hero-illustration.prompt.md",
            "Hero Illustration Prompt",
            "prompt",
            f"Create an editorial bento-grid style hero illustration for {brief.brand_name}, matching the brand tone {strategy.tone_of_voice} and typography direction {design_brief.typography_direction}.",
            asset_type="hero_illustration",
        ),
    ]
    return BrandingWorkspace(
        raw_brand_data=raw_brand_data,
        internal_assets=internal_assets,
        external_assets=external_assets,
        visual_asset_prompts=visual_asset_prompts,
    )


def _build_design_system(brief: CampaignBrief, strategy: BrandStrategy, design_brief: DesignBrief) -> DesignSystemPackage:
    slug = _slugify(brief.brand_name)
    palette = design_brief.palette or ["#1F2937", "#F59E0B", "#F9FAFB"]
    tokens = {
        "$schema": "https://design-tokens.github.io/community-group/format/",
        "brand": {
            "raw": {
                "primary": {"value": palette[0]},
                "secondary": {"value": palette[1] if len(palette) > 1 else palette[0]},
                "surface": {"value": palette[-1]},
            },
            "semantic": {
                "color": {
                    "bg": {"value": "{brand.raw.surface.value}"},
                    "fg": {"value": "{brand.raw.primary.value}"},
                    "accent": {"value": "{brand.raw.secondary.value}"},
                },
                "typography": {
                    "headlineFamily": {"value": design_brief.typography_direction},
                    "bodyTone": {"value": strategy.tone_of_voice},
                },
            },
        },
    }
    tailwind = {
        "theme": {
            "extend": {
                "colors": {
                    "brand-primary": "var(--brand-primary)",
                    "brand-secondary": "var(--brand-secondary)",
                    "brand-surface": "var(--brand-surface)",
                }
            }
        }
    }
    css = "\n".join(
        [
            ":root {",
            f"  --brand-primary: {palette[0]};",
            f"  --brand-secondary: {palette[1] if len(palette) > 1 else palette[0]};",
            f"  --brand-surface: {palette[-1]};",
            "}",
        ]
    )
    components = [
        _workspace_doc(
            "branding/design-system/components/Button.tsx",
            "Button Component",
            "code",
            "\n".join(
                [
                    "export function Button({ children }: { children: React.ReactNode }) {",
                    "  return <button className=\"rounded-md bg-[var(--brand-primary)] px-4 py-2 text-white\">{children}</button>;",
                    "}",
                ]
            ),
            component="Button",
        ),
        _workspace_doc(
            "branding/design-system/components/Card.tsx",
            "Card Component",
            "code",
            "\n".join(
                [
                    "export function Card({ children }: { children: React.ReactNode }) {",
                    "  return <div className=\"rounded-xl border border-zinc-200 bg-[var(--brand-surface)] p-4 shadow-sm\">{children}</div>;",
                    "}",
                ]
            ),
            component="Card",
        ),
    ]
    asset_recipes = [
        _workspace_doc(
            "branding/design-system/assets/logo-spec.md",
            "Logo Spec",
            "document",
            f"Use {palette[0]} as the primary mark color for {brief.brand_name}. Preserve geometric silhouette discipline and avoid embedded text.",
            asset="logo_mark",
        ),
        _workspace_doc(
            "branding/design-system/assets/asset-runbook.md",
            "Asset Runbook",
            "document",
            "\n".join(
                [
                    "# Asset Runbook",
                    "",
                    f"1. Read `branding/raw/brand-foundation.md` for {brief.brand_name}.",
                    "2. Load `branding/design-system/tokens.json` and `global-tokens.css`.",
                    "3. Generate logo mark, background pattern, and hero illustration from the prompt files.",
                    "4. Review outputs for contrast, glyph integrity, and crop safety.",
                ]
            ),
        ),
    ]
    return DesignSystemPackage(
        tokens_json=tokens,
        tailwind_config=tailwind,
        global_tokens_css=css,
        component_scaffolds=components,
        asset_recipes=asset_recipes,
        validation_notes=[
            "Contrast and token normalization must be validated before live UI use.",
            "Dynamic class names should map to CSS variables or safelisted tokens only.",
            f"Namespace raw tokens under brand.raw.{slug} if merged into a larger system.",
        ],
    )


def _build_asset_execution(
    brief: CampaignBrief,
    strategy: BrandStrategy,
    package: CampaignPackage,
) -> AssetExecutionPackage:
    prompt_docs = {doc.path: doc for doc in (package.branding_workspace.visual_asset_prompts if package.branding_workspace else [])}
    recipe_docs = {doc.path: doc for doc in (package.design_system.asset_recipes if package.design_system else [])}
    tokens = (package.design_system.tokens_json if package.design_system else {}) or {}
    raw = (((tokens.get("brand") or {}).get("raw")) or {})
    primary = ((raw.get("primary") or {}).get("value")) or "#1F2937"
    secondary = ((raw.get("secondary") or {}).get("value")) or "#F59E0B"
    surface = ((raw.get("surface") or {}).get("value")) or "#F9FAFB"
    slug = _slugify(brief.brand_name)
    rendered_assets = [
        RenderedAsset(
            asset_id=f"{slug}-logo-mark",
            asset_type="logo_mark",
            title="Canonical Logo Mark",
            prompt_path="branding/prompts/logo-mark.prompt.md",
            spec_path="branding/design-system/assets/logo-spec.md",
            output_path="branding/rendered/logo-mark.svg",
            format="image/svg+xml",
            review_status="pending_review",
            generation_mode="deterministic_svg_v1",
            lineage_refs=[
                "campaign_package.design_system.tokens_json",
                "campaign_package.branding_workspace.raw_brand_data",
            ],
            notes=[
                "Rendered from canonical brand tokens on the Zo server.",
                "Review silhouette clarity and glyph exclusion before publish.",
            ],
        ),
        RenderedAsset(
            asset_id=f"{slug}-background-pattern",
            asset_type="background_pattern",
            title="Canonical Background Pattern",
            prompt_path="branding/prompts/background-pattern.prompt.md",
            spec_path="branding/design-system/assets/asset-runbook.md",
            output_path="branding/rendered/background-pattern.svg",
            format="image/svg+xml",
            review_status="pending_review",
            generation_mode="deterministic_svg_v1",
            lineage_refs=[
                "campaign_package.design_system.tokens_json",
                "campaign_package.design_system.asset_recipes",
            ],
            notes=[
                "Crop-safe modular pattern for responsive surfaces.",
            ],
        ),
        RenderedAsset(
            asset_id=f"{slug}-hero-illustration",
            asset_type="hero_illustration",
            title="Canonical Hero Illustration",
            prompt_path="branding/prompts/hero-illustration.prompt.md",
            spec_path="branding/design-system/assets/asset-runbook.md",
            output_path="branding/rendered/hero-illustration.svg",
            format="image/svg+xml",
            review_status="pending_review",
            generation_mode="deterministic_svg_v1",
            lineage_refs=[
                "campaign_package.copy_variants",
                "campaign_package.design_system.tokens_json",
                "campaign_package.brand_strategy",
            ],
            notes=[
                "Use as the base render for landing pages and internal app hero surfaces.",
            ],
        ),
    ]
    review_queue = AssetReviewQueue(
        review_status="pending_review",
        review_artifact_path="branding/review/asset-approval-inbox.md",
        checklist=[
            "Confirm asset matches brand pillars and tone.",
            "Confirm token-derived colors remain accessible on target surfaces.",
            "Confirm no malformed text or glyph artifacts are present.",
            "Confirm hero and pattern crops are safe across target aspect ratios.",
        ],
        blocking_issues=[],
    )
    adapters = [
        PublishingAdapter(
            adapter_id="brand-profile-export",
            target="brand_profile_bundle",
            status="draft_only",
            exported_asset_types=["logo_mark", "background_pattern", "hero_illustration"],
            notes=[
                "Adapter manifest only. External profile upload remains approval-gated and unexecuted.",
            ],
        ),
        PublishingAdapter(
            adapter_id="social-launch-kit",
            target="social_launch_bundle",
            status="draft_only",
            exported_asset_types=["logo_mark", "hero_illustration"],
            notes=[
                "Prepares export metadata for downstream publishing tools without mutating external systems.",
            ],
        ),
    ]
    execution_notes = [
        "Asset execution runs from the compiled design-system package, not ad hoc prompts.",
        "Rendered outputs remain internal artifacts until explicit human approval authorizes downstream publishing.",
        "Any design token change should trigger asset regeneration through the same canonical path.",
    ]
    return AssetExecutionPackage(
        rendered_assets=rendered_assets,
        review_queue=review_queue,
        publishing_adapters=adapters,
        execution_notes=execution_notes,
    )


def _agency_data(state: GraphState) -> tuple[dict, dict]:
    data = dict(state.get("extracted_data") or {})
    agency = dict(data.get("agency") or {})
    return data, agency


def _record_generation(agency: dict, task: str, outcome: GenerationOutcome) -> dict:
    provenance = list(agency.get("generation_provenance") or [])
    provenance.append(outcome.provenance(task))
    agency["generation_provenance"] = provenance
    if outcome.degraded:
        agency["degraded"] = True
    return outcome.data


def _log_node(state: GraphState, node_id: str) -> None:
    logger.info(
        "agency_node",
        extra={
            "run_id": str(state["run"].id),
            "tenant_id": state["run"].tenant_id,
            "project_id": state["run"].project_id,
            "node_id": node_id,
        },
    )


def brief_intake_node(state: GraphState) -> dict:
    _log_node(state, "brief_intake")
    raw_input = state["run"].metadata.get("input_data", {}) if state["run"].metadata else {}
    raw_brief = quarantine_payload(sanitize_deep(raw_input)).get("brief", {})
    brief = CampaignBrief(
        brand_name=raw_brief.get("brand_name", "Unnamed Brand"),
        industry=raw_brief.get("industry"),
        business_idea=raw_brief.get("business_idea"),
        offer_summary=raw_brief.get("offer_summary"),
        product_type=raw_brief.get("product_type"),
        goals=raw_brief.get("goals", []),
        target_audience=raw_brief.get("target_audience", "General audience"),
        tone=raw_brief.get("tone"),
        channels=raw_brief.get("channels", []),
        constraints=raw_brief.get("constraints", []),
        business_model=raw_brief.get("business_model"),
        affiliate_model=raw_brief.get("affiliate_model"),
        workflow_idea=raw_brief.get("workflow_idea"),
        differentiators=raw_brief.get("differentiators", []),
        brand_style_notes=raw_brief.get("brand_style_notes", []),
    )
    data, agency = _agency_data(state)
    agency["brief"] = brief.model_dump()
    data["agency"] = agency
    return {
        "current_node": "brief_intake",
        "extracted_data": data,
        "messages": [
            SystemMessage(content="You are the orchestrator for an autonomous branding and marketing agency pipeline."),
            HumanMessage(content=f"New campaign brief intake for '{brief.brand_name}'."),
        ],
    }


def brand_strategy_node(state: GraphState) -> dict:
    _log_node(state, "brand_strategy")
    data, agency = _agency_data(state)
    brief = agency.get("brief", {})
    prompt = (
        "You are a senior brand strategist. Given this campaign brief, return a JSON object with keys "
        "'positioning_statement' (string), 'brand_pillars' (array of 3-5 short strings), "
        "'tone_of_voice' (string), and 'target_audience_summary' (string).\n"
        f"Brief: {json.dumps(brief)}"
    )
    fallback = {
        "positioning_statement": f"{brief.get('brand_name', 'The brand')} is the trusted choice for {brief.get('target_audience', 'its audience')}.",
        "brand_pillars": ["Clarity", "Trust", "Craft"],
        "tone_of_voice": brief.get("tone") or "confident and approachable",
        "target_audience_summary": brief.get("target_audience", "General audience"),
    }
    outcome = generate_structured(prompt, fallback, schema_version="brand-strategy-v1")
    result = _record_generation(agency, "brand_strategy", outcome)
    strategy = BrandStrategy(**{**fallback, **{k: v for k, v in result.items() if k in fallback}})
    agency["brand_strategy"] = strategy.model_dump()
    data["agency"] = agency
    quality = evaluate_quality(strategy.positioning_statement)
    return {
        "current_node": "brand_strategy",
        "extracted_data": data,
        "messages": [AIMessage(content=f"Brand strategy defined: {strategy.positioning_statement}")],
        "validation_status": "degraded" if outcome.degraded else ("passed" if quality["threshold_passed"] else "failed"),
    }


def creative_concepting_node(state: GraphState) -> dict:
    _log_node(state, "creative_concepting")
    data, agency = _agency_data(state)
    brief = agency.get("brief", {})
    strategy = agency.get("brand_strategy", {})
    prompt = (
        "You are a creative director. Given this brand strategy and brief, return a JSON object with key "
        "'concepts': an array of exactly 3 objects, each with 'id', 'name', 'tagline', and 'rationale'.\n"
        f"Brand strategy: {json.dumps(strategy)}\nBrief: {json.dumps(brief)}"
    )
    pillar = (strategy.get("brand_pillars") or ["Clarity"])[0]
    fallback = {
        "concepts": [
            {"id": "concept-1", "name": f"{pillar} First", "tagline": strategy.get("positioning_statement", "")[:60] or "Built on what matters.", "rationale": f"Leads with {pillar.lower()} to build trust with {brief.get('target_audience', 'the audience')}."},
            {"id": "concept-2", "name": "Everyday Momentum", "tagline": f"{brief.get('brand_name', 'We')} moves with you.", "rationale": "Frames the brand as a daily companion rather than a one-off purchase."},
            {"id": "concept-3", "name": "Proof Over Promises", "tagline": "Results you can see.", "rationale": "Counters category skepticism with evidence-led messaging."},
        ]
    }
    outcome = generate_structured(prompt, fallback, schema_version="creative-concepts-v1")
    result = _record_generation(agency, "creative_concepting", outcome)
    concepts = [CreativeConcept(**item) for item in (result.get("concepts") or fallback["concepts"])]
    agency["creative_concepts"] = [item.model_dump() for item in concepts]
    data["agency"] = agency
    return {
        "current_node": "creative_concepting",
        "extracted_data": data,
        "messages": [AIMessage(content=f"Generated {len(concepts)} creative concepts.")],
        "validation_status": "degraded" if outcome.degraded else state.get("validation_status", "pending"),
    }


def copywriting_node(state: GraphState) -> dict:
    _log_node(state, "copywriting")
    data, agency = _agency_data(state)
    concepts = agency.get("creative_concepts", [])
    strategy = agency.get("brand_strategy", {})
    prompt = (
        "You are a senior copywriter. For each concept below, write ad copy. Return a JSON object: "
        "{'copy': [{'concept_id','headline','body','cta'}, ...]} with one entry per concept.\n"
        f"Tone of voice: {strategy.get('tone_of_voice', 'confident')}\nConcepts: {json.dumps(concepts)}"
    )
    fallback_variants = [
        {"concept_id": item.get("id", "concept-1"), "headline": item.get("tagline", "Discover more."), "body": item.get("rationale", "A campaign built on brand strategy."), "cta": "Learn more"}
        for item in concepts
    ]
    fallback = {"copy": fallback_variants}
    outcome = generate_structured(prompt, fallback, schema_version="campaign-copy-v1")
    result = _record_generation(agency, "copywriting", outcome)
    variants = [CopyVariant(**item) for item in (result.get("copy") or fallback_variants)]
    agency["copy_variants"] = [item.model_dump() for item in variants]
    data["agency"] = agency
    return {
        "current_node": "copywriting",
        "extracted_data": data,
        "messages": [AIMessage(content=f"Drafted {len(variants)} copy variants.")],
        "validation_status": "degraded" if outcome.degraded else state.get("validation_status", "pending"),
    }


def design_brief_node(state: GraphState) -> dict:
    _log_node(state, "design_brief")
    data, agency = _agency_data(state)
    strategy = agency.get("brand_strategy", {})
    brief = agency.get("brief", {})
    prompt = (
        "You are an art director. Produce a JSON design brief with keys 'palette' (array of 3-5 hex colors), "
        "'typography_direction' (string), 'imagery_style' (string), 'layout_notes' (string), consistent with this brand strategy.\n"
        f"Strategy: {json.dumps(strategy)}\nChannels: {brief.get('channels', [])}"
    )
    fallback = {
        "palette": ["#1F2937", "#F59E0B", "#F9FAFB"],
        "typography_direction": "A confident geometric sans for headlines paired with a readable serif for body copy.",
        "imagery_style": "Authentic, lightly art-directed photography over stock imagery.",
        "layout_notes": "Generous whitespace, a single dominant focal image per placement, consistent grid across channels.",
    }
    outcome = generate_structured(prompt, fallback, schema_version="design-brief-v1")
    result = _record_generation(agency, "design_brief", outcome)
    design_brief = DesignBrief(**{**fallback, **{k: v for k, v in result.items() if k in fallback}})
    agency["design_brief"] = design_brief.model_dump()
    data["agency"] = agency
    return {
        "current_node": "design_brief",
        "extracted_data": data,
        "messages": [AIMessage(content="Design brief drafted for creative production handoff.")],
        "validation_status": "degraded" if outcome.degraded else state.get("validation_status", "pending"),
    }


def campaign_assembly_node(state: GraphState) -> dict:
    _log_node(state, "campaign_assembly")
    data, agency = _agency_data(state)
    brief = CampaignBrief(**agency.get("brief", {}))
    strategy = BrandStrategy(**agency.get("brand_strategy", {}))
    concepts = [CreativeConcept(**item) for item in agency.get("creative_concepts", [])]
    design_brief = DesignBrief(**agency.get("design_brief", {}))
    business_workspace = _build_business_workspace(brief, strategy, concepts)
    branding_workspace = _build_branding_workspace(brief, strategy, design_brief, concepts)
    design_system = _build_design_system(brief, strategy, design_brief)
    package = CampaignPackage(
        brief=brief,
        strategy=strategy,
        concepts=concepts,
        copy_variants=[CopyVariant(**item) for item in agency.get("copy_variants", [])],
        design_brief=design_brief,
        business_workspace=business_workspace,
        branding_workspace=branding_workspace,
        design_system=design_system,
    )
    package.asset_execution = _build_asset_execution(brief, strategy, package)
    agency["campaign_package"] = package.model_dump()
    data["agency"] = agency
    return {"current_node": "campaign_assembly", "extracted_data": data, "messages": [AIMessage(content="Campaign package assembled from all agency workstreams.")]}


def brand_safety_qa_node(state: GraphState) -> dict:
    _log_node(state, "brand_safety_qa")
    data, agency = _agency_data(state)
    package = agency.get("campaign_package", {})
    combined_text = " ".join(
        f"{item.get('headline', '')} {item.get('body', '')} {item.get('cta', '')}"
        for item in package.get("copy_variants", [])
    ).strip()
    flagged = check_brand_safety(combined_text)
    quality = evaluate_quality(combined_text or package.get("strategy", {}).get("positioning_statement", ""))
    degraded_tasks = [item.get("task", "unknown") for item in agency.get("generation_provenance", []) if item.get("mode") != "PROVIDER_SUCCESS"]
    release_blocked = bool(degraded_tasks)
    qa_passed = (not flagged) and quality["threshold_passed"] and not release_blocked
    notes = ["No banned-claim heuristic matches detected." if not flagged else f"Flagged terms requiring review: {', '.join(flagged)}"]
    if release_blocked:
        notes.append("Release blocked because one or more generation stages used degraded fallback output; rerun with a configured provider before delivery.")
    qa_report = QAReport(
        brand_safety_passed=not flagged,
        flagged_terms=flagged,
        quality_metrics=quality,
        notes=" ".join(notes),
        release_blocked=release_blocked,
        degradation_reasons=degraded_tasks,
    )
    agency["qa_report"] = qa_report.model_dump()
    if isinstance(agency.get("campaign_package"), dict):
        agency["campaign_package"] = {**agency["campaign_package"], "qa_report": qa_report.model_dump()}
    data["agency"] = agency
    return {
        "current_node": "brand_safety_qa",
        "extracted_data": data,
        "messages": [AIMessage(content=f"Brand-safety QA {'passed' if qa_passed else 'requires review'}.")],
        "validation_status": "passed" if qa_passed else ("degraded" if release_blocked else "failed"),
    }


def hitl_gate_node(state: GraphState) -> dict:
    _log_node(state, "hitl_gate")
    data, agency = _agency_data(state)
    qa_report = agency.get("qa_report", {})
    run = state["run"]
    if qa_report.get("release_blocked"):
        reason = "Campaign requires human review, but delivery remains blocked until degraded provider output is regenerated successfully."
    elif qa_report.get("brand_safety_passed", False):
        reason = "Campaign package ready for human review before external publish."
    else:
        reason = f"Brand-safety QA flagged terms: {', '.join(qa_report.get('flagged_terms', []))}. Human review required before publish."
    approval = create_approval_request(
        run_id=str(run.id),
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        reason=reason,
        confidence=None,
    )
    agency["pending_approval_id"] = approval["approval_id"]
    data["agency"] = agency
    return {"current_node": "hitl_gate", "extracted_data": data, "messages": [AIMessage(content="Routed campaign package to human-in-the-loop approval before delivery.")]}


def delivery_node(state: GraphState) -> dict:
    _log_node(state, "delivery")
    data, agency = _agency_data(state)
    if (agency.get("qa_report") or {}).get("release_blocked"):
        raise RuntimeError("Delivery blocked because generation is degraded")
    package = agency.get("campaign_package", {})
    delivery_bundle = {
        "campaign_package": package,
        "delivered_at": datetime.now(timezone.utc).isoformat(),
        "approval_id": agency.get("pending_approval_id"),
        "format": "json_bundle_v1",
    }
    agency["delivery"] = delivery_bundle
    data["agency"] = agency
    return {"current_node": "delivery", "extracted_data": data, "messages": [AIMessage(content="Campaign package approved and delivered.")], "validation_status": "passed"}
