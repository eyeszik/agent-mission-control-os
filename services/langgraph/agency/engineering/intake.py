"""Authorized, idempotent engineering handoff admission through AMC durable runs.

This module adds no table, scheduler, worker, or state writer. It scopes the
caller with the existing Principal, then delegates the durable row and its
initial FSM transition to ``persistence.durable_runs.create_job``. Intake does
not authorize requested execution or any external write.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.langgraph.agency.durable.fsm import RunState
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence import durable_runs
from services.langgraph.security.auth import Principal, authorize_project

from .contracts import CONTRACT_VERSION, HandoffRequest

ENGINEERING_HANDOFF_KIND = "engineering_handoff_intake"
INTAKE_POLICY_VERSION = "amc-engineering-intake/v1"


def submit_handoff(principal: Principal, project_id: str, handoff: HandoffRequest, *,
                   due_at: datetime | None = None) -> dict:
    """Persist one authorized-to-submit request; requested actions remain unapproved.

    Repeated submissions by the same authenticated user in the same tenant and
    project with identical canonical handoff bytes return the existing durable
    job. Tenant/project/user are server-derived and included in the key. A
    retry with changed source/brief/budget/action input becomes a new intake.
    """
    authorize_project(principal, project_id)
    handoff = HandoffRequest.model_validate(handoff)
    moment = due_at or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("due_at must be timezone-aware")
    handoff_payload = handoff.model_dump(mode="json")
    scope = {
        "tenant_id": principal.tenant_id,
        "project_id": project_id,
        "requested_by": principal.user_id,
    }
    handoff_hash = canonical_hash(handoff_payload)
    dedupe_key = canonical_hash({
        "contract_version": CONTRACT_VERSION,
        "scope": scope,
        "handoff_hash": handoff_hash,
    })
    job_id = "eng-" + dedupe_key[:48]
    spec = {
        "contract_version": CONTRACT_VERSION,
        "intake_policy_version": INTAKE_POLICY_VERSION,
        "handoff": handoff_payload,
        "scope": scope,
        "dedupe_key": dedupe_key,
        "handoff_hash": handoff_hash,
        "authority_gate": {
            "state": "UNVERIFIED",
            "authorized_actions": [],
            "reason": "SUBMISSION_AUTHORIZES_INTAKE_ONLY",
        },
        "delivery_gate": {
            "live_github_writes": False,
            "draft_pr_requires_separate_approval": True,
        },
    }
    spec_hash = canonical_hash(spec)
    job = durable_runs.create_job(
        tenant_id=principal.tenant_id,
        project_id=project_id,
        kind=ENGINEERING_HANDOFF_KIND,
        spec=spec,
        spec_hash=spec_hash,
        requested_by=principal.user_id,
        due_at=moment,
        job_id=job_id,
    )
    return {
        "job_id": job["job_id"],
        "kind": job["kind"],
        "state": RunState(job["state"]).value,
        "version": int(job["version"]),
        "tenant_id": job["tenant_id"],
        "project_id": job["project_id"],
        "requested_by": job["requested_by"],
        "spec_hash": job["spec_hash"],
        "dedupe_key": dedupe_key,
        "created_at": job["created_at"],
    }


__all__ = ["ENGINEERING_HANDOFF_KIND", "INTAKE_POLICY_VERSION", "submit_handoff"]
