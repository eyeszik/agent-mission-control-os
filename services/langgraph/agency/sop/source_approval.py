"""Native approval evidence for a Brand OS source document (WO-03, Batch 1b).

A source is authenticated only when a person, through the existing
``/approvals/{id}/decide`` route, approved the exact stored bytes of that
source for this purpose. Nothing here is a second approval system:

* the source bytes are an ordinary Project OS artifact (``foundry.studio.store``),
  whose ``content_hash`` is the SHA-256 of those bytes;
* the approval is opened with ``intake.release.open_artifact_approval`` and bound
  to the artifact id, version and content hash;
* verification reuses ``intake.release.artifact_release_verdict`` (scope, status,
  staleness, subject binding, separation of duties) and adds only a purpose check
  and a check that the caller's principal may act in that tenant and project.

The result is evidence, never a token: ``grants_runtime_authority`` is typed
``False`` and nothing here opens, decides, releases or dispatches anything.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.intake.release import artifact_release_verdict, open_artifact_approval
from services.langgraph.security.auth import Principal

SUBJECT_TYPE = "BRAND_OS_SOURCE"
POLICY_VERSION = "amc-brand-os-source/v1"
RUN_PIPELINE = "brand_os_source_intake"


class SourceApprovalEvidence(BaseModel):
    """What the native approval store proves about one source artifact. Documentary only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verified: bool
    reasons: tuple[str, ...]
    tenant_id: str
    project_id: str
    artifact_id: str
    artifact_version: Optional[int]
    artifact_hash: Optional[str]
    approval_id: Optional[str]
    subject_type: Literal["BRAND_OS_SOURCE"] = SUBJECT_TYPE
    policy_version: Literal["amc-brand-os-source/v1"] = POLICY_VERSION
    grants_runtime_authority: Literal[False] = False
    external_effects: Literal["none"] = "none"


def _scope_reasons(principal: Principal, tenant_id: str, project_id: str) -> list[str]:
    reasons = []
    if principal.tenant_id != tenant_id:
        reasons.append("PRINCIPAL_TENANT_MISMATCH")
    if not principal.can_access_project(project_id):
        reasons.append("PRINCIPAL_PROJECT_DENIED")
    return reasons


def source_mission_id(artifact_id: str) -> str:
    return f"brand-os-source:{artifact_id}"


def open_source_approval(principal: Principal, *, tenant_id: str, project_id: str, artifact_id: str, version: int,
                         content_hash: str, sop_id: str) -> dict:
    """Open (or reuse) a pending approval for exactly these source bytes. Never decides it."""
    denied = _scope_reasons(principal, tenant_id, project_id)
    if denied:
        raise PermissionError(f"cannot open a source approval: {denied}")
    return open_artifact_approval(
        principal, tenant_id=tenant_id, project_id=project_id, mission_id=source_mission_id(artifact_id),
        contract_hash=content_hash, artifact_id=artifact_id, version=version, content_hash=content_hash,
        run_pipeline=RUN_PIPELINE, policy_version=POLICY_VERSION, subject_type=SUBJECT_TYPE,
        reason=f"Authenticate Brand OS {sop_id} source: confirm these exact bytes are the original, canonical procedure.",
        metadata={"sop_id": sop_id},
    )


def _purpose_reasons(approval_id: Optional[str]) -> list[str]:
    from services.langgraph.persistence.approvals import get_approval

    approval = get_approval(approval_id) if approval_id else None
    if approval is None:
        return []  # artifact_release_verdict already reports NO_APPROVAL
    if (approval.get("subject_type"), approval.get("policy_version")) != (SUBJECT_TYPE, POLICY_VERSION):
        return ["APPROVAL_PURPOSE_MISMATCH"]
    return []


def verify_source_approval(principal: Principal, *, tenant_id: str, project_id: str, artifact_id: str, version: int,
                           content_hash: str, approval_id: Optional[str]) -> SourceApprovalEvidence:
    """Fail closed unless a separate approver approved these exact, still-current source bytes for this purpose.

    ``content_hash`` is the digest the caller computed from the source bytes it is about to rely on;
    if the stored head no longer has those bytes the verdict reports VERIFICATION_STALE.
    """
    reasons = _scope_reasons(principal, tenant_id, project_id)
    verdict = artifact_release_verdict(
        simulated=False, verification_passed=True, artifact_id=artifact_id, verified_version=version,
        verified_hash=content_hash, approval_id=approval_id, tenant_id=tenant_id, project_id=project_id,
    )
    reasons += [r for r in verdict.reasons if r not in reasons]
    reasons += [r for r in _purpose_reasons(approval_id) if r not in reasons]
    return SourceApprovalEvidence(
        verified=not reasons, reasons=tuple(reasons), tenant_id=tenant_id, project_id=project_id,
        artifact_id=artifact_id, artifact_version=verdict.artifact_version, artifact_hash=verdict.artifact_hash,
        approval_id=verdict.approval_id,
    )


__all__ = [
    "POLICY_VERSION",
    "RUN_PIPELINE",
    "SUBJECT_TYPE",
    "SourceApprovalEvidence",
    "open_source_approval",
    "source_mission_id",
    "verify_source_approval",
]
