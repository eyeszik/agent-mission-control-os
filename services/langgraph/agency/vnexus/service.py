"""VNEXUS brand genome service: authorization, lifecycle and approval binding.

Every entry point takes the server-derived ``Principal``. The project that
authorizes a write is derived from the scope (a brand scope is authorized by
the brand's owner project), and that project's *recorded* tenant must be the
principal's. Client input never names a tenant or an approver.

Approval reuses the existing machinery: submitting a version opens an approval
bound to the version's content hash through ``open_artifact_approval``, a human
decides it on ``/approvals/{id}/decide`` (approver role, separation of duties),
and ``settle_version`` applies the decision. An approval whose hash no longer
matches, or that was decided by the version's author or submitter, is never
applied.
"""

from __future__ import annotations

from typing import Any, Optional

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence import vnexus as db
from services.langgraph.security.auth import Principal

from .genome import (
    ConflictReason,
    GenomeDocument,
    GenomeLayer,
    Resolution,
    Scope,
    Severity,
    VersionStatus,
    ancestor_refs,
    diff_documents,
    next_status,
    resolve,
    scope_ref_project,
    self_check,
)

READ_ONLY_ROLES = frozenset({"viewer", "read_only", "readonly", "guest", "auditor"})
APPROVAL_POLICY = "amc-vnexus-genome/v1"
SUBJECT_GENOME = "VNEXUS_GENOME_VERSION"


class GenomeIntegrityError(RuntimeError):
    """A stored document no longer hashes to its recorded content hash."""


class GenomeBlocked(ValueError):
    """The version cannot move forward: blocking conflicts or findings against approved ancestors."""

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


# --------------------------------------------------------------------------- authorization


def _project_tenant(project_id: str) -> str:
    from services.langgraph.persistence.projects import ProjectNotFoundError, get_project_workspace

    workspace = get_project_workspace(project_id)
    if workspace is None:
        raise ProjectNotFoundError(f"project {project_id} not found")
    return workspace.tenant_id


def authorize(principal: Principal, project_id: str, *, write: bool = False) -> None:
    if _project_tenant(project_id) != principal.tenant_id:
        raise PermissionError("resource belongs to a different tenant")
    if not principal.can_access_project(project_id):
        raise PermissionError("principal may not access this project")
    if write and principal.role.strip().lower() in READ_ONLY_ROLES:
        raise PermissionError(f"role {principal.role!r} is read-only")


def brand_for(principal: Principal, brand_id: str) -> dict:
    brand = db.get_brand(brand_id)
    if brand is None or brand["tenant_id"] != principal.tenant_id:
        # Same answer for "absent" and "another tenant's" so ids cannot be probed.
        raise db.VnexusNotFound(f"brand {brand_id} not found")
    return brand


def scope_project(brand: dict, scope: Scope, scope_ref: str) -> str:
    if scope is Scope.BRAND and scope_ref != brand["brand_id"]:
        raise ValueError("a brand scope_ref is the brand id")
    return scope_ref_project(scope, scope_ref, brand_owner_project=brand["owner_project_id"])


# --------------------------------------------------------------------------- brands


def create_brand(principal: Principal, *, brand_id: str, display_name: str, owner_project_id: str) -> dict:
    authorize(principal, owner_project_id, write=True)
    return db.create_brand(tenant_id=principal.tenant_id, brand_id=brand_id, owner_project_id=owner_project_id,
                           display_name=display_name, actor=principal.user_id)


def list_brands(principal: Principal) -> list[dict]:
    return [b for b in db.list_brands(principal.tenant_id) if principal.can_access_project(b["owner_project_id"])
            or "*" in principal.allowed_project_ids]


# --------------------------------------------------------------------------- versions


def _document(row: dict) -> GenomeDocument:
    doc = GenomeDocument.model_validate(row["document"])
    if doc.content_hash != row["content_hash"]:
        raise GenomeIntegrityError(f"genome version {row['version_id']} does not match its recorded hash")
    return doc


