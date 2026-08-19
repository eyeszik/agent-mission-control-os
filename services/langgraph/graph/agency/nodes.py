import json
from datetime import datetime

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage

from services.langgraph.graph.state import GraphState
from services.langgraph.security.pii import quarantine_payload
from services.langgraph.security.sanitize import sanitize_input
from services.langgraph.quality.evaluator import evaluate_quality
from services.langgraph.quality.brand_safety import check_brand_safety
from services.langgraph.persistence.approvals import create_approval_request
from services.langgraph.graph.agency.llm import generate_structured
from services.langgraph.graph.agency.models import (
    CampaignBrief,
    BrandStrategy,
    CreativeConcept,
    CopyVariant,
    DesignBrief,
    CampaignPackage,
    QAReport,
)

# Ordered stage names for this pipeline, exposed for API responses and UI wiring.
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


def _agency_data(state: GraphState) -> tuple[dict, dict]:
    """Returns (full extracted_data dict, agency sub-dict), both copies safe to mutate."""
    data = dict(state.get("extracted_data") or {})
    agency = dict(data.get("agency") or {})
    return data, agency


def brief_intake_node(state: GraphState) -> dict:
    """
    Node: Brief Intake
    Responsibilities: normalize the incoming campaign brief, mask PII, sanitize
    against prompt injection, and produce a structured CampaignBrief.
    """
    print(f"Running Brief Intake for run {state['run'].id}")

    raw_input = state["run"].metadata.get("input_data", {}) if state["run"].metadata else {}
    sanitized = sanitize_input(raw_input)
    quarantined = quarantine_payload(sanitized)
    raw_brief = quarantined.get("brief", quarantined)

    brief = CampaignBrief(
        brand_name=raw_brief.get("brand_name", "Unnamed Brand"),
        industry=raw_brief.get("industry"),
        goals=raw_brief.get("goals", []),
        target_audience=raw_brief.get("target_audience", "General audience"),
        tone=raw_brief.get("tone"),
        channels=raw_brief.get("channels", []),
        constraints=raw_brief.get("constraints", []),
    )

    data, agency = _agency_data(state)
    agency["brief"] = brief.model_dump()
    data["agency"] = agency

    system_msg = SystemMessage(content="You are the orchestrator for an autonomous branding and marketing agency pipeline.")
    human_msg = HumanMessage(content=f"New campaign brief intake for '{brief.brand_name}'.")

    return {"current_node": "brief_intake", "extracted_data": data, "messages": [system_msg, human_msg]}


def brand_strategy_node(state: GraphState) -> dict:
    """
    Node: Brand Strategy
    Responsibilities: derive positioning, brand pillars, and tone of voice from the brief.
    """
    print(f"Running Brand Strategy for run {state['run'].id}")

    data, agency = _agency_data(state)
    brief = agency.get("brief", {})

    prompt = (
        "You are a senior brand strategist. Given this campaign brief, return a JSON object with keys "
        "'positioning_statement' (string), 'brand_pillars' (array of 3-5 short strings), "
        "'tone_of_voice' (string), and 'target_audience_summary' (string).\n"
        f"Brief: {json.dumps(brief)}"
    )
    fallback = {
        "positioning_statement": (
            f"{brief.get('brand_name', 'The brand')} is the trusted choice for "
            f"{brief.get('target_audience', 'its audience')}."
        ),
        "brand_pillars": ["Clarity", "Trust", "Craft"],
        "tone_of_voice": brief.get("tone") or "confident and approachable",
        "target_audience_summary": brief.get("target_audience", "General audience"),
    }
    result = generate_structured(prompt, fallback)
    merged = {**fallback, **{k: v for k, v in result.items() if k in fallback}}
    strategy = BrandStrategy(**merged)

    agency["brand_strategy"] = strategy.model_dump()
    data["agency"] = agency

    quality = evaluate_quality(strategy.positioning_statement)
    ai_msg = AIMessage(content=f"Brand strategy defined: {strategy.positioning_statement}")

    return {
        "current_node": "brand_strategy",
        "extracted_data": data,
        "messages": [ai_msg],
        "validation_status": "passed" if quality["threshold_passed"] else "failed",
    }


