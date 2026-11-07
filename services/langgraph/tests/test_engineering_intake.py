"""Durable handoff intake reuses the existing fenced job store and no second FSM."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from services.langgraph.agency.durable.ticks import run_tick
from services.langgraph.agency.engineering.contracts import (
    AcceptanceCriterion,
    BudgetCeiling,
    DeliverableKind,
    DeliverableSpec,
    HandoffRequest,
    OutputDestination,
    RequestedAction,
    SourceRef,
)
from services.langgraph.agency.engineering.intake import (
    ENGINEERING_HANDOFF_KIND,
    submit_handoff,
)
from services.langgraph.persistence import durable_runs
from services.langgraph.persistence.projects import create_project_workspace
from services.langgraph.security.auth import Principal


def handoff(**changes) -> HandoffRequest:
    base = {
        "campaign_id": "fixture-campaign",
        "source_refs": (SourceRef(artifact_id="fixture-brief", version=1, content_hash="a" * 64,
                                  source_kind="approved_brief"),),
        "repository_id": "example-repo",
        "objective": "Apply one reviewed, bounded repository change.",
        "deliverable": DeliverableSpec(
            kind=DeliverableKind.REPOSITORY_PATCH,
            title="Synthetic handoff",
            audience="Local reviewer",
            approved_brief="Fixture input only; no provider or external action.",
            acceptance=(AcceptanceCriterion(criterion_id="TEST_PASS", description="A declared fixture test passes.",
                                            evidence_required=("check_record",)),),
        ),
        "requested_actions": (RequestedAction.LOCAL_PATCH, RequestedAction.RUN_CHECKS),
        "output_destinations": (OutputDestination.LOCAL_REVIEW,),
        "budget_ceiling": BudgetCeiling(max_provider_cost_microusd=0, max_compute_seconds=60,
                                         max_storage_bytes=1_000_000),
    }
    base.update(changes)
    return HandoffRequest.model_validate(base)


@pytest.fixture
def authorized_scope(tmp_path):
    tenant = "fixture-eng-" + uuid4().hex
    project = "prj-" + uuid4().hex[:12]
    create_project_workspace(tenant_id=tenant, project_id=project, actor="fixture-user",
                             display_name="Synthetic Engineering Fixture", slug=project,
                             export_root=tmp_path)
    principal = Principal(user_id="fixture-user", tenant_id=tenant, role="admin",
                          allowed_project_ids=frozenset({project}))
    return principal, project


def test_intake_is_durable_idempotent_and_only_authorizes_submission(authorized_scope):
    principal, project = authorized_scope
    first = submit_handoff(principal, project, handoff())
    replay = submit_handoff(principal, project, handoff(), due_at=datetime.now(timezone.utc))
    assert first["job_id"] == replay["job_id"]
    assert first["dedupe_key"] == replay["dedupe_key"]
    assert first["spec_hash"] == replay["spec_hash"]
    assert first["state"] == replay["state"] == "SCHEDULED"
    assert first["kind"] == ENGINEERING_HANDOFF_KIND
    job = durable_runs.get_job(first["job_id"])
    assert job is not None
    assert job["tenant_id"] == principal.tenant_id
    assert job["project_id"] == project
    assert job["requested_by"] == principal.user_id
    assert job["state"] == "SCHEDULED"
    assert job["spec"]["authority_gate"] == {
        "state": "UNVERIFIED",
        "authorized_actions": [],
        "reason": "SUBMISSION_AUTHORIZES_INTAKE_ONLY",
    }
    assert job["spec"]["delivery_gate"]["live_github_writes"] is False
    transitions = durable_runs.list_transitions(job["job_id"])
    assert len(transitions) == 1  # The canonical store owns the initial transition.
    assert transitions[0]["from_state"] == "DORMANT"
    assert transitions[0]["to_state"] == "SCHEDULED"


def test_unregistered_worker_kind_fails_closed_without_intent_or_effect(authorized_scope):
    principal, project = authorized_scope
    submitted = submit_handoff(principal, project, handoff())
    report = run_tick(worker_id="fixture-no-handler", handlers={}, job_id=submitted["job_id"])
    assert report.final_state == "BLOCKED_ENVIRONMENT"
    assert "NO_HANDLER_FOR_KIND" in report.reasons[0]
    job = durable_runs.get_job(submitted["job_id"])
    assert job["state"] == "BLOCKED_ENVIRONMENT"
    assert durable_runs.list_intents(submitted["job_id"]) == []


def test_scope_is_server_derived_and_unauthorized_project_is_rejected(authorized_scope):
    principal, project = authorized_scope
    other = Principal(user_id=principal.user_id, tenant_id=principal.tenant_id, role=principal.role,
                      allowed_project_ids=frozenset({"prj-not-authorized"}))
    with pytest.raises(HTTPException) as exc:
        submit_handoff(other, project, handoff())
    assert exc.value.status_code == 403


def test_changed_input_or_requester_does_not_alias_an_existing_dedupe_key(authorized_scope):
    principal, project = authorized_scope
    first = submit_handoff(principal, project, handoff())
    changed = handoff(objective="Different approved objective.")
    second = submit_handoff(principal, project, changed)
    other_user = Principal(user_id="fixture-other-user", tenant_id=principal.tenant_id, role="operator",
                            allowed_project_ids=frozenset({project}))
    third = submit_handoff(other_user, project, handoff())
    assert len({first["job_id"], second["job_id"], third["job_id"]}) == 3
    assert len({first["dedupe_key"], second["dedupe_key"], third["dedupe_key"]}) == 3
