import json
import logging
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from services.langgraph.graph.agency.llm import GenerationOutcome, generate_structured
from services.langgraph.graph.agency.models import (
    BrandStrategy,
    CampaignBrief,
    CampaignPackage,
    CopyVariant,
    CreativeConcept,
    DesignBrief,
    QAReport,
)
from services.langgraph.graph.state import GraphState
from services.langgraph.persistence.approvals import create_approval_request
from services.langgraph.quality.brand_safety import evaluate_brand_compliance
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
        goals=raw_brief.get("goals", []),
        target_audience=raw_brief.get("target_audience", "General audience"),
        tone=raw_brief.get("tone"),
        channels=raw_brief.get("channels", []),
        constraints=raw_brief.get("constraints", []),
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
    package = CampaignPackage(
        brief=CampaignBrief(**agency.get("brief", {})),
        strategy=BrandStrategy(**agency.get("brand_strategy", {})),
        concepts=[CreativeConcept(**item) for item in agency.get("creative_concepts", [])],
        copy_variants=[CopyVariant(**item) for item in agency.get("copy_variants", [])],
        design_brief=DesignBrief(**agency.get("design_brief", {})),
    )
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
    compliance = evaluate_brand_compliance(combined_text)
    flagged = compliance["flagged_terms"]
    quality = evaluate_quality(combined_text or package.get("strategy", {}).get("positioning_statement", ""))
    degraded_tasks = [item.get("task", "unknown") for item in agency.get("generation_provenance", []) if item.get("mode") != "PROVIDER_SUCCESS"]
    release_blocked = bool(degraded_tasks)
    qa_passed = (not flagged) and quality["threshold_passed"] and not release_blocked
    notes = ["No banned-claim heuristic matches detected." if not flagged else f"Flagged terms requiring review: {', '.join(flagged)}"]
    if release_blocked:
        notes.append("Release blocked because one or more generation stages used degraded fallback output; rerun with a configured provider before delivery.")
    notes.extend(compliance["advisories"])
    qa_report = QAReport(
        brand_safety_passed=not flagged,
        flagged_terms=flagged,
        quality_metrics=quality,
        brand_compliance=compliance,
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