def creative_concepting_node(state: GraphState) -> dict:
    """
    Node: Creative Concepting
    Responsibilities: propose distinct creative directions grounded in the brand strategy.
    """
    print(f"Running Creative Concepting for run {state['run'].id}")

    data, agency = _agency_data(state)
    brief = agency.get("brief", {})
    strategy = agency.get("brand_strategy", {})

    prompt = (
        "You are a creative director. Given this brand strategy and brief, return a JSON object with key "
        "'concepts': an array of exactly 3 objects, each with 'id' (e.g. 'concept-1'), 'name', 'tagline', "
        "and 'rationale'.\n"
        f"Brand strategy: {json.dumps(strategy)}\nBrief: {json.dumps(brief)}"
    )
    pillar = (strategy.get("brand_pillars") or ["Clarity"])[0]
    fallback = {
        "concepts": [
            {
                "id": "concept-1",
                "name": f"{pillar} First",
                "tagline": strategy.get("positioning_statement", "")[:60] or "Built on what matters.",
                "rationale": f"Leads with {pillar.lower()} to build trust with {brief.get('target_audience', 'the audience')}.",
            },
            {
                "id": "concept-2",
                "name": "Everyday Momentum",
                "tagline": f"{brief.get('brand_name', 'We')} moves with you.",
                "rationale": "Frames the brand as a daily companion rather than a one-off purchase.",
            },
            {
                "id": "concept-3",
                "name": "Proof Over Promises",
                "tagline": "Results you can see.",
                "rationale": "Counters category skepticism with evidence-led messaging.",
            },
        ]
    }
    result = generate_structured(prompt, fallback)
    concepts_raw = result.get("concepts") if isinstance(result, dict) else None
    concepts = [CreativeConcept(**c) for c in (concepts_raw or fallback["concepts"])]

    agency["creative_concepts"] = [c.model_dump() for c in concepts]
    data["agency"] = agency

    ai_msg = AIMessage(content=f"Generated {len(concepts)} creative concepts.")
    return {"current_node": "creative_concepting", "extracted_data": data, "messages": [ai_msg]}


def copywriting_node(state: GraphState) -> dict:
    """
    Node: Copywriting
    Responsibilities: draft headline/body/CTA copy per creative concept.
    """
    print(f"Running Copywriting for run {state['run'].id}")

    data, agency = _agency_data(state)
    concepts = agency.get("creative_concepts", [])
    strategy = agency.get("brand_strategy", {})

    prompt = (
        "You are a senior copywriter. For each concept below, write ad copy. Return a JSON object: "
        "{'copy': [{'concept_id','headline','body','cta'}, ...]} with one entry per concept.\n"
        f"Tone of voice: {strategy.get('tone_of_voice', 'confident')}\nConcepts: {json.dumps(concepts)}"
    )
    fallback_variants = [
        {
            "concept_id": c.get("id", "concept-1"),
            "headline": c.get("tagline", "Discover more."),
            "body": c.get("rationale", "A campaign built on brand strategy."),
            "cta": "Learn more",
        }
        for c in concepts
    ]
    fallback = {"copy": fallback_variants}
    result = generate_structured(prompt, fallback)
    copy_raw = result.get("copy") if isinstance(result, dict) else None
    variants = [CopyVariant(**v) for v in (copy_raw or fallback_variants)]

    agency["copy_variants"] = [v.model_dump() for v in variants]
    data["agency"] = agency

    ai_msg = AIMessage(content=f"Drafted {len(variants)} copy variants.")
    return {"current_node": "copywriting", "extracted_data": data, "messages": [ai_msg]}


def design_brief_node(state: GraphState) -> dict:
    """
    Node: Design Brief
    Responsibilities: translate brand strategy into a visual direction brief for
    downstream creative production (no image generation is performed here).
    """
    print(f"Running Design Brief for run {state['run'].id}")

    data, agency = _agency_data(state)
    strategy = agency.get("brand_strategy", {})
    brief = agency.get("brief", {})

    prompt = (
        "You are an art director. Produce a JSON design brief with keys 'palette' (array of 3-5 hex colors), "
        "'typography_direction' (string), 'imagery_style' (string), 'layout_notes' (string), consistent with "
        "this brand strategy.\n"
        f"Strategy: {json.dumps(strategy)}\nChannels: {brief.get('channels', [])}"
    )
    fallback = {
        "palette": ["#1F2937", "#F59E0B", "#F9FAFB"],
        "typography_direction": "A confident geometric sans for headlines paired with a readable serif for body copy.",
        "imagery_style": "Authentic, lightly art-directed photography over stock imagery.",
        "layout_notes": "Generous whitespace, a single dominant focal image per placement, consistent grid across channels.",
    }
    result = generate_structured(prompt, fallback)
    merged = {**fallback, **{k: v for k, v in result.items() if k in fallback}}
    design_brief = DesignBrief(**merged)

    agency["design_brief"] = design_brief.model_dump()
    data["agency"] = agency

    ai_msg = AIMessage(content="Design brief drafted for creative production handoff.")
    return {"current_node": "design_brief", "extracted_data": data, "messages": [ai_msg]}


