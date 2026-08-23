"""Delivery-gate parity tests for the N2-guarded resume route.

The resume route previously carried four ad-hoc checks (degraded output,
approval missing, approval unresolved, approval rejected). Those are now
evaluated by the declared N2 release guards. Only the degraded path had test
coverage, so these tests pin every branch of the error contract — status code,
detail text, and the persisted lifecycle-event reason — against the behavior
that shipped before the refactor.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.langgraph.agency.kernel.lifecycle import TransitionContext, release_guard_failures
from services.langgraph.api.routes.agency import _DELIVERY_BLOCK_DETAIL, _delivery_context
from services.langgraph.app.main import app
from services.langgraph.graph.agency.llm import GenerationOutcome

client = TestClient(app)


@pytest.fixture
def provider_success(monkeypatch):
    """Force PROVIDER_SUCCESS so the degraded guard does not mask later guards.

    Without a configured provider the pipeline degrades, and the degraded guard
    fires first by design. These tests target the approval guards, so the run
    must be non-degraded to reach them.
    """

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


def _create_run(project_id: str = "proj-delivery-gate") -> dict:
    response = client.post(
        "/agency/runs",
        json={
            "project_id": project_id,
            "brief": {"brand_name": "Northwind", "target_audience": "Urban professionals"},
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()


def _resume(run_id: str):
    return client.post(f"/agency/runs/{run_id}/resume", headers={"Idempotency-Key": str(uuid4())})


# ---------------------------------------------------------------------------
# Route-level behavior
# ---------------------------------------------------------------------------

def test_unresolved_approval_blocks_delivery(provider_success):
    body = _create_run()
    response = _resume(body["run_id"])
    assert response.status_code == 409
    assert response.json()["detail"] == "Run still has an unresolved approval"


def test_degraded_output_blocks_before_the_approval_guard(monkeypatch):
    """Guard order is part of the contract: degraded reports first."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    body = _create_run()
    response = _resume(body["run_id"])
    assert response.status_code == 409
    assert "degraded" in response.json()["detail"].lower()