def get_version(principal: Principal, version_id: str, *, settle: bool = True) -> dict:
    row = db.get_version(version_id)
    if row is None or row["tenant_id"] != principal.tenant_id:
        raise db.VnexusNotFound(f"genome version {version_id} not found")
    authorize(principal, row["project_id"])
    _document(row)
    if settle and row["status"] == VersionStatus.IN_REVIEW.value and row.get("approval_id"):
        row = settle_version(principal, version_id)
    return row


def list_versions(principal: Principal, brand_id: str, *, scope: Optional[Scope] = None, scope_ref: Optional[str] = None) -> list[dict]:
    brand = brand_for(principal, brand_id)
    rows = db.list_versions(brand["brand_id"], scope=scope.value if scope else None, scope_ref=scope_ref)
    return [r for r in rows if principal.can_access_project(r["project_id"])]


def create_draft(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str, document: GenomeDocument,
                 experimental: bool = False) -> dict:
    brand = brand_for(principal, brand_id)
    project_id = scope_project(brand, scope, scope_ref)
    authorize(principal, project_id, write=True)
    approved = db.approved_version(brand_id, scope.value, scope_ref)
    return db.create_version(tenant_id=principal.tenant_id, brand_id=brand_id, scope=scope.value, scope_ref=scope_ref,
                             project_id=project_id, document=document.model_dump(mode="json"), content_hash=document.content_hash,
                             actor=principal.user_id, status="EXPERIMENTAL" if experimental else "DRAFT",
                             parent_version_id=approved["version_id"] if approved else None)


def edit_draft(principal: Principal, version_id: str, *, expected_revision: int, document: GenomeDocument) -> dict:
    row = get_version(principal, version_id, settle=False)
    authorize(principal, row["project_id"], write=True)
    return db.update_version_document(version_id, expected_revision=expected_revision, document=document.model_dump(mode="json"),
                                      content_hash=document.content_hash, actor=principal.user_id)


def revert_to(principal: Principal, version_id: str) -> dict:
    """A revert is a new draft carrying an older version's document; history is never rewritten."""
    target = get_version(principal, version_id, settle=False)
    authorize(principal, target["project_id"], write=True)
    if target["status"] not in (VersionStatus.APPROVED.value, VersionStatus.SUPERSEDED.value):
        raise ValueError("only an approved or superseded version can be reverted to")
    doc = _document(target)
    current = db.approved_version(target["brand_id"], target["scope"], target["scope_ref"])
    return db.create_version(tenant_id=target["tenant_id"], brand_id=target["brand_id"], scope=target["scope"],
                             scope_ref=target["scope_ref"], project_id=target["project_id"], document=doc.model_dump(mode="json"),
                             content_hash=doc.content_hash, actor=principal.user_id, origin="REVERT", origin_ref=version_id,
                             parent_version_id=current["version_id"] if current else None)


# --------------------------------------------------------------------------- resolution


def layers_for(brand_id: str, scope: Scope, scope_ref: str, *, preview: Optional[dict] = None) -> list[GenomeLayer]:
    layers: list[GenomeLayer] = []
    for s, ref in ancestor_refs(scope, scope_ref, brand_id):
        row = preview if preview is not None and (s.value, ref) == (preview["scope"], preview["scope_ref"]) else \
            db.approved_version(brand_id, s.value, ref)
        if row is not None:
            layers.append(GenomeLayer(scope=s, scope_ref=ref, status=VersionStatus(row["status"]), document=_document(row),
                                      version_id=row["version_id"], version=row["version"]))
    return layers


