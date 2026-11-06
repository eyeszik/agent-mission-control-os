"""Deliverable Vault and delivery manifests.

The vault lists a project's artifacts with what can be proven about each one:
* version and hash;
* approval state (from the approvals table);
* the release verdict (``intake.release.artifact_release_verdict``: approved,
  not stale, not self-approved, hash-matched);
* rights evidence.

``export_manifest`` re-verifies every requested artifact from its stored bytes
(``intake.runner.verify_artifact``). Only artifacts that pass and are
releasable are included; everything else is listed with its reasons.

The manifest hash is deterministic: no timestamp is hashed, and items are
sorted, so exporting the same state twice gives the same hash. It is signed
with HMAC-SHA256 only when ``AMC_DELIVERY_SIGNING_KEY`` is set (32+
characters); otherwise it says UNSIGNED. Nothing is sent anywhere: the
manifest is returned to the caller and recorded as a project event.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import Any, Optional

from services.langgraph.agency.actions import broker
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.security.auth import Principal

MANIFEST_VERSION = "amc-delivery-manifest/v1"


def _approvals_by_artifact(project_id: str, artifact_ids: list[str]) -> dict[str, list[dict]]:
    from services.langgraph.persistence.approvals import list_approvals_for_subject_refs

    out: dict[str, list[dict]] = {}
    for a in list_approvals_for_subject_refs(project_id, artifact_ids):
        out.setdefault(a["subject_ref"], []).append(a)
    return out


def _verdict(meta: Any, approvals: list[dict], project_id: str, tenant_id: str) -> dict:
    from services.langgraph.agency.intake.release import artifact_release_verdict

    current = [a for a in approvals if a.get("subject_hash") == meta.content_hash]
    approved = next((a for a in current if a.get("status") == "resolved" and a.get("decision") == "approve"), None)
    candidate = approved or (current[0] if current else None)
    verdict = artifact_release_verdict(simulated=False, verification_passed=True, artifact_id=meta.artifact_id,
                                       verified_version=meta.version, verified_hash=meta.content_hash,
                                       approval_id=candidate["approval_id"] if candidate else None, tenant_id=tenant_id,
                                       project_id=project_id)
    return {"allowed": verdict.allowed, "reasons": list(verdict.reasons), "approval_id": verdict.approval_id,
            "note": "assumes verification passes; export re-verifies the stored bytes"}


def vault(principal: Principal, project_id: str) -> list[dict]:
    from services.langgraph.persistence.projects import list_project_artifacts

    broker.authorize_scope(principal, project_id, write=False)
    metas = list_project_artifacts(project_id, limit=1000)
    approvals = _approvals_by_artifact(project_id, [m.artifact_id for m in metas])
    out = []
    for m in metas:
        mine = approvals.get(m.artifact_id, [])
        out.append({
            "artifact_id": m.artifact_id, "artifact_key": m.artifact_key, "artifact_type": m.artifact_type, "version": m.version,
            "content_hash": m.content_hash, "mime_type": m.mime_type, "status": m.status, "preview_uri": m.preview_uri,
            "approvals": [{k: a.get(k) for k in ("approval_id", "status", "decision", "reviewer", "decided_at", "subject_hash")}
                          for a in mine],
            "release": _verdict(m, mine, project_id, principal.tenant_id),
            "rights": {"rights_ref": m.rights_ref, "status": "RECORDED" if m.rights_ref else "NOT_RECORDED"},
            "provenance_ref": m.provenance_ref, "source_refs": list(m.source_refs),
        })
    return out


def _palette(principal: Principal, project_id: str) -> Optional[dict[str, str]]:
    from services.langgraph.agency.intake.context import compile_context
    from services.langgraph.agency.intake.runner import BRAND_AUTHORITY_FLOOR, BRAND_SUBJECT

    capsule, _ = compile_context(tenant_id=principal.tenant_id, project_id=project_id, subjects={BRAND_SUBJECT: BRAND_AUTHORITY_FLOOR})
    entry = capsule.memory.get(BRAND_SUBJECT)
    try:
        return dict(entry["body"]["palette"]) if entry else None
    except (KeyError, TypeError):
        return None


def export_manifest(principal: Principal, project_id: str, artifact_ids: list[str], *, now: Optional[datetime] = None) -> dict:
    from services.langgraph.agency.intake.release import artifact_release_verdict
    from services.langgraph.agency.intake.runner import verify_artifact
    from services.langgraph.agency.project_os.vocabulary import ActivityType
    from services.langgraph.api.routes._project_common import storage_adapter
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import append_project_event

    broker.authorize_scope(principal, project_id, write=True)
    if not artifact_ids:
        raise ValueError("name at least one artifact to export")
    moment = now or datetime.now(timezone.utc)
    adapter = storage_adapter()
    palette = _palette(principal, project_id)
    approvals = _approvals_by_artifact(project_id, artifact_ids)
    items, excluded = [], []
    for artifact_id in sorted(set(artifact_ids)):
        head = get_artifact(artifact_id)
        if head is None or head.get("project_id") != project_id:
            excluded.append({"artifact_id": artifact_id, "reasons": ["ARTIFACT_NOT_IN_PROJECT"]})
            continue
        verification = verify_artifact(artifact_id, expected_version=int(head["version"]), adapter=adapter, palette=palette,
                                       now=moment)
        mine = [a for a in approvals.get(artifact_id, []) if a.get("subject_hash") == head.get("content_hash")]
        approved = next((a for a in mine if a.get("status") == "resolved" and a.get("decision") == "approve"), None)
        verdict = artifact_release_verdict(
            simulated=False, verification_passed=verification.status == "PASSED", artifact_id=artifact_id,
            verified_version=verification.version, verified_hash=verification.content_hash,
            approval_id=(approved or (mine[0] if mine else {})).get("approval_id"), tenant_id=principal.tenant_id,
            project_id=project_id)
        if verification.status != "PASSED" or not verdict.allowed:
            excluded.append({"artifact_id": artifact_id, "version": int(head["version"]),
                             "verification": verification.status,
                             "reasons": sorted(set(verdict.reasons) | set(verification.findings))})
            continue
        items.append({"artifact_id": artifact_id, "artifact_type": head.get("artifact_type"), "version": int(head["version"]),
                      "sha256": verification.content_hash,
                      "verification": {"status": verification.status, "verifier": verification.verifier,
                                       "checks": [{k: c.get(k) for k in ("family", "check", "passed")} for c in verification.checks]},
                      "approval": {"approval_id": approved["approval_id"], "reviewer": approved.get("reviewer"),
                                   "decided_at": approved.get("decided_at")}})
    body = {"manifest_version": MANIFEST_VERSION, "tenant_id": principal.tenant_id, "project_id": project_id, "items": items,
            "excluded": excluded}
    manifest_hash = canonical_hash(body)
    key = (os.environ.get("AMC_DELIVERY_SIGNING_KEY") or "").encode()
    signature = ({"status": "SIGNED", "algorithm": "HMAC-SHA256",
                  "value": hmac.new(key, manifest_hash.encode(), hashlib.sha256).hexdigest()}
                 if len(key) >= 32 else {"status": "UNSIGNED", "reason": "AMC_DELIVERY_SIGNING_KEY is not configured"})
    if items:
        append_project_event(tenant_id=principal.tenant_id, project_id=project_id, event_type=ActivityType.VERIFIED,
                             actor=principal.user_id, subject_ref=f"delivery:{manifest_hash[:16]}",
                             payload={"delivery_manifest_hash": manifest_hash, "items": [i["artifact_id"] for i in items],
                                      "signature_status": signature["status"]})
    return {**body, "manifest_hash": manifest_hash, "signature": signature, "exported_at": moment.isoformat(),
            "delivered_externally": False}


def verify_manifest(manifest: dict) -> dict:
    """Recompute the hash (and the signature when a key is configured) of a manifest."""
    body = {k: manifest.get(k) for k in ("manifest_version", "tenant_id", "project_id", "items", "excluded")}
    recomputed = canonical_hash(body)
    out = {"hash_matches": recomputed == manifest.get("manifest_hash"), "recomputed_hash": recomputed}
    key = (os.environ.get("AMC_DELIVERY_SIGNING_KEY") or "").encode()
    sig = manifest.get("signature") or {}
    if sig.get("status") == "SIGNED" and len(key) >= 32:
        out["signature_valid"] = hmac.compare_digest(sig.get("value", ""), hmac.new(key, recomputed.encode(), hashlib.sha256).hexdigest())
    else:
        out["signature_valid"] = None
    return out


__all__ = ["MANIFEST_VERSION", "export_manifest", "vault", "verify_manifest"]
