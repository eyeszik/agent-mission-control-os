from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError


def _kernel():
    """Use the suite-managed SQLite database without mutating shared module state."""
    import services.langgraph.persistence.sqlite_db as sqlite_db
    from services.langgraph.persistence import agency_kernel

    sqlite_db.init_db()
    return sqlite_db, agency_kernel


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _confidence() -> dict:
    return {
        "evidence": 0.9,
        "freshness": 0.9,
        "contract": 0.95,
        "execution": 0.8,
        "safety": 1.0,
        "strategic_coherence": 0.9,
        "aggregate": 0.9,
    }


def test_agency_kernel_persists_and_selectively_invalidates():
    sqlite_db, kernel = _kernel()
    assert sqlite_db.current_schema_version() == 9

    engagement_id = _id("eng")
    workstream_id = _id("ws-strategy")
    evidence_id = _id("ev")
    decision_id = _id("dec")
    positioning_id = _id("art-positioning")
    messaging_id = _id("art-messaging")
    landing_id = _id("art-landing")

    engagement = kernel.create_engagement(
        engagement_id,
        "tenant_1",
        "proj_1",
        "Launch a new product",
        "Validated brand, product, and launch system",
        constraints={"budget": "bounded"},
        permissions={"production_deploy": False},
    )
    assert engagement["objective"] == "Launch a new product"
    assert engagement["permissions"] == {"production_deploy": False}

    workstream = kernel.create_workstream(
        workstream_id,
        engagement_id,
        "tenant_1",
        "proj_1",
        "strategy",
        "Define positioning",
        acceptance_criteria=["positioning is evidence-backed"],
    )
    assert workstream["department"] == "strategy"

    evidence = kernel.create_evidence(
        evidence_id,
        engagement_id,
        "tenant_1",
        "proj_1",
        "customer_research",
        "Customers value faster setup",
        "verified",
        0.92,
        source_ref="research://customer-interview-set",
    )
    assert evidence["confidence"] == pytest.approx(0.92)

    decision = kernel.create_decision(
        decision_id,
        engagement_id,
        "tenant_1",
        "proj_1",
        "Which positioning should lead?",
        _confidence(),
        alternatives=["speed", "price"],
        selected_option="speed",
        evidence_ids=[evidence_id],
        status="accepted",
    )
    assert decision["selected_option"] == "speed"
    assert decision["confidence"]["aggregate"] == pytest.approx(0.9)

    kernel.create_artifact(
        positioning_id,
        engagement_id,
        "tenant_1",
        "proj_1",
        "positioning_statement",
        "strategy",
        workstream_id=workstream_id,
        status="approved",
    )
    kernel.create_artifact(
        messaging_id,
        engagement_id,
        "tenant_1",
        "proj_1",
        "brand_platform",
        "brand",
        status="approved",
    )
    kernel.create_artifact(
        landing_id,
        engagement_id,
        "tenant_1",
        "proj_1",
        "campaign_package",
        "growth",
        status="approved",
    )

    kernel.add_artifact_dependency(messaging_id, positioning_id, "hard")
    kernel.add_artifact_dependency(landing_id, messaging_id, "soft")

    graph = kernel.artifact_dependency_graph(engagement_id)
    assert {node["artifact_id"] for node in graph["nodes"]} == {landing_id, messaging_id, positioning_id}
    assert len(graph["edges"]) == 2

    affected = kernel.propagate_artifact_change(positioning_id)
    assert affected == sorted(
        [
            {"artifact_id": landing_id, "status": "review_required"},
            {"artifact_id": messaging_id, "status": "invalidated"},
        ],
        key=lambda item: item["artifact_id"],
    )
    assert kernel.get_artifact(messaging_id)["status"] == "invalidated"
    assert kernel.get_artifact(landing_id)["status"] == "review_required"


def test_artifact_dependency_rejects_cycles_and_cross_engagement_edges():
    _sqlite_db, kernel = _kernel()

    engagement_a = _id("eng-a")
    engagement_b = _id("eng-b")
    for engagement_id in [engagement_a, engagement_b]:
        kernel.create_engagement(
            engagement_id,
            "tenant_1",
            "proj_1",
            "Objective",
            "Outcome",
        )

    a1 = _id("a1")
    a2 = _id("a2")
    b1 = _id("b1")
    kernel.create_artifact(a1, engagement_a, "tenant_1", "proj_1", "positioning_statement", "strategy")
    kernel.create_artifact(a2, engagement_a, "tenant_1", "proj_1", "brand_platform", "brand")
    kernel.create_artifact(b1, engagement_b, "tenant_1", "proj_1", "campaign_package", "growth")

    kernel.add_artifact_dependency(a2, a1, "hard")

    with pytest.raises(ValueError, match="cycle"):
        kernel.add_artifact_dependency(a1, a2, "hard")

    with pytest.raises(ValueError, match="cross engagement"):
        kernel.add_artifact_dependency(b1, a1, "soft")


def test_confidence_vector_enforces_unit_interval():
    from services.langgraph.agency.kernel.models import ConfidenceVector

    with pytest.raises(ValidationError):
        ConfidenceVector(
            evidence=1.1,
            freshness=1.0,
            contract=1.0,
            execution=1.0,
            safety=1.0,
            strategic_coherence=1.0,
            aggregate=1.0,
        )


def test_engagement_model_uses_typed_status():
    from services.langgraph.agency.kernel.models import Engagement, EngagementStatus

    now = datetime.now(timezone.utc)
    engagement = Engagement(
        engagement_id=_id("eng-model"),
        tenant_id="tenant_1",
        project_id="proj_1",
        objective="Build the product",
        desired_outcome="Working product",
        created_at=now,
        updated_at=now,
    )
    assert engagement.status is EngagementStatus.intake


def test_artifact_revision_auto_stales_bound_approvals_and_opens_lineage_remediation():
    _sqlite_db, kernel = _kernel()
    from services.langgraph.persistence.approvals import bind_approval_subject, create_approval_request, get_approval
    from services.langgraph.persistence.lineage import list_project_lineage_remediations

    engagement_id = _id("eng-lineage")
    artifact_id = _id("art-lineage")
    run_id = _id("run-lineage")
    kernel.create_engagement(engagement_id, "tenant_1", "proj_1", "Protect artifact", "Keep lineage canonical")
    kernel.create_artifact(
        artifact_id,
        engagement_id,
        "tenant_1",
        "proj_1",
        "campaign_package",
        "growth",
        status="approved",
        metadata={"protected_run_id": run_id},
    )
    approval = create_approval_request(
        run_id,
        "tenant_1",
        "proj_1",
        "review protected artifact",
        0.8,
        subject_type="ARTIFACT_VERSION",
        subject_ref=artifact_id,
        subject_version_ref=f"{artifact_id}:v1",
        subject_hash="a" * 64,
    )
    bind_approval_subject(
        approval["approval_id"],
        subject_hash="a" * 64,
        subject_ref=artifact_id,
        subject_version_ref=f"{artifact_id}:v1",
    )

    revised = kernel.record_artifact_revision(artifact_id, content_hash="b" * 64)
    assert revised["artifact"]["version"] == 2

    stale = get_approval(approval["approval_id"])
    assert stale["status"] == "stale"
    assert stale["stale_reason"].startswith("artifact_version_changed:")
    queue = list_project_lineage_remediations("proj_1", "tenant_1")
    assert queue
    assert queue[0]["run_id"] == run_id
    assert queue[0]["artifact_id"] == artifact_id
    assert queue[0]["status"] == "OPEN"
