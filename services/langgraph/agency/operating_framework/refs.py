"""Resolve and check the references a task or assurance record carries.

Read-only. Every reference resolves against the store that owns it - Project OS
knowledge items, N4 kernel evidence and decisions, N4/Project OS artifacts with
a storage read-back - inside the caller's tenant and project. A reference that
does not exist or belongs elsewhere reports ``REF_NOT_FOUND`` either way, so a
lookup cannot be used to probe another project.

``origin`` keeps synthetic material apart from customer evidence: anything whose
source is ``synthetic:`` / ``fixture:`` is ``SYNTHETIC`` wherever it is used,
and no check here promotes it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.project_os.knowledge import (
    DEFAULT_FRESHNESS_DAYS,
    FRESHNESS_DAYS,
)

from .contracts import EvidenceOrigin, parse_artifact_ref, ref_kind

SYNTHETIC_PREFIXES = ("synthetic:", "fixture:")
CUSTOMER_DOMAINS = ("customer", "client", "voc", "first_party")
_UNUSABLE_EPISTEMIC = {"stale", "conflict", "blocked", "unverified"}
_INFERENCE_EPISTEMIC = {"inferred", "assumption", "hypothesis"}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _origin_for_source(source: str | None, domain: str | None = None) -> str:
    text = (source or "").strip().lower()
    if text.startswith(SYNTHETIC_PREFIXES) or text.startswith("synthetic://"):
        return EvidenceOrigin.SYNTHETIC.value
    if (domain or "").lower() in CUSTOMER_DOMAINS:
        return EvidenceOrigin.CUSTOMER_SOURCED.value
    return EvidenceOrigin.PUBLIC_SOURCE.value


def _result(ref: str, status: str, *, origin: str | None = None, content_hash: str | None = None,
            fresh_until: str | None = None, detail: str = "", attachable: bool = True) -> dict[str, Any]:
    return {"ref": ref, "kind": ref_kind(ref), "status": status, "ok": status == "OK", "attachable": attachable,
            "origin": origin, "content_hash": content_hash, "fresh_until": fresh_until, "detail": detail}


def _knowledge(ref: str, item_id: str, tenant_id: str, project_id: str, now: datetime) -> dict[str, Any]:
    from services.langgraph.persistence.database import decode_json, table, transaction

    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('knowledge_items')} WHERE item_id = ?", (item_id,)).fetchone()
    if row is None or row["tenant_id"] != tenant_id or row["project_id"] != project_id:
        return _result(ref, "REF_NOT_FOUND", attachable=False)
    origin = _origin_for_source(row["source_uri"], row["domain"])
    status = str(row["status"])
    if status == "REJECTED":
        return _result(ref, "EVIDENCE_REJECTED", origin=origin, content_hash=row["content_hash"], attachable=False)
    fetched = _parse_time(row["fetched_at"])
    if fetched is None:
        return _result(ref, "EVIDENCE_UNDATED", origin=origin, content_hash=row["content_hash"],
                       detail="no acquisition date; freshness cannot be established")
    deadline = fetched + timedelta(days=FRESHNESS_DAYS.get(row["domain"], DEFAULT_FRESHNESS_DAYS))
    if status != "PROMOTED":
        return _result(ref, "EVIDENCE_NOT_REVIEWED", origin=origin, content_hash=row["content_hash"],
                       fresh_until=deadline.isoformat(), detail=f"knowledge item is {status}")
    if deadline < now:
        return _result(ref, "EVIDENCE_STALE", origin=origin, content_hash=row["content_hash"],
                       fresh_until=deadline.isoformat(), detail=f"{row['domain']} evidence expired")
    claims = decode_json(row["claims"], [])
    return _result(ref, "OK", origin=origin, content_hash=row["content_hash"], fresh_until=deadline.isoformat(),
                   detail=f"{len(claims)} claim(s), rights {row['rights_class']}")


def _kernel_evidence(ref: str, evidence_id: str, tenant_id: str, project_id: str, now: datetime) -> dict[str, Any]:
    from services.langgraph.persistence.agency_kernel import get_evidence

    record = get_evidence(evidence_id)
    if record is None or record.get("tenant_id") != tenant_id or record.get("project_id") != project_id:
        return _result(ref, "REF_NOT_FOUND", attachable=False)
    digest = canonical_hash({k: record.get(k) for k in ("evidence_id", "claim", "source_ref", "epistemic_status",
                                                         "collected_at", "payload")})
    epistemic = str(record.get("epistemic_status") or "unverified")
    origin = _origin_for_source(record.get("source_ref"), record.get("evidence_type"))
    if epistemic in _INFERENCE_EPISTEMIC and origin != EvidenceOrigin.SYNTHETIC.value:
        origin = EvidenceOrigin.INFERENCE.value
    if epistemic in _UNUSABLE_EPISTEMIC:
        return _result(ref, f"EVIDENCE_{epistemic.upper()}", origin=origin, content_hash=digest)
    collected = _parse_time(record.get("collected_at"))
    freshness = record.get("freshness_seconds")
    fresh_until = None
    if collected is not None and freshness:
        deadline = collected + timedelta(seconds=int(freshness))
        fresh_until = deadline.isoformat()
        if deadline < now:
            return _result(ref, "EVIDENCE_STALE", origin=origin, content_hash=digest, fresh_until=fresh_until)
    return _result(ref, "OK", origin=origin, content_hash=digest, fresh_until=fresh_until,
                   detail=f"epistemic status {epistemic}")


def _decision(ref: str, decision_id: str, tenant_id: str, project_id: str) -> dict[str, Any]:
    from services.langgraph.persistence.agency_kernel import get_decision
    from services.langgraph.persistence.database import decode_json

    record = get_decision(decision_id)
    if record is None or record.get("tenant_id") != tenant_id or record.get("project_id") != project_id:
        return _result(ref, "REF_NOT_FOUND", attachable=False)
    alternatives = decode_json(record.get("alternatives"), []) if isinstance(record.get("alternatives"), str) else record.get("alternatives") or []
    digest = canonical_hash({k: record.get(k) for k in ("decision_id", "question", "selected_option", "status")}
                            | {"alternatives": alternatives})
    if str(record.get("status")) == "rejected":
        return _result(ref, "DECISION_REJECTED", origin=EvidenceOrigin.INTERNAL_RECORD.value, content_hash=digest)
    if not alternatives:
        return _result(ref, "DECISION_NO_ALTERNATIVES", origin=EvidenceOrigin.INTERNAL_RECORD.value, content_hash=digest,
                       detail="a decision must record the alternatives it chose between")
    return _result(ref, "OK", origin=EvidenceOrigin.INTERNAL_RECORD.value, content_hash=digest,
                   detail=f"status {record.get('status')}")


def _genome(ref: str, version_id: str, tenant_id: str, project_id: str) -> dict[str, Any]:
    """An approved VNEXUS genome version is a decision the brand owner already ratified."""
    from services.langgraph.persistence.vnexus import get_version

    record = get_version(version_id)
    if record is None or record.get("tenant_id") != tenant_id or record.get("project_id") != project_id:
        return _result(ref, "REF_NOT_FOUND", attachable=False)
    status = str(record.get("status"))
    if status == "SUPERSEDED":
        return _result(ref, "GENOME_SUPERSEDED", origin=EvidenceOrigin.INTERNAL_RECORD.value,
                       content_hash=record.get("content_hash"), detail="a newer genome version was approved")
    if status != "APPROVED":
        return _result(ref, "GENOME_NOT_APPROVED", origin=EvidenceOrigin.INTERNAL_RECORD.value,
                       content_hash=record.get("content_hash"), detail=f"genome version is {status}")
    return _result(ref, "OK", origin=EvidenceOrigin.INTERNAL_RECORD.value, content_hash=record.get("content_hash"),
                   detail=f"approved {record.get('scope')} genome v{record.get('version')} by {record.get('decided_by')}")


def read_artifact_bytes(artifact: dict, adapter: Any) -> bytes | None:
    """Read an artifact head's bytes back from storage, or None if they are not readable here."""
    location = artifact.get("content_location") or ""
    if not location.startswith("local://"):
        return None
    tenant_id, project_id = location[len("local://"):].split("/")[:2]
    if (tenant_id, project_id) != (artifact.get("tenant_id"), artifact.get("project_id")):
        return None
    try:
        return adapter.get_bytes(location)
    except Exception:  # noqa: BLE001 - unreadable bytes are reported by the caller as a failed readback
        return None


