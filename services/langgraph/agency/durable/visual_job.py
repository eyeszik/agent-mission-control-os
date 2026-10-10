"""Durable job kind ``visual_render``: the local visual engine driven by the run FSM.

The job spec is written server-side by :func:`submit_visual_job` from a
server-derived principal; nothing in it is client authority. Each tick
rechecks project access and capability before dispatch, records the target
artifact's pre-image, and after an interruption adopts a render that was
persisted after that pre-image instead of rendering again.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.visual.capabilities import probe_all
from services.langgraph.agency.visual.contracts import CapabilityStatus, VisualIntent
from services.langgraph.agency.visual.router import route
from services.langgraph.security.auth import Principal

from .fsm import RunState

KIND = "visual_render"
CONTRACT_VERSION = "amc-visual-render/v1"
_BLOCK_STATE = {
    CapabilityStatus.BLOCKED_LOCAL_MODEL: RunState.BLOCKED_PROVIDER,
    CapabilityStatus.MISSING_DEPENDENCIES: RunState.BLOCKED_ENVIRONMENT,
    CapabilityStatus.BLOCKED_ENVIRONMENT: RunState.BLOCKED_ENVIRONMENT,
}


def _principal(job: dict) -> Principal:
    p = job["spec"]["principal"]
    return Principal(user_id=p["user_id"], tenant_id=p["tenant_id"], role=p["role"],
                     allowed_project_ids=frozenset(p["allowed_project_ids"]))


def _intent(job: dict) -> VisualIntent:
    return VisualIntent.model_validate(job["spec"]["intent"])


def _export_root(job: dict) -> Path:
    return Path(job["spec"].get("export_root") or os.environ.get("AMC_EXPORT_ROOT") or "exports")


def submit_visual_job(principal: Principal, project_id: str, intent: VisualIntent, *, artifact_key: str, mission_id: str,
                      export_root: Optional[Path] = None, due_at: Optional[datetime] = None,
                      requires_approval: bool = True, recurrence_seconds: Optional[int] = None) -> dict:
    from services.langgraph.persistence.durable_runs import create_job
    from services.langgraph.persistence.projects import require_project_workspace

    if not principal.can_access_project(project_id):
        raise PermissionError("principal cannot access this project")
    workspace = require_project_workspace(project_id)
    if workspace.tenant_id != principal.tenant_id:
        raise PermissionError("project belongs to another tenant")
    spec = {
        "mission_id": mission_id, "artifact_key": artifact_key, "intent": intent.model_dump(mode="json"),
        "requires_approval": requires_approval, "export_root": str(export_root) if export_root else None,
        "principal": {"user_id": principal.user_id, "tenant_id": principal.tenant_id, "role": principal.role,
                      "allowed_project_ids": sorted(principal.allowed_project_ids)},
    }
    job_id = "djob-" + canonical_hash({"project": project_id, "mission": mission_id, "key": artifact_key})[:28]
    return create_job(tenant_id=principal.tenant_id, project_id=project_id, kind=KIND, spec=spec,
                      spec_hash=canonical_hash(spec), requested_by=principal.user_id,
                      due_at=due_at or datetime.now(timezone.utc), recurrence_seconds=recurrence_seconds, job_id=job_id)


class VisualRenderHandler:
    operation = "visual.render"
    contract_version = CONTRACT_VERSION
    retry_class = "RETRY_SAFE"  # a local render has no external effect; re-running it is safe

    def target(self, job: dict) -> str:
        from services.langgraph.persistence.projects import project_artifact_id

        return project_artifact_id(job["project_id"], job["spec"]["artifact_key"])

    def input_hash(self, job: dict) -> str:
        return canonical_hash(job["spec"]["intent"])

    def environment_fingerprint(self, job: dict) -> str:
        caps = probe_all()
        return canonical_hash({r.value: [c.status.value, c.version] for r, c in sorted(caps.items(), key=lambda kv: kv[0].value)})[:16]

    def precheck(self, job: dict) -> tuple[Optional[RunState], list[str]]:
        from services.langgraph.persistence.projects import get_project_workspace

        workspace = get_project_workspace(job["project_id"])
        if workspace is None or workspace.tenant_id != job["tenant_id"]:
            return RunState.BLOCKED_AUTHORITY, ["PROJECT_NOT_AVAILABLE"]
        if workspace.lifecycle_state.value == "ARCHIVED":
            return RunState.BLOCKED_AUTHORITY, ["PROJECT_ARCHIVED"]
        if not _principal(job).can_access_project(job["project_id"]):
            return RunState.BLOCKED_AUTHORITY, ["PRINCIPAL_LOST_PROJECT_ACCESS"]
        if int(job["attempts"]) >= int(job["max_attempts"]):
            return RunState.BLOCKED_ENVIRONMENT, ["ATTEMPT_BUDGET_EXHAUSTED"]
        caps = probe_all()
        decision = route(_intent(job), caps)
        if decision.status == "BLOCKED":
            first = next((c for r, c in caps.items() if any(reason.startswith(r.value) for reason in decision.reasons)), None)
            if any(r.startswith("RIGHTS_UNVERIFIED") for r in decision.reasons):
                return RunState.BLOCKED_AUTHORITY, list(decision.reasons)
            state = _BLOCK_STATE.get(first.status, RunState.BLOCKED_ENVIRONMENT) if first else RunState.BLOCKED_ENVIRONMENT
            return state, list(decision.reasons)
        return None, []

    def pre_image(self, job: dict) -> dict:
        from services.langgraph.persistence.agency_kernel import get_artifact

        head = get_artifact(self.target(job))
        return {"artifact_id": self.target(job), "version": int(head["version"]) if head else 0,
                "content_hash": head.get("content_hash") if head else None}

    def dispatch(self, job: dict) -> dict:
        from services.langgraph.agency.visual.engine import produce

        result = produce(_principal(job), job["project_id"], _intent(job), work_dir=_export_root(job) / ".render-work",
                         artifact_key=job["spec"]["artifact_key"], export_root=_export_root(job),
                         logical_tick=int(job["logical_tick"]) + 1)
        if result.status == "BLOCKED":
            return {"blocked_state": RunState.BLOCKED_ENVIRONMENT.value, "reasons": list(result.reasons)}
        if result.status == "FAILED" and result.artifact_id is None:
            return {"failed": True, "reasons": list(result.reasons)}
        receipt = result.receipts[-1] if result.receipts else None
        return {"artifact_id": result.artifact_id, "version": result.version, "content_hash": result.content_hash,
                "mime_type": result.mime_type, "route": result.decision.route.value if result.decision.route else None,
                "wall_ms": sum((r.wall_ms or 0) for r in result.receipts),
                "network_isolated": all(r.network_isolated for r in result.receipts),
                "receipts": [r.model_dump(mode="json") for r in result.receipts],
                "renderer": receipt.genome.renderer if receipt and receipt.genome else None}

    def observe(self, job: dict, dispatched: dict) -> dict:
        """Independent read-back of the persisted head, not of the renderer's report."""
        from services.langgraph.agency.project_os.storage import LocalStorageAdapter
        from services.langgraph.agency.visual.engine import readback_verify

        verification = readback_verify(dispatched["artifact_id"], intent=_intent(job), adapter=LocalStorageAdapter(_export_root(job)))
        return {**{k: v for k, v in dispatched.items() if k != "receipts"}, "receipts": dispatched.get("receipts", []),
                "content_hash": verification.content_hash, "version": verification.version,
                "verification": verification.model_dump(mode="json")}

    def verify(self, job: dict, observation: dict) -> dict:
        v = observation["verification"]
        return {"status": v["status"], "findings": v["findings"], "highest_passed": v["highest_passed"],
                "human_required": v["human_required"]}

    def reconcile(self, job: dict, intent: dict) -> tuple[str, Optional[dict]]:
        from services.langgraph.agency.project_os.storage import LocalStorageAdapter
        from services.langgraph.agency.visual.engine import readback_verify
        from services.langgraph.persistence.agency_kernel import get_artifact

        pre = intent.get("pre_image") or {}
        head = get_artifact(self.target(job))
        if head is None or int(head["version"]) <= int(pre.get("version") or 0):
            return "REDO", None  # nothing was persisted after the pre-image
        verification = readback_verify(self.target(job), intent=_intent(job), adapter=LocalStorageAdapter(_export_root(job)))
        return "ADOPT", {"artifact_id": self.target(job), "version": verification.version,
                         "content_hash": verification.content_hash, "route": None, "wall_ms": None, "receipts": [],
                         "verification": verification.model_dump(mode="json"), "adopted_after_interruption": True}

    def on_commit(self, job: dict, observation: dict, verification: dict) -> tuple[RunState, dict]:
        from services.langgraph.agency.intake.release import open_artifact_approval

        extra = {"artifact_id": observation["artifact_id"], "version": observation["version"],
                 "content_hash": observation["content_hash"], "verification_status": verification["status"]}
        if job["spec"].get("requires_approval"):
            approval = open_artifact_approval(
                _principal(job), tenant_id=job["tenant_id"], project_id=job["project_id"], mission_id=job["spec"]["mission_id"],
                contract_hash=job["spec_hash"], artifact_id=observation["artifact_id"], version=int(observation["version"]),
                content_hash=observation["content_hash"], run_pipeline="visual_production",
                policy_version="amc-visual-approval/v1", subject_type="VISUAL_ARTIFACT",
                reason="Locally rendered media requires human visual, brand and realism review before release",
                metadata={"route": observation.get("route"), "durable_job": job["job_id"]},
            )
            return RunState.WAITING_APPROVAL, {**extra, "approval_id": approval["approval_id"]}
        return (RunState.SCHEDULED if job.get("recurrence_seconds") else RunState.DORMANT), extra


