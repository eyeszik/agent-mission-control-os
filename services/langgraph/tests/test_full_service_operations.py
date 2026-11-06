from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from services.langgraph.agency.full_service import compile_agency_operations
from services.langgraph.agency.kernel import assert_role_may_produce, get_role
from services.langgraph.app.main import app
from services.langgraph.graph.agency.llm import GenerationOutcome
from services.langgraph.graph.agency.nodes import (
    LIVE_STAGE_ARTIFACTS,
    LIVE_STAGE_ROLE_BINDINGS,
)

client = TestClient(app)


def _provider_success(monkeypatch):
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


def test_full_service_compiler_never_fabricates_missing_external_evidence():
    package = compile_agency_operations(
        brief={
            "brand_name": "Northwind",
            "target_audience": "Urban professionals",
            "industry": "consumer services",
            "channels": ["web", "email"],
        },
        strategy={
            "positioning_statement": "Northwind is the trusted choice for urban professionals."
        },
        copy_variants=[
            {
                "concept_id": "c1",
                "headline": "Results you can see.",
                "body": "Built for busy people.",
                "cta": "Learn more",
            }
        ],
        asset_execution={
            "rendered_assets": [
                {"asset_id": "hero-1", "output_path": "branding/rendered/hero.svg"}
            ]
        },
        generation_provenance=[
            {
                "task": "brand_strategy",
                "provider": "test-provider",
                "model": "test-model",
                "mode": "PROVIDER_SUCCESS",
                "prompt_version": "test-v1",
                "schema_version": "brand-strategy-v1",
            }
        ],
    )

    assert package.market == "UNKNOWN"
    assert package.language == "UNKNOWN"
    assert package.locale == "UNKNOWN"
    assert package.research.interview_guide
    assert package.research.competitive_audit == []
    assert package.research.perception_gaps == []
    assert "competitive_audit_requires_external_evidence" in package.research.unresolved

    assert package.claims
    assert {claim.status for claim in package.claims} == {"UNKNOWN"}
    assert all(claim.source_ref is None for claim in package.claims)

    assert package.rights_handoff
    assert package.rights_handoff[0].license_status == "UNKNOWN"
    assert package.rights_handoff[0].portfolio_permission == "UNKNOWN"
    assert package.rights_handoff[0].territory == "UNKNOWN"

    assert package.accessibility.contrast == "NOT_MEASURED"
    assert package.accessibility.assistive_technology == "NOT_MEASURED"
    assert package.media.execution_mode == "PLANNING_ONLY"
    assert package.observability.runtime_binding_status == "UNVERIFIED_EXTERNAL_BINDING"
    assert all(item.target == "UNSET" for item in package.slos)
    assert package.model_cards[0].evaluation_status == "NOT_MEASURED"
    assert package.legal_readiness == "COUNSEL_REQUIRED"
    assert "unproved_or_unknown_factual_claims" in package.external_release_blockers
    assert "asset_rights_clearance_missing" in package.external_release_blockers


def test_live_stage_bindings_resolve_through_n3_and_production_rights():
    assert set(LIVE_STAGE_ROLE_BINDINGS) == {
        "brief_intake",
        "brand_strategy",
        "creative_concepting",
        "copywriting",
        "design_brief",
        "campaign_assembly",
        "brand_safety_qa",
        "hitl_gate",
        "delivery",
    }

    for stage, role_id in LIVE_STAGE_ROLE_BINDINGS.items():
        assert get_role(role_id).role_id == role_id
        artifact_type = LIVE_STAGE_ARTIFACTS.get(stage)
        if artifact_type is not None:
            assert_role_may_produce(role_id, artifact_type)


def test_live_campaign_package_contains_full_service_operations(monkeypatch):
    _provider_success(monkeypatch)

    response = client.post(
        "/agency/runs",
        json={
            "project_id": f"proj-full-service-{uuid4()}",
            "brief": {
                "brand_name": "Northwind",
                "target_audience": "Urban professionals",
                "market": "Los Angeles",
                "language": "English",
                "locale": "en-US",
                "channels": ["web", "email"],
            },
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    package = response.json()["campaign_package"]
    operations = package["agency_operations"]

    assert operations["schema_version"] == "amc-agency-operations/v1"
    assert operations["market"] == "Los Angeles"
    assert operations["language"] == "English"
    assert operations["locale"] == "en-US"
    assert operations["research"]["interview_guide"]
    assert operations["claims"]
    assert operations["rights_handoff"]
    assert operations["accessibility"]["status"] == "GAP"
    assert operations["media"]["execution_mode"] == "PLANNING_ONLY"
    assert operations["observability"]["runtime_binding_status"] == "UNVERIFIED_EXTERNAL_BINDING"
    assert operations["slos"]
    assert operations["model_cards"]

    exported = package["business_workspace"]["production_docs"]
    ops_docs = [item for item in exported if item["path"] == "business/operations/agency-operations.json"]
    assert len(ops_docs) == 1
    assert "amc-agency-operations/v1" in ops_docs[0]["body"]