def campaign_assembly_node(state: GraphState) -> dict:
    """
    Node: Campaign Assembly
    Responsibilities: assemble brief + strategy + concepts + copy + design brief
    into a single CampaignPackage artifact.
    """
    print(f"Running Campaign Assembly for run {state['run'].id}")

    data, agency = _agency_data(state)
    package = CampaignPackage(
        brief=CampaignBrief(**agency.get("brief", {})),
        strategy=BrandStrategy(**agency.get("brand_strategy", {})),
        concepts=[CreativeConcept(**c) for c in agency.get("creative_concepts", [])],
        copy_variants=[CopyVariant(**v) for v in agency.get("copy_variants", [])],
        design_brief=DesignBrief(**agency.get("design_brief", {})),
    )

    agency["campaign_package"] = package.model_dump()
    data["agency"] = agency

    ai_msg = AIMessage(content="Campaign package assembled from all agency workstreams.")
    return {"current_node": "campaign_assembly", "extracted_data": data, "messages": [ai_msg]}


def brand_safety_qa_node(state: GraphState) -> dict:
    """
    Node: Brand Safety QA
    Responsibilities: check assembled copy against brand-safety heuristics and
    quality thresholds before routing to human review.
    """
    print(f"Running Brand Safety QA for run {state['run'].id}")

    data, agency = _agency_data(state)
    package = agency.get("campaign_package", {})
    copy_variants = package.get("copy_variants", [])
    combined_text = " ".join(
        f"{v.get('headline', '')} {v.get('body', '')} {v.get('cta', '')}" for v in copy_variants
    ).strip()

    flagged = check_brand_safety(combined_text)
    quality = evaluate_quality(combined_text or package.get("strategy", {}).get("positioning_statement", ""))
    qa_passed = (not flagged) and quality["threshold_passed"]

    qa_report = QAReport(
        brand_safety_passed=not flagged,
        flagged_terms=flagged,
        quality_metrics=quality,
        notes=(
            "No banned claims detected."
            if not flagged
            else f"Flagged terms requiring review: {', '.join(flagged)}"
        ),
    )

    agency["qa_report"] = qa_report.model_dump()
    if isinstance(agency.get("campaign_package"), dict):
        agency["campaign_package"] = {**agency["campaign_package"], "qa_report": qa_report.model_dump()}
    data["agency"] = agency

    ai_msg = AIMessage(content=f"Brand-safety QA {'passed' if qa_passed else 'flagged issues'}.")
    return {
        "current_node": "brand_safety_qa",
        "extracted_data": data,
        "messages": [ai_msg],
        "validation_status": "passed" if qa_passed else "failed",
    }


def hitl_gate_node(state: GraphState) -> dict:
    """
    Node: HITL Gate
    Responsibilities: always route the assembled campaign package to a human
    reviewer before delivery/publish (canonical_publish action requires human
    review regardless of automated QA outcome, per governance policy). The graph
    is compiled with interrupt_before=["delivery"], so returning here pauses
    execution until an approval decision resumes it via the /agency resume route.
    """
    print(f"Running HITL Gate for run {state['run'].id}")

    data, agency = _agency_data(state)
    qa_report = agency.get("qa_report", {})
    run = state["run"]
    confidence = (qa_report.get("quality_metrics") or {}).get("faithfulness", 0.0)

    reason = (
        "Campaign package ready for human review before external publish."
        if qa_report.get("brand_safety_passed", False)
        else (
            "Brand-safety QA flagged terms: "
            f"{', '.join(qa_report.get('flagged_terms', []))}. Human review required before publish."
        )
    )

    approval = create_approval_request(
        run_id=str(run.id),
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        reason=reason,
        confidence=confidence,
    )

    agency["pending_approval_id"] = approval["approval_id"]
    data["agency"] = agency

    ai_msg = AIMessage(content="Routed campaign package to human-in-the-loop approval before delivery.")
    return {"current_node": "hitl_gate", "extracted_data": data, "messages": [ai_msg]}


def delivery_node(state: GraphState) -> dict:
    """
    Node: Delivery
    Responsibilities: package the approved campaign for export. Only reached after
    a human approves the pending HITL gate approval and the run is resumed.
    """
    print(f"Running Delivery for run {state['run'].id}")

    data, agency = _agency_data(state)
    package = agency.get("campaign_package", {})

    delivery_bundle = {
        "campaign_package": package,
        "delivered_at": datetime.utcnow().isoformat(),
        "approval_id": agency.get("pending_approval_id"),
        "format": "json_bundle_v1",
    }
    agency["delivery"] = delivery_bundle
    data["agency"] = agency

    ai_msg = AIMessage(content="Campaign package approved and delivered.")
    return {
        "current_node": "delivery",
        "extracted_data": data,
        "messages": [ai_msg],
        "validation_status": "passed",
    }
