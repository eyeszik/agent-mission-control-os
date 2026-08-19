from uuid import uuid4
from datetime import datetime

from services.langgraph.graph.agency.build import build_agency_workflow, AGENCY_PIPELINE_STAGES
from services.langgraph.graph.models import AgentRun
from services.langgraph.quality.brand_safety import check_brand_safety
from services.langgraph.persistence.approvals import get_approvals_for_run, resolve_approval


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


def test_agency_graph_pauses_before_delivery_and_creates_approval():
    run = _make_run()
    graph = build_agency_workflow()
    config = {"configurable": {"thread_id": str(run.id)}}

    state = graph.invoke(_initial_state(run), config=config)

    # interrupt_before=["delivery"] means the graph stops before running delivery.
    assert state["current_node"] == "hitl_gate"
    agency = state["extracted_data"]["agency"]
    assert "delivery" not in agency
    assert agency["campaign_package"]["brief"]["brand_name"] == "Northwind Coffee"
    assert len(agency["creative_concepts"]) == 3
    assert len(agency["copy_variants"]) == 3

    snapshot = graph.get_state(config)
    assert snapshot.next == ("delivery",)

    approvals = get_approvals_for_run(str(run.id))
    assert len(approvals) == 1
    assert approvals[0]["status"] == "pending"


def test_agency_graph_resumes_and_delivers_after_approval():
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
    assert delivery["approval_id"] == approvals[0]["approval_id"]

    snapshot = graph.get_state(config)
    assert snapshot.next == ()


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
    assert check_brand_safety("This product is a guaranteed cure for everything.") == [
        "guaranteed",
        "cure",
    ]
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
