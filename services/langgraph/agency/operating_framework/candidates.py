"""Read-only inspection of a sealed delivery release candidate for a framework Review.

``agency/delivery`` seals a ``ReleaseCandidateManifest`` for a run before its
approval can be decided, and is the only release authority: resume runs
``evaluate_release_predicate``. This module only reads that seal and re-checks
it at use time, the same way the release gate does:

- the manifest still hashes to the sealed ``candidate_manifest_hash`` and to
  the sealed approval subject;
- every artifact is still the head the manifest pinned, and the dependency
  snapshot is unchanged;
- every artifact hash recomputes from the stored payload it was bound over
  (the binding layer's own spec and subject hash, not a second scheme);
- the run's own approval exists and, in enforce mode, is bound to the sealed
  subject.

Nothing here writes, opens an approval or releases. A run outside the plan's
tenant and project is reported exactly like a missing one.
"""

from __future__ import annotations

import json
import re
from typing import Any

from services.langgraph.persistence.approvals import get_approvals_for_run

from .contracts import FrameworkError

CANDIDATE_REF = re.compile(r"^release-candidate:([A-Za-z0-9][A-Za-z0-9_.:-]{0,199})$")
RELEASE_AUTHORITY = "agency/delivery: evaluate_release_predicate when the run resumes after /approvals/{id}/decide"

# Blocking codes. Each means the sealed candidate no longer describes what would ship.
NOT_SEALED = "CANDIDATE_NOT_SEALED"
INVALID = "CANDIDATE_INVALID"
HASH_MISMATCH = "CANDIDATE_HASH_MISMATCH"
SUBJECT_MISMATCH = "APPROVAL_SUBJECT_MISMATCH"
ARTIFACTS_CHANGED = "ARTIFACTS_CHANGED"
DEPENDENCIES_CHANGED = "DEPENDENCIES_CHANGED"
PAYLOAD_UNVERIFIED = "PAYLOAD_UNVERIFIED"


def run_id_of(ref: str) -> str:
    match = CANDIDATE_REF.match(ref)
    if not match:
        raise FrameworkError("REF_REJECTED", "A release candidate ref is release-candidate:<run_id>", 422)
    return match.group(1)


def subject_ref(version_ref: str) -> str:
    """``art-x:v3`` (a manifest version ref) as the framework's ``artifact:art-x@v3``."""
    artifact_id, _, version = version_ref.rpartition(":v")
    return f"artifact:{artifact_id}@v{version}"


def load_run(ref: str, plan: dict) -> dict:
    """The run behind the ref, only when it is in the plan's tenant and project."""
    from services.langgraph.persistence.runs import get_run_record

    record = get_run_record(run_id_of(ref))
    if record is None or (record.get("tenant_id"), record.get("project_id")) != (plan["tenant_id"], plan["project_id"]):
        raise FrameworkError("REF_NOT_FOUND", "No release candidate with that ref in this project", 422,
                             {"checks": [{"ref": ref, "status": "REF_NOT_FOUND"}]})
    return record


def _payloads(run_id: str, agency: dict) -> dict[str, Any]:
    """The payload each candidate artifact's hash was computed over, by artifact id.

    Reuses the run artifact binding layer's own definitions so the reviewer
    checks exactly what delivery bound.
    """
    from services.langgraph.api.routes.agency import (
        _agency_subject_hash,
        _workspace_artifact_specs,
    )

    out: dict[str, Any] = {f"art-protected-{run_id}": ("subject", agency)}
    package = agency.get("campaign_package") or {}
    export = package.get("workspace_export") if isinstance(package, dict) else None
    if isinstance(export, dict) and export.get("root_folder"):
        for spec in _workspace_artifact_specs(run_id=run_id, workspace_export=export, package=package):
            out[f"art-{run_id}-{spec['artifact_key']}"] = ("payload", spec["payload"])
    return {k: (_agency_subject_hash(v) if kind == "subject" else None, v if kind == "payload" else None)
            for k, (kind, v) in out.items()}


def _verify_payloads(run_id: str, agency: dict, refs: list) -> list[dict]:
    from services.langgraph.persistence.idempotency import hash_payload

    sources = _payloads(run_id, agency)
    checks = []
    for ref in refs:
        precomputed, payload = sources.get(ref.artifact_id, (None, None))
        if precomputed is None and payload is None:
            checks.append({"artifact_id": ref.artifact_id, "hash_verified": False, "bytes_read": None,
                           "detail": "no stored payload for this artifact"})
            continue
        recomputed = precomputed if precomputed is not None else hash_payload(payload)
        size = len(json.dumps(agency if precomputed is not None else payload, sort_keys=True, default=str).encode())
        checks.append({"artifact_id": ref.artifact_id, "hash_verified": recomputed == ref.content_hash,
                       "bytes_read": size, "detail": "hash recomputed from the stored payload"})
    return checks


