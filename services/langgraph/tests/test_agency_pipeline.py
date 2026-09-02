from datetime import datetime, timezone
from uuid import uuid4

from services.langgraph.graph.agency.build import AGENCY_PIPELINE_STAGES, build_agency_workflow
from services.langgraph.graph.agency.llm import GenerationOutcome
from services.langgraph.graph.models import AgentRun
from services.langgraph.agency.exporter import export_idea_workspace, resolve_export_root
from services.langgraph.persistence.approvals import get_approvals_for_run, resolve_approval
from services.langgraph.quality.brand_safety import check_brand_safety


def _make_run(**metadata_overrides) -> AgentRun:
    now = datetime.utcnow()
    brief = {
        "brand_name": "Northwind Coffee",
        "industry": "food_and_beverage",
        "goals": ["Grow awareness in new markets"],
        "target_audience": "Urban professionals aged 25-40",
        "tone": "warm and confident",
        "channels": ["instagram", "email"],
        "constraints": ["No health claims"],
    }
    brief.update(metadata_overrides)
    return AgentRun(
        id=uuid4(),
        tenant_id="tenant-agency-test",
        project_id="proj-agency-test",
        status="running",
        created_at=now,
        updated_at=now,
        metadata={"input_data": {"brief": brief}},
    )


def _initial_state(run: AgentRun) -> dict:
    return {
        "run": run,
        "current_node": "start",
        "messages": [],
        "extracted_data": {},
        "validation_status": "pending",
    }


def _force_provider_success(monkeypatch):
    def fake_generate(prompt: str, fallback: dict, **kwargs):
        now = datetime.now(timezone.utc).isoformat()
        return GenerationOutcome(
            data=fallback,
            mode="PROVIDER_SUCCESS",
            provider="test-provider",
            model="test-model",
            schema_version=kwargs.get("schema_version", "test-v1"),
            prompt_version="test-v1",
            prompt_hash="test-hash",
            attempts=1,
            started_at=now,
            completed_at=now,
            fallback_used=False,
            error_class=None,
        )

    monkeypatch.setattr("services.langgraph.graph.agency.nodes.generate_structured", fake_generate)


def test_agency_graph_pauses_before_delivery_and_creates_approval():
    run = _make_run()
    graph = build_agency_workflow()
    config = {"configurable": {"thread_id": str(run.id)}}
    state = graph.invoke(_initial_state(run), config=config)
    assert state["current_node"] == "hitl_gate"
    agency = state["extracted_data"]["agency"]
    assert "delivery" not in agency
    assert agency["campaign_package"]["brief"]["brand_name"] == "Northwind Coffee"
    assert agency["campaign_package"]["business_workspace"]["overview"]["idea_name"] == "Northwind Coffee"
    assert agency["campaign_package"]["branding_workspace"]["raw_brand_data"]["brand_name"] == "Northwind Coffee"
    assert agency["campaign_package"]["design_system"]["tokens_json"]["brand"]["semantic"]["color"]["bg"]["value"] == "{brand.raw.surface.value}"
    assert len(agency["campaign_package"]["asset_execution"]["rendered_assets"]) == 3
    assert agency["campaign_package"]["asset_execution"]["review_queue"]["review_status"] == "pending_review"
    assert len(agency["creative_concepts"]) == 3
    assert len(agency["copy_variants"]) == 3
    snapshot = graph.get_state(config)
    assert snapshot.next == ("delivery",)
    approvals = get_approvals_for_run(str(run.id))
    assert len(approvals) == 1
    assert approvals[0]["status"] == "pending"


def test_agency_graph_resumes_and_delivers_after_successful_provider_approval(monkeypatch):
    _force_provider_success(monkeypatch)
    run = _make_run()
    graph = build_agency_workflow()
    config = {"configurable": {"thread_id": str(run.id)}}
    graph.invoke(_initial_state(run), config=config)
    approvals = get_approvals_for_run(str(run.id))
    resolve_approval(approvals[0]["approval_id"], reviewer="qa-bot", decision="approve")
    final_state = graph.invoke(None, config=config)
    assert final_state["current_node"] == "delivery"
    assert final_state["validation_status"] == "passed"
    delivery = final_state["extracted_data"]["agency"]["delivery"]
    assert delivery["campaign_package"]["brief"]["brand_name"] == "Northwind Coffee"
    assert delivery["campaign_package"]["design_system"]["component_scaffolds"][0]["path"].endswith("Button.tsx")
    assert delivery["campaign_package"]["asset_execution"]["publishing_adapters"][0]["status"] == "draft_only"
    assert delivery["approval_id"] == approvals[0]["approval_id"]
    assert graph.get_state(config).next == ()