def resolve_scope(principal: Principal, brand_id: str, *, scope: Scope, scope_ref: str,
                  preview_version_id: Optional[str] = None) -> tuple[Resolution, list[GenomeLayer]]:
    brand = brand_for(principal, brand_id)
    authorize(principal, scope_project(brand, scope, scope_ref))
    preview = None
    if preview_version_id:
        preview = get_version(principal, preview_version_id, settle=False)
        if preview["brand_id"] != brand_id or (preview["scope"], preview["scope_ref"]) != (scope.value, scope_ref):
            raise ValueError("the preview version belongs to a different scope")
    layers = layers_for(brand_id, scope, scope_ref, preview=preview)
    return resolve(layers, preview_ref=scope_ref if preview else None), layers


def readiness(row: dict) -> dict:
    """What would block this version if it were approved now, judged against its approved ancestors."""
    doc = _document(row)
    scope = Scope(row["scope"])
    layers = layers_for(row["brand_id"], scope, row["scope_ref"], preview=row)
    resolution = resolve(layers, preview_ref=row["scope_ref"])
    own = [c for c in resolution.conflicts if c.scope_ref == row["scope_ref"] and c.reason is not ConflictReason.UNAPPROVED_OVERRIDE]
    blocking_findings = [f for f in resolution.findings if not f.passed and f.severity is Severity.BLOCKING]
    self_findings = [f for f in self_check(doc) if f.severity in (Severity.BLOCKING, Severity.ERROR)]
    report = {"version_id": row["version_id"], "content_hash": doc.content_hash, "resolution_hash": resolution.resolution_hash,
              "conflicts": [c.model_dump(mode="json") for c in own],
              "blocking_findings": [f.model_dump(mode="json") for f in blocking_findings],
              "self_findings": [f.model_dump(mode="json") for f in self_findings]}
    report["ready"] = not (own or blocking_findings or self_findings)
    return report


# --------------------------------------------------------------------------- lifecycle and approval


def submit_version(principal: Principal, version_id: str) -> dict:
    row = get_version(principal, version_id, settle=False)
    authorize(principal, row["project_id"], write=True)
    next_status(VersionStatus(row["status"]), "submit")
    report = readiness(row)
    if not report["ready"]:
        raise GenomeBlocked("version has blocking conflicts or findings against its approved ancestors", report)
    from services.langgraph.agency.intake.release import open_artifact_approval

    approval = open_artifact_approval(
        principal, tenant_id=row["tenant_id"], project_id=row["project_id"], mission_id=f"vnexus-genome:{version_id}",
        contract_hash=canonical_hash({"policy": APPROVAL_POLICY, "scope": row["scope"], "scope_ref": row["scope_ref"]}),
        artifact_id=version_id, version=int(row["version"]), content_hash=row["content_hash"], run_pipeline="vnexus.genome",
        policy_version=APPROVAL_POLICY, subject_type=SUBJECT_GENOME,
        reason=f"Approve brand genome {row['brand_id']} {row['scope']}:{row['scope_ref']} v{row['version']}",
        metadata={"brand_id": row["brand_id"], "scope": row["scope"], "scope_ref": row["scope_ref"]},
    )
    stamp = db.now_iso()
    return db.transition_version(version_id, from_status="DRAFT", to_status="IN_REVIEW", actor=principal.user_id, action="submit",
                                 detail={"approval_id": approval["approval_id"], "readiness": report["resolution_hash"]},
                                 submitted_by=principal.user_id, submitted_at=stamp, approval_id=approval["approval_id"])


def withdraw_version(principal: Principal, version_id: str) -> dict:
    row = get_version(principal, version_id, settle=False)
    authorize(principal, row["project_id"], write=True)
    if principal.user_id not in (row["created_by"], row.get("submitted_by")):
        raise PermissionError("only the author or submitter can withdraw a version from review")
    next_status(VersionStatus(row["status"]), "withdraw")
    from services.langgraph.persistence.approvals import get_approval, mark_approval_stale

    approval = get_approval(row["approval_id"]) if row.get("approval_id") else None
    if approval and approval.get("status") == "resolved":
        raise db.VnexusConflict("the approval was already decided; settle the version instead")
    if approval and approval.get("status") == "pending":
        mark_approval_stale(approval["approval_id"], "withdrawn by submitter")
    return db.transition_version(version_id, from_status="IN_REVIEW", to_status="DRAFT", actor=principal.user_id,
                                 action="withdraw", detail={"approval_id": row.get("approval_id")})