def _artifact(ref: str, tenant_id: str, project_id: str, adapter: Any) -> dict[str, Any]:
    from services.langgraph.persistence.agency_kernel import get_artifact

    artifact_id, version = parse_artifact_ref(ref)
    record = get_artifact(artifact_id)
    if record is None or record.get("tenant_id") != tenant_id or record.get("project_id") != project_id:
        return _result(ref, "REF_NOT_FOUND", attachable=False)
    head_hash = record.get("content_hash")
    if int(record["version"]) != version:
        return _result(ref, "ARTIFACT_STALE", content_hash=head_hash,
                       detail=f"head is v{record['version']}, ref pins v{version}")
    if str(record.get("status")) == "invalidated":
        return _result(ref, "ARTIFACT_INVALIDATED", content_hash=head_hash)
    data = read_artifact_bytes(record, adapter) if adapter is not None else None
    if data is None:
        return _result(ref, "READBACK_UNAVAILABLE", content_hash=head_hash, detail="stored bytes are not readable here")
    if hashlib.sha256(data).hexdigest() != head_hash:
        return _result(ref, "READBACK_MISMATCH", content_hash=head_hash, attachable=False)
    origin = EvidenceOrigin.SYNTHETIC.value if (record.get("metadata") or {}).get("synthetic") else EvidenceOrigin.INTERNAL_RECORD.value
    return _result(ref, "OK", origin=origin, content_hash=head_hash, detail=f"{record['artifact_type']} v{version}, {len(data)} bytes read back")


def resolve_ref(ref: str, *, tenant_id: str, project_id: str, adapter: Any = None,
                now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    kind, _, rest = ref.partition(":")
    if kind == "knowledge":
        return _knowledge(ref, rest, tenant_id, project_id, now)
    if kind == "evidence":
        return _kernel_evidence(ref, rest, tenant_id, project_id, now)
    if kind == "decision":
        return _decision(ref, rest, tenant_id, project_id)
    if kind == "genome":
        return _genome(ref, rest, tenant_id, project_id)
    if kind == "artifact":
        return _artifact(ref, tenant_id, project_id, adapter)
    return _result(ref, "REF_KIND_UNKNOWN", attachable=False)


__all__ = ["CUSTOMER_DOMAINS", "SYNTHETIC_PREFIXES", "read_artifact_bytes", "resolve_ref"]
