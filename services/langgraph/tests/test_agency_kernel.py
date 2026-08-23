from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


def _kernel(monkeypatch, tmp_path):
    db_path = str(tmp_path / "agency-kernel.db")
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AMC_DB_PATH", db_path)

    import services.langgraph.persistence.sqlite_db as sqlite_db
    importlib.reload(sqlite_db)
    sqlite_db.DB_PATH = db_path
    sqlite_db.init_db()

    import services.langgraph.persistence.database as database
    importlib.reload(database)
    database.DB_PATH = db_path

    import services.langgraph.persistence.agency_kernel as agency_kernel
    importlib.reload(agency_kernel)
    return sqlite_db, agency_kernel


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


def test_agency_kernel_persists_and_selectively_invalidates(monkeypatch, tmp_path):
    sqlite_db, kernel = _kernel(monkeypatch, tmp_path)
    assert sqlite_db.current_schema_version() == 5

    engagement = kernel.create_engagement(
        "eng_1",
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
        "ws_strategy",
        "eng_1",
        "tenant_1",
        "proj_1",
        "strategy",
        "Define positioning",
        acceptance_criteria=["positioning is evidence-backed"],
    )
    assert workstream["department"] == "strategy"

    evidence = kernel.create_evidence(
        "ev_1",
        "eng_1",
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
        "dec_1",
        "eng_1",
        "tenant_1",
        "proj_1",
        "Which positioning should lead?",
        _confidence(),
        alternatives=["speed", "price"],
        selected_option="speed",
        evidence_ids=["ev_1"],
        status="accepted",
    )
    assert decision["selected_option"] == "speed"
    assert decision["confidence"]["aggregate"] == pytest.approx(0.9)

    kernel.create_artifact(
        "art_positioning",
        "eng_1",
        "tenant_1",
        "proj_1",
        "positioning",
        "strategy",
        workstream_id="ws_strategy",
        status="approved",
    )
    kernel.create_artifact(
        "art_messaging",
        "eng_1",
        "tenant_1",
        "proj_1",
        "messaging",
        "brand",
        status="approved",
    )
    kernel.create_artifact(
        "art_landing",
        "eng_1",
        "tenant_1",
        "proj_1",
        "landing_page",
        "growth",
        status="approved",
    )

    kernel.add_artifact_dependency("art_messaging", "art_positioning", "hard")
    kernel.add_artifact_dependency("art_landing", "art_messaging", "soft")

    graph = kernel.artifact_dependency_graph("eng_1")
    assert [node["artifact_id"] for node in graph["nodes"]] == ["art_landing", "art_messaging", "art_positioning"]
    assert len(graph["edges"]) == 2

    affected = kernel.propagate_artifact_change("art_positioning")
    assert affected == [
        {"artifact_id": "art_landing", "status": "review_required"},
        {"artifact_id": "art_messaging", "status": "invalidated"},
    ]
    assert kernel.get_artifact("art_messaging")["status"] == "invalidated"
    assert kernel.get_artifact("art_landing")["status"] == "review_required"


def test_artifact_dependency_rejects_cycles_and_cross_engagement_edges(monkeypatch, tmp_path):
    _sqlite_db, kernel = _kernel(monkeypatch, tmp_path)

    for engagement_id in ["eng_a", "eng_b"]:
        kernel.create_engagement(
            engagement_id,
            "tenant_1",
            "proj_1",
            "Objective",
            "Outcome",
        )

    kernel.create_artifact("a1", "eng_a", "tenant_1", "proj_1", "strategy", "strategy")
    kernel.create_artifact("a2", "eng_a", "tenant_1", "proj_1", "messaging", "brand")
    kernel.create_artifact("b1", "eng_b", "tenant_1", "proj_1", "campaign", "growth")

    kernel.add_artifact_dependency("a2", "a1", "hard")

    with pytest.raises(ValueError, match="cycle"):
        kernel.add_artifact_dependency("a1", "a2", "hard")

    with pytest.raises(ValueError, match="cross engagement"):
        kernel.add_artifact_dependency("b1", "a1", "soft")


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
        engagement_id="eng_model",
        tenant_id="tenant_1",
        project_id="proj_1",
        objective="Build the product",
        desired_outcome="Working product",
        created_at=now,
        updated_at=now,
    )
    assert engagement.status is EngagementStatus.intake