def settle_version(principal: Principal, version_id: str) -> dict:
    """Apply a decided approval to an IN_REVIEW version. Undecided approvals leave it in review."""
    row = db.get_version(version_id)
    if row is None or row["tenant_id"] != principal.tenant_id:
        raise db.VnexusNotFound(f"genome version {version_id} not found")
    authorize(principal, row["project_id"])
    if row["status"] != VersionStatus.IN_REVIEW.value or not row.get("approval_id"):
        return row
    from services.langgraph.persistence.approvals import get_approval
    from services.langgraph.security.approval_authority import self_approval_allowed

    approval = get_approval(row["approval_id"])
    if approval is None or approval.get("status") != "resolved":
        return row
    if approval.get("subject_hash") != row["content_hash"] or approval.get("subject_ref") != version_id:
        return db.transition_version(version_id, from_status="IN_REVIEW", to_status="DRAFT", actor="system", action="refuse",
                                     detail={"reason": "approval is not bound to this content", "approval_id": approval["approval_id"]})
    reviewer = approval.get("reviewer")
    if approval.get("decision") == "approve" and reviewer in {row["created_by"], row.get("submitted_by")} and not self_approval_allowed():
        return db.transition_version(version_id, from_status="IN_REVIEW", to_status="DRAFT", actor="system", action="refuse",
                                     detail={"reason": "separation of duties: the reviewer authored or submitted this version",
                                             "approval_id": approval["approval_id"]})
    _document(row)
    action = "approve" if approval.get("decision") == "approve" else "reject"
    target = next_status(VersionStatus.IN_REVIEW, action)
    if action == "approve":
        report = readiness(row)
        if not report["ready"]:
            # An ancestor changed while this version was in review; it can no longer be approved as is.
            return db.transition_version(version_id, from_status="IN_REVIEW", to_status="DRAFT", actor="system", action="refuse",
                                         detail={"reason": "ancestor genome changed during review", "readiness": report})
    return db.transition_version(version_id, from_status="IN_REVIEW", to_status=target.value, actor=reviewer or "unknown",
                                 action=action, detail={"approval_id": approval["approval_id"]},
                                 decided_by=reviewer, decided_at=approval.get("decided_at") or db.now_iso())


def compare_versions(principal: Principal, a_id: str, b_id: str) -> dict:
    a, b = get_version(principal, a_id, settle=False), get_version(principal, b_id, settle=False)
    if a["brand_id"] != b["brand_id"]:
        raise ValueError("versions belong to different brands")
    diff = diff_documents(_document(a), _document(b))
    return {"from": {k: a[k] for k in ("version_id", "scope", "scope_ref", "version", "status", "content_hash")},
            "to": {k: b[k] for k in ("version_id", "scope", "scope_ref", "version", "status", "content_hash")},
            "diff": diff.model_dump(mode="json"), "identical": diff.is_empty}


def audit_trail(principal: Principal, brand_id: str, *, subject_id: Optional[str] = None) -> dict[str, Any]:
    brand = brand_for(principal, brand_id)
    authorize(principal, brand["owner_project_id"])
    return {"entries": db.list_audit(brand_id, subject_id=subject_id), "verification": db.verify_audit_chain(brand_id)}


__all__ = [
    "APPROVAL_POLICY", "GenomeBlocked", "GenomeIntegrityError", "READ_ONLY_ROLES", "SUBJECT_GENOME", "audit_trail", "authorize",
    "brand_for", "compare_versions", "create_brand", "create_draft", "edit_draft", "get_version", "layers_for", "list_brands",
    "list_versions", "readiness", "resolve_scope", "revert_to", "scope_project", "settle_version", "submit_version",
    "withdraw_version",
]