def inspect(ref: str, plan: dict) -> dict[str, Any]:
    """Use-time facts about the sealed candidate. Raises only when the run is not this project's."""
    from pydantic import ValidationError

    from services.langgraph.agency.delivery.release import (
        ReleaseCandidateManifest,
        approval_subject_hash,
        candidate_manifest_hash,
        dependency_snapshot_hash,
    )
    from services.langgraph.persistence.delivery import (
        current_artifact_refs,
        dependency_edges,
    )

    record = load_run(ref, plan)
    run_id = record["run_id"]
    agency = (record.get("result") or {}).get("agency") or {}
    sealed = agency.get("release_candidate") or {}
    contract_mode = ((record.get("metadata") or {}).get("workflow") or {}).get("contract_mode")
    base = {"ref": ref, "run_id": run_id, "contract_mode": contract_mode, "release_authority": RELEASE_AUTHORITY}
    if sealed.get("status") != "SEALED":
        return {**base, "status": "NOT_SEALED", "blocking": [NOT_SEALED], "artifact_refs": [], "payload_checks": [],
                "candidate_manifest_hash": None, "approval_subject_hash": None, "native_approval": None,
                "freshness": None, "reason": sealed.get("reason") or "the run has no sealed release candidate"}
    try:
        manifest = ReleaseCandidateManifest.model_validate(sealed["manifest"])
    except (KeyError, ValidationError):
        return {**base, "status": "INVALID", "blocking": [INVALID], "artifact_refs": [], "payload_checks": [],
                "candidate_manifest_hash": sealed.get("candidate_manifest_hash"), "native_approval": None,
                "approval_subject_hash": sealed.get("approval_subject_hash"), "freshness": None}
    blocking: list[str] = []
    recomputed = candidate_manifest_hash(manifest)
    hash_ok = (recomputed == sealed.get("candidate_manifest_hash") and manifest.run_id == run_id
               and manifest.project_id == plan["project_id"])
    if not hash_ok:
        blocking.append(HASH_MISMATCH)
    subject = approval_subject_hash(candidate_manifest_hash=recomputed, contract_hash=manifest.contract_hash,
                                    policy_version=manifest.policy_version)
    subject_ok = subject == sealed.get("approval_subject_hash")
    if not subject_ok and HASH_MISMATCH not in blocking:
        blocking.append(HASH_MISMATCH)
    ids = [r.artifact_id for r in manifest.artifact_refs]
    artifacts_ok = tuple(current_artifact_refs(ids)) == tuple(manifest.artifact_refs)
    if not artifacts_ok:
        blocking.append(ARTIFACTS_CHANGED)
    deps_ok = dependency_snapshot_hash(dependency_edges(ids)) == manifest.dependency_snapshot_hash
    if not deps_ok:
        blocking.append(DEPENDENCIES_CHANGED)
    payload_checks = _verify_payloads(run_id, agency, list(manifest.artifact_refs))
    if not all(c["hash_verified"] for c in payload_checks):
        blocking.append(PAYLOAD_UNVERIFIED)

    approvals = get_approvals_for_run(run_id)
    native = None
    if approvals:
        latest = approvals[0]
        bound = latest.get("subject_hash") == sealed.get("approval_subject_hash")
        native = {"approval_id": latest["approval_id"], "status": latest.get("status"),
                  "policy_version": latest.get("policy_version"), "subject_bound": bound,
                  "decide_route": f"/approvals/{latest['approval_id']}/decide"}
        # Enforce binds the approval to the sealed subject; shadow keeps the legacy subject by design.
        if contract_mode == "enforce" and not bound:
            blocking.append(SUBJECT_MISMATCH)
    return {
        **base,
        "status": "CURRENT" if not blocking else "BLOCKED",
        "blocking": blocking,
        "candidate_manifest_hash": sealed.get("candidate_manifest_hash"),
        "recomputed_manifest_hash": recomputed,
        "approval_subject_hash": sealed.get("approval_subject_hash"),
        "contract_hash": manifest.contract_hash,
        "policy_version": manifest.policy_version,
        "dependency_snapshot_hash": manifest.dependency_snapshot_hash,
        "artifact_refs": [r.model_dump(mode="json") for r in manifest.artifact_refs],
        "payload_checks": payload_checks,
        "freshness": {"manifest_hash_verified": hash_ok, "approval_subject_verified": subject_ok,
                      "artifacts_current": artifacts_ok, "dependencies_current": deps_ok},
        "native_approval": native,
    }


__all__ = ["CANDIDATE_REF", "RELEASE_AUTHORITY", "inspect", "load_run", "run_id_of", "subject_ref"]
