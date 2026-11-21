"""Native approval evidence for Brand OS procedure sources (WO-03, Batch 1b).

Two purposes, never interchangeable:

* ``BRAND_OS_SOURCE``: a person confirms the stored bytes are an *original*, canonical
  procedure. A newly written draft can never be opened for this purpose.
* ``BRAND_OS_SOP_ADOPTION``: a person adopts a *newly written* draft (origin
  ``NEWLY_AUTHORED_SOP``) as the canonical Brand OS 4.0 procedure for a project.

Nothing here is a second approval system:

* the bytes are an ordinary Project OS artifact (``foundry.studio.store``) whose
  ``content_hash`` is the SHA-256 of those bytes;
* the approval is opened with ``intake.release.open_artifact_approval`` and bound to the
  artifact id, version and content hash, and decided only on ``/approvals/{id}/decide``;
* verification reuses ``intake.release.artifact_release_verdict`` (scope, status, staleness,
  subject binding, separation of duties) plus a purpose check and a principal scope check.

The result is evidence, never a token: ``grants_runtime_authority`` is typed ``False`` and
nothing here decides, releases or dispatches anything.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.intake.release import artifact_release_verdict, open_artifact_approval
from services.langgraph.security.auth import Principal

SUBJECT_TYPE = "BRAND_OS_SOURCE"
POLICY_VERSION = "amc-brand-os-source/v1"
ADOPTION_SUBJECT_TYPE = "BRAND_OS_SOP_ADOPTION"
ADOPTION_POLICY_VERSION = "amc-brand-os-sop-adoption/v1"
RUN_PIPELINE = "brand_os_source_intake"
SOP_ARTIFACT_TYPE = "knowledge_capsule"
SOP_PRODUCER_ROLE = "market_researcher"
SOP_SUBTYPE = "brand_os.sop"
_PURPOSES = {SUBJECT_TYPE: POLICY_VERSION, ADOPTION_SUBJECT_TYPE: ADOPTION_POLICY_VERSION}


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
    subject_type: Literal["BRAND_OS_SOURCE", "BRAND_OS_SOP_ADOPTION"] = SUBJECT_TYPE
    policy_version: Literal["amc-brand-os-source/v1", "amc-brand-os-sop-adoption/v1"] = POLICY_VERSION
    grants_runtime_authority: Literal[False] = False
    external_effects: Literal["none"] = "none"


def _scope_reasons(principal: Principal, tenant_id: str, project_id: str) -> list[str]:
    reasons = []
    if principal.tenant_id != tenant_id:
        reasons.append("PRINCIPAL_TENANT_MISMATCH")
    if not principal.can_access_project(project_id):
        reasons.append("PRINCIPAL_PROJECT_DENIED")
    return reasons


def source_mission_id(artifact_id: str, subject_type: str = SUBJECT_TYPE) -> str:
    return f"brand-os-source:{artifact_id}" if subject_type == SUBJECT_TYPE else f"brand-os-adoption:{artifact_id}"


def _open(principal: Principal, *, subject_type: str, tenant_id: str, project_id: str, artifact_id: str, version: int,
          content_hash: str, sop_id: str, reason: str) -> dict:
    denied = _scope_reasons(principal, tenant_id, project_id)
    if denied:
        raise PermissionError(f"cannot open a Brand OS approval: {denied}")
    return open_artifact_approval(
        principal, tenant_id=tenant_id, project_id=project_id, mission_id=source_mission_id(artifact_id, subject_type),
        contract_hash=content_hash, artifact_id=artifact_id, version=version, content_hash=content_hash,
        run_pipeline=RUN_PIPELINE, policy_version=_PURPOSES[subject_type], subject_type=subject_type,
        reason=reason, metadata={"sop_id": sop_id},
    )


def open_source_approval(principal: Principal, *, tenant_id: str, project_id: str, artifact_id: str, version: int,
                         content_hash: str, sop_id: str) -> dict:
    """Open (or reuse) a pending approval asking whether these bytes are the original procedure. Never decides it."""
    from services.langgraph.agency.sop.brand_os_source import load_index

    if load_index().entry(sop_id).procedure_status == "NEWLY_AUTHORED_DRAFT":
        raise ValueError(f"{sop_id} is a newly written draft; it can be adopted, never authenticated as an original")
    return _open(principal, subject_type=SUBJECT_TYPE, tenant_id=tenant_id, project_id=project_id,
                 artifact_id=artifact_id, version=version, content_hash=content_hash, sop_id=sop_id,
                 reason=f"Authenticate Brand OS {sop_id} source: confirm these exact bytes are the original, canonical procedure.")


def stage_sop_for_adoption(principal: Principal, *, project_id: str, sop_id: str, adapter) -> dict:
    """Store a newly written draft's exact bytes in the project and open its adoption approval.

    The bytes must still match the digest pinned in the index. Returns the stored artifact head and the
    pending approval; a separate approver decides it on ``/approvals/{id}/decide``.
    """
    from services.langgraph.agency.foundry.studio import store
    from services.langgraph.agency.kernel import assert_role_may_produce
    from services.langgraph.agency.sop.brand_os_source import load_index, verified_draft_bytes

    entry = load_index().entry(sop_id)
    if entry.procedure_status != "NEWLY_AUTHORED_DRAFT":
        raise LookupError(f"{sop_id} has no newly written draft to adopt")
    if _scope_reasons(principal, principal.tenant_id, project_id):
        raise PermissionError(f"principal may not act in project {project_id}")
    data = verified_draft_bytes(entry)
    assert_role_may_produce(SOP_PRODUCER_ROLE, SOP_ARTIFACT_TYPE)
    head = store(principal, project_id, f"brand-os-{sop_id.lower()}", data, mime="text/markdown",
                 artifact_type=SOP_ARTIFACT_TYPE, subtype=SOP_SUBTYPE, adapter=adapter,
                 v2={"brand_os_sop_id": sop_id, "origin": "NEWLY_AUTHORED_SOP", "draft_version": entry.procedure_source.version})
    approval = _open(principal, subject_type=ADOPTION_SUBJECT_TYPE, tenant_id=principal.tenant_id, project_id=project_id,
                     artifact_id=head["artifact_id"], version=head["version"], content_hash=head["content_hash"], sop_id=sop_id,
                     reason=f"Adopt Brand OS {sop_id} ({entry.name}) as this project's canonical procedure. "
                            "This is a newly written draft, not a recovered original.")
    return {"artifact": head, "approval": approval}


def _purpose_reasons(approval_id: Optional[str], subject_type: str) -> list[str]:
    from services.langgraph.persistence.approvals import get_approval

    approval = get_approval(approval_id) if approval_id else None
    if approval is None:
        return []  # artifact_release_verdict already reports NO_APPROVAL
    if (approval.get("subject_type"), approval.get("policy_version")) != (subject_type, _PURPOSES[subject_type]):
        return ["APPROVAL_PURPOSE_MISMATCH"]
    return []


def _verify(principal: Principal, subject_type: str, *, tenant_id: str, project_id: str, artifact_id: str, version: int,
            content_hash: str, approval_id: Optional[str]) -> SourceApprovalEvidence:
    reasons = _scope_reasons(principal, tenant_id, project_id)
    verdict = artifact_release_verdict(
        simulated=False, verification_passed=True, artifact_id=artifact_id, verified_version=version,
        verified_hash=content_hash, approval_id=approval_id, tenant_id=tenant_id, project_id=project_id,
    )
    reasons += [r for r in verdict.reasons if r not in reasons]
    reasons += [r for r in _purpose_reasons(approval_id, subject_type) if r not in reasons]
    return SourceApprovalEvidence(
        verified=not reasons, reasons=tuple(reasons), tenant_id=tenant_id, project_id=project_id,
        artifact_id=artifact_id, artifact_version=verdict.artifact_version, artifact_hash=verdict.artifact_hash,
        approval_id=verdict.approval_id, subject_type=subject_type, policy_version=_PURPOSES[subject_type],
    )


def verify_source_approval(principal: Principal, *, tenant_id: str, project_id: str, artifact_id: str, version: int,
                           content_hash: str, approval_id: Optional[str]) -> SourceApprovalEvidence:
    """Fail closed unless a separate approver confirmed these exact, still-current bytes are the original."""
    return _verify(principal, SUBJECT_TYPE, tenant_id=tenant_id, project_id=project_id, artifact_id=artifact_id,
                   version=version, content_hash=content_hash, approval_id=approval_id)


def verify_sop_adoption(principal: Principal, *, tenant_id: str, project_id: str, artifact_id: str, version: int,
                        content_hash: str, approval_id: Optional[str]) -> SourceApprovalEvidence:
    """Fail closed unless a separate approver adopted these exact, still-current draft bytes for this project."""
    return _verify(principal, ADOPTION_SUBJECT_TYPE, tenant_id=tenant_id, project_id=project_id,
                   artifact_id=artifact_id, version=version, content_hash=content_hash, approval_id=approval_id)


__all__ = [
    "ADOPTION_POLICY_VERSION",
    "ADOPTION_SUBJECT_TYPE",
    "POLICY_VERSION",
    "RUN_PIPELINE",
    "SUBJECT_TYPE",
    "SourceApprovalEvidence",
    "open_source_approval",
    "source_mission_id",
    "stage_sop_for_adoption",
    "verify_source_approval",
    "verify_sop_adoption",
]