def test_export_root_is_writable_without_zo_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("AMC_EXPORT_ROOT", raising=False)
    monkeypatch.setattr("services.langgraph.agency.exporter._ZO_WORKSPACE", tmp_path / "missing-zo")
    monkeypatch.setattr("services.langgraph.agency.exporter.os.access", lambda *_args, **_kwargs: False)
    root = resolve_export_root()
    assert root.name == "amc-idea-exports"
    root.mkdir(parents=True, exist_ok=True)
    probe = root / "ci-write-probe.txt"
    probe.write_text("ok\n", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok\n"


def test_export_idea_workspace_renders_assets(tmp_path, monkeypatch):
    monkeypatch.setattr("services.langgraph.agency.exporter.DEFAULT_EXPORT_ROOT", tmp_path)
    run = _make_run()
    graph = build_agency_workflow()
    state = graph.invoke(_initial_state(run), config={"configurable": {"thread_id": str(run.id)}})
    package = state["extracted_data"]["agency"]["campaign_package"]
    export = export_idea_workspace(brand_name="Northwind Coffee", run_id=str(run.id), package=package)
    assert export["rendered_assets_folder"].endswith("/branding/rendered")
    written = export["files_written"]
    assert any(path.endswith("branding/rendered/logo-mark.svg") for path in written)
    assert any(path.endswith("branding/rendered/background-pattern.svg") for path in written)
    assert any(path.endswith("branding/rendered/hero-illustration.svg") for path in written)
    assert any(path.endswith("branding/review/asset-approval-inbox.md") for path in written)


def test_workspace_export_artifacts_bind_to_canonical_revision_path(tmp_path, monkeypatch):
    import services.langgraph.persistence.sqlite_db as sqlite_db
    from services.langgraph.api.routes.agency import _bind_workspace_export_artifacts
    from services.langgraph.persistence.agency_kernel import get_artifact

    sqlite_db.init_db()
    monkeypatch.setattr("services.langgraph.agency.exporter.DEFAULT_EXPORT_ROOT", tmp_path)

    run = _make_run()
    graph = build_agency_workflow()
    state = graph.invoke(_initial_state(run), config={"configurable": {"thread_id": str(run.id)}})
    package = state["extracted_data"]["agency"]["campaign_package"]
    export = export_idea_workspace(brand_name="Northwind Coffee", run_id=str(run.id), package=package)

    first_bindings = _bind_workspace_export_artifacts(
        run_id=str(run.id),
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        package=package,
        workspace_export=export,
    )
    assert {item["artifact_key"] for item in first_bindings} == {
        "business_model_spec",
        "brand_core",
        "asset_prompt_set",
        "design_token_set",
        "design_system_spec",
        "website_lockup_spec",
        "campaign_package",
    }
    assert all(item["created"] is True for item in first_bindings)
    prompt_binding = next(item for item in first_bindings if item["artifact_key"] == "asset_prompt_set")
    prompt_artifact = get_artifact(prompt_binding["artifact_id"])
    assert prompt_artifact is not None
    assert prompt_artifact["version"] == 1
    assert prompt_artifact["content_location"].endswith("/branding/prompts")

    package["branding_workspace"]["visual_asset_prompts"][0]["body"] += "\nAdd sharper silhouette constraints."
    second_bindings = _bind_workspace_export_artifacts(
        run_id=str(run.id),
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        package=package,
        workspace_export=export,
    )
    second_prompt_binding = next(item for item in second_bindings if item["artifact_key"] == "asset_prompt_set")
    assert second_prompt_binding["created"] is False
    assert second_prompt_binding["changed"] is True
    assert second_prompt_binding["version"] == 2


def test_pipeline_stage_order_is_stable():
    assert AGENCY_PIPELINE_STAGES == [
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


def test_brand_safety_flags_banned_claims():
    assert check_brand_safety("This product is a guaranteed cure for everything.") == ["guaranteed", "cure"]
    assert check_brand_safety("A thoughtfully designed everyday companion.") == []


def test_brand_safety_qa_node_flags_banned_claims_in_assembled_copy():
    from services.langgraph.graph.agency.nodes import brand_safety_qa_node

    run = _make_run()
    state = _initial_state(run)
    state["extracted_data"] = {
        "agency": {
            "campaign_package": {
                "strategy": {"positioning_statement": "A trusted everyday choice."},
                "copy_variants": [
                    {
                        "concept_id": "concept-1",
                        "headline": "Guaranteed results, every time.",
                        "body": "Our formula is a clinically proven miracle for your routine.",
                        "cta": "Try the cure today",
                    }
                ],
            }
        }
    }
    result = brand_safety_qa_node(state)
    qa_report = result["extracted_data"]["agency"]["qa_report"]
    assert qa_report["brand_safety_passed"] is False
    assert set(qa_report["flagged_terms"]) == {"guaranteed", "clinically proven", "miracle", "cure"}
    assert result["validation_status"] == "failed"