def settle_waiting_approval(job_id: str, *, now: Optional[datetime] = None) -> dict:
    """Move a WAITING_APPROVAL job on once its approval is decided; a pending approval leaves it waiting.

    No worker holds a lease in WAITING_APPROVAL, so the job's current fencing token is used; a
    concurrent claim would bump it and make this transition raise StaleFence.
    """
    from services.langgraph.persistence.approvals import get_approval
    from services.langgraph.persistence.durable_runs import get_job, transition

    job = get_job(job_id)
    if job is None or job["state"] != RunState.WAITING_APPROVAL.value:
        return {"job_id": job_id, "settled": False, "reason": "NOT_WAITING_APPROVAL"}
    approval = get_approval((job.get("result") or {}).get("approval_id") or "")
    status = (approval or {}).get("status")
    if status not in {"resolved", "stale"}:
        return {"job_id": job_id, "settled": False, "reason": f"APPROVAL_{(status or 'MISSING').upper()}"}
    outcome = (approval or {}).get("decision") if status == "resolved" else "stale"
    to = RunState.SCHEDULED if job.get("recurrence_seconds") else RunState.DORMANT
    moment = now or datetime.now(timezone.utc)
    updated = transition(job, to, fencing_token=int(job["lease_token"]), now=moment, reason=f"approval {outcome}")
    return {"job_id": job_id, "settled": True, "approval_outcome": outcome, "state": updated["state"]}


HANDLERS = {KIND: VisualRenderHandler()}


__all__ = ["CONTRACT_VERSION", "HANDLERS", "KIND", "VisualRenderHandler", "settle_waiting_approval", "submit_visual_job"]
