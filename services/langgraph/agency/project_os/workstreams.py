"""Workstream templates: product, creative, video, content, search, social,
growth, CRM and web/app work expressed over the existing N1 vocabulary.

Each stage that produces a durable artifact names its N1 ``ArtifactType`` and a
``subtype``. Stages are not new artifact types: N1 stays small, and ownership,
release reviewers and N3 production authority come from the existing kernel.
``plan_workstream`` checks every stage against N3 (some role must be allowed to
produce that type) and against what the project already holds, so a plan shows
real readiness rather than an aspirational checklist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from services.langgraph.agency.kernel.ontology import owning_department
from services.langgraph.agency.kernel.roles import ROLE_REGISTRY


@dataclass(frozen=True)
class Stage:
    key: str
    artifact_type: Optional[str] = None  # None = activity without a durable artifact
    subtype: Optional[str] = None
    depends_on: tuple[str, ...] = ()


def _chain(*specs: tuple[str, Optional[str], Optional[str]]) -> tuple[Stage, ...]:
    stages: list[Stage] = []
    previous: Optional[str] = None
    for key, artifact_type, subtype in specs:
        stages.append(Stage(key, artifact_type, subtype, (previous,) if previous else ()))
        previous = key
    return tuple(stages)


WORKSTREAMS: dict[str, tuple[Stage, ...]] = {
    "product": _chain(
        ("opportunity_discovery", "research_brief", "opportunity"),
        ("jtbd", "research_brief", "jtbd"),
        ("competitive_analysis", "market_analysis", "competitive"),
        ("prd", "product_spec", "prd"),
        ("prioritization_roadmap", "product_spec", "roadmap"),
        ("user_stories", "product_spec", "user_stories"),
        ("information_architecture", "design_brief", "ia"),
        ("flows_wireframes", "design_brief", "flows"),
        ("prototype_usability", "qa_report", "usability"),
        ("technical_architecture", "app_build_spec", "architecture"),
        ("api_data_contracts", "app_build_spec", "api_contract"),
        ("engineering_backlog", "implementation_plan", "backlog"),
        ("qa_security_performance", "qa_report", "release_qa"),
        ("telemetry_plan", "measurement_plan", "telemetry"),
        ("release", "release_record", "release"),
        ("post_launch_review", "measurement_plan", "post_launch"),
    ),
    "creative": _chain(
        ("creative_brief", "creative_concept", "brief"),
        ("reference_board", "creative_concept", "reference_board"),
        ("style_invariants", "asset_prompt_set", "style_invariants"),
        ("creative_bom", "creative_concept", "bom"),
        ("concepts", "creative_concept", "concepts"),
        ("prompt_package", "asset_prompt_set", "prompt_package"),
        ("masters", "media_asset", "master"),
        ("brand_lint_qa", "qa_report", "brand_lint"),
        ("channel_derivatives", "media_asset", "derivative"),
    ),
    "video": _chain(
        ("premise", "creative_concept", "premise"),
        ("character_world_bible", "creative_concept", "bible"),
        ("treatment", "creative_concept", "treatment"),
        ("script", "copy_variant", "video_script"),
        ("storyboard_shot_list", "asset_prompt_set", "storyboard"),
        ("shot_prompts", "asset_prompt_set", "shot_ir_prompts"),
        ("render_master", "media_asset", "video_master"),
        ("qc", "qa_report", "video_qc"),
        ("platform_variants", "media_asset", "video_variant"),
        ("thumbnails", "media_asset", "thumbnail"),
    ),
    "content": _chain(
        ("content_strategy", "media_plan", "content_strategy"),
        ("topic_inventory", "market_analysis", "topic_inventory"),
        ("editorial_briefs", "creative_concept", "editorial_brief"),
        ("fact_cores", "knowledge_capsule", "content_atom"),
        ("derivatives", "copy_variant", "derivative"),
        ("editorial_calendar", "media_plan", "editorial_calendar"),
        ("measurement", "measurement_plan", "content_measurement"),
    ),
    "search": _chain(
        ("seo_audit", "research_brief", "seo_audit"),
        ("search_intent_map", "market_analysis", "search_intent_map"),
        ("entity_map", "market_analysis", "entity_map"),
        ("topic_graph", "market_analysis", "topic_graph"),
        ("content_gap_map", "market_analysis", "content_gap_map"),
        ("seo_content_brief", "research_brief", "seo_content_brief"),
        ("ai_discoverability_brief", "research_brief", "ai_discoverability_brief"),
        ("technical_seo_plan", "implementation_plan", "technical_seo_plan"),
        ("search_measurement_plan", "measurement_plan", "search_measurement_plan"),
    ),
    "social": _chain(
        ("platform_strategy", "media_plan", "platform_strategy"),
        ("channel_voice", "brand_guidelines_doc", "channel_voice"),
        ("creative_templates", "asset_prompt_set", "social_templates"),
        ("social_calendar", "media_plan", "social_calendar"),
        ("posts", "copy_variant", "social_post"),
        ("community_playbook", "copy_variant", "community_replies"),
        ("listening_report", "market_analysis", "social_listening"),
        ("performance_review", "measurement_plan", "social_performance"),
    ),
    "growth": _chain(
        ("gtm", "offer_definition", "gtm"),
        ("funnel_architecture", "campaign_package", "funnel"),
        ("segmentation", "market_analysis", "segments"),
        ("experiment_backlog", "measurement_plan", "experiments"),
        ("landing_pages", "copy_variant", "landing_page"),
        ("cro_review", "measurement_plan", "cro"),
    ),
    "crm": _chain(
        ("journey_map", "campaign_package", "journey_map"),
        ("lifecycle_messages", "copy_variant", "lifecycle_message"),
        ("trigger_schedule", "automation_spec", "lifecycle_triggers"),
        ("lifecycle_measurement", "measurement_plan", "lifecycle"),
    ),
    "web_app": _chain(
        ("discovery", "research_brief", "web_discovery"),
        ("ia_content_model", "design_brief", "content_model"),
        ("ui_design_system", "design_system_spec", "web_ui"),
        ("design_tokens", "design_token_set", "web_tokens"),
        ("cms_schema", "app_build_spec", "cms_schema"),
        ("component_inventory", "design_system_spec", "component_inventory"),
        ("page_contracts", "app_build_spec", "page_contracts"),
        ("api_contracts", "app_build_spec", "api_contract"),
        ("test_plan", "implementation_plan", "test_plan"),
        ("a11y_performance_qa", "qa_report", "web_qa"),
        ("deployment_manifest", "release_record", "deployment_manifest"),
        ("post_deploy_smoke", "qa_report", "post_deploy_smoke"),
    ),
}


class UnknownWorkstream(ValueError):
    pass


def producing_roles(artifact_type: str) -> list[str]:
    return sorted(role_id for role_id, role in ROLE_REGISTRY.items() if any(t.value == artifact_type for t in role.produces))


def plan_workstream(kind: str, existing: Iterable[Mapping[str, object]] = ()) -> dict[str, object]:
    """``existing`` rows are artifact metadata with artifact_type, subtype, status."""
    stages = WORKSTREAMS.get(kind)
    if stages is None:
        raise UnknownWorkstream(f"unknown workstream {kind!r}; known: {', '.join(sorted(WORKSTREAMS))}")
    have: dict[tuple[str, str], str] = {}
    for row in existing:
        have[(str(row.get("artifact_type")), str(row.get("subtype") or ""))] = str(row.get("status"))
    plan = []
    done: set[str] = set()
    for stage in stages:
        status = None
        roles: list[str] = []
        owner = None
        if stage.artifact_type:
            owner = owning_department(stage.artifact_type).value
            roles = producing_roles(stage.artifact_type)
            status = have.get((stage.artifact_type, stage.subtype or ""))
        if status in {"approved", "release_eligible", "released"}:
            readiness = "DONE"
            done.add(stage.key)
        elif status is not None:
            readiness = "IN_PROGRESS" if status not in {"invalidated", "review_required"} else "STALE"
        elif all(dep in done for dep in stage.depends_on):
            readiness = "READY" if roles or not stage.artifact_type else "NO_AUTHORIZED_ROLE"
        else:
            readiness = "WAITING"
        plan.append({
            "stage": stage.key,
            "artifact_type": stage.artifact_type,
            "subtype": stage.subtype,
            "owner_department": owner,
            "producing_roles": roles,
            "depends_on": list(stage.depends_on),
            "existing_status": status,
            "readiness": readiness,
        })
    return {"workstream": kind, "stages": plan, "complete": len(done) == len(stages)}