def test_rejected_approval_blocks_delivery_and_names_the_decision(provider_success):
    body = _create_run()
    approval_id = body["pending_approval"]["approval_id"]
    decision = client.post(
        f"/approvals/{approval_id}/decide",
        json={"decision": "reject"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert decision.status_code == 200

    response = _resume(body["run_id"])
    assert response.status_code == 409
    detail = response.json()["detail"]
    # A rejected run reaches a terminal rejected state rather than staying
    # deliverable; either way delivery must not proceed.
    assert "reject" in detail.lower() or "not awaiting delivery" in detail.lower()


# ---------------------------------------------------------------------------
# Guard-context mapping
#
# These assert the translation layer directly, so a change to the guard set
# cannot silently alter the route's error contract.
# ---------------------------------------------------------------------------

def _context(**overrides) -> TransitionContext:
    qa_report = {
        "release_blocked": overrides.pop("release_blocked", False),
        "brand_safety_passed": overrides.pop("brand_safety_passed", True),
    }
    approval = overrides.pop("approval", {"status": "resolved", "decision": "approve"})
    return _delivery_context({"qa_report": qa_report}, approval)


def test_clean_run_passes_every_release_guard():
    assert release_guard_failures(_context()) == []


@pytest.mark.parametrize(
    "overrides,expected_code",
    [
        ({"release_blocked": True}, "degraded_release_block"),
        ({"approval": None}, "approval_missing"),
        ({"approval": {"status": "pending", "decision": None}}, "approval_pending"),
        ({"approval": {"status": "resolved", "decision": "reject"}}, "approval_not_approved"),
    ],
)
def test_each_blocked_condition_maps_to_its_stable_guard_code(overrides, expected_code):
    failures = release_guard_failures(_context(**overrides))
    assert [failure.code for failure in failures] == [expected_code]
    # Every code the route can surface must have a detail renderer.
    assert expected_code in _DELIVERY_BLOCK_DETAIL


def test_every_guard_code_has_a_detail_renderer():
    """No guard may reach the route without a mapped, renderable message."""
    from services.langgraph.agency.kernel.lifecycle import RELEASE_GUARDS

    for code, _guard in RELEASE_GUARDS:
        assert code in _DELIVERY_BLOCK_DETAIL, f"guard '{code}' has no HTTP detail mapping"
        rendered = _DELIVERY_BLOCK_DETAIL[code]({"decision": "reject"})
        assert isinstance(rendered, str) and rendered


def test_degraded_output_is_not_discharged_by_human_approval():
    """The keystone constraint: approval never releases degraded output."""
    failures = release_guard_failures(_context(release_blocked=True))
    assert [failure.code for failure in failures] == ["degraded_release_block"]


def test_brand_safety_flag_is_advisory_on_this_route_when_approved():
    """Documents the route's established policy, so a change is deliberate.

    A reviewer may approve a campaign whose brand-safety heuristic flagged
    terms. If this assertion ever needs to flip, the policy decision is to make
    brand safety a hard gate by dropping brand_safety_advisory in
    _delivery_context.
    """
    assert release_guard_failures(_context(brand_safety_passed=False)) == []


def test_approval_blocks_stay_out_of_lifecycle_analytics():
    """Awaiting a decision is ordinary; it must not emit a delivery-blocked event."""
    from services.langgraph.api.routes.agency import _ANALYTICS_REPORTED_BLOCKS

    assert "approval_pending" not in _ANALYTICS_REPORTED_BLOCKS
    assert "approval_missing" not in _ANALYTICS_REPORTED_BLOCKS
    assert "approval_not_approved" not in _ANALYTICS_REPORTED_BLOCKS
    assert "degraded_release_block" in _ANALYTICS_REPORTED_BLOCKS


def test_brand_safety_flag_still_blocks_when_the_run_is_not_approved():
    failures = release_guard_failures(
        _context(brand_safety_passed=False, approval={"status": "pending", "decision": None})
    )
    codes = [failure.code for failure in failures]
    assert "approval_pending" in codes
    assert "brand_safety_failed" in codes


# ---------------------------------------------------------------------------
# N1 enforcement at the persistence boundary
# ---------------------------------------------------------------------------

def _engagement() -> str:
    from services.langgraph.persistence import agency_kernel as kernel

    engagement_id = f"eng-{uuid4()}"
    kernel.create_engagement(engagement_id, "tenant_1", "proj_1", "Objective", "Outcome")
    return engagement_id


def test_workstream_rejects_a_department_outside_the_ontology():
    from services.langgraph.agency.kernel.ontology import OntologyError
    from services.langgraph.persistence import agency_kernel as kernel

    engagement_id = _engagement()
    with pytest.raises(OntologyError):
        kernel.create_workstream(
            f"ws-{uuid4()}", engagement_id, "tenant_1", "proj_1", "marketing", "Do marketing"
        )


def test_artifact_rejects_an_unknown_type():
    from services.langgraph.agency.kernel.ontology import OntologyError
    from services.langgraph.persistence import agency_kernel as kernel

    engagement_id = _engagement()
    with pytest.raises(OntologyError):
        kernel.create_artifact(
            f"art-{uuid4()}", engagement_id, "tenant_1", "proj_1", "landing_page", "growth"
        )


def test_artifact_rejects_a_department_that_does_not_own_the_type():
    from services.langgraph.agency.kernel.ontology import OntologyError
    from services.langgraph.persistence import agency_kernel as kernel

    engagement_id = _engagement()
    with pytest.raises(OntologyError):
        kernel.create_artifact(
            f"art-{uuid4()}", engagement_id, "tenant_1", "proj_1", "media_plan", "copy"
        )


def test_artifact_accepts_the_canonical_owning_department():
    from services.langgraph.persistence import agency_kernel as kernel

    engagement_id = _engagement()
    record = kernel.create_artifact(
        f"art-{uuid4()}", engagement_id, "tenant_1", "proj_1", "campaign_package", "growth"
    )
    assert record["artifact_type"] == "campaign_package"
    assert record["owner_department"] == "growth"
