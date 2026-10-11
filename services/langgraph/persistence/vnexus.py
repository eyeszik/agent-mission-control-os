"""Persistence for VNEXUS: brands, genome versions and the hash-chained audit log.

Rows only. Authorization, validation and lifecycle rules live in
``agency/vnexus/service.py``; this module enforces what the database must
guarantee regardless of caller:

* an APPROVED, IN_REVIEW, REJECTED or SUPERSEDED genome version is never
  rewritten (updates are conditioned on an editable status and a revision);
* at most one APPROVED version per scope (a partial unique index, and the
  previous one is superseded in the same transaction);
* every state change appends an audit entry whose hash covers the previous
  entry of the same chain, so a removed or edited entry is detectable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from uuid import uuid4

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.persistence.database import decode_json, is_postgres, json_param, normalize_record, table, transaction
from services.langgraph.persistence.tenancy import ensure_tenant_project


class VnexusNotFound(LookupError):
    pass


class VnexusConflict(ValueError):
    """A compare-and-set lost, a duplicate identity, or a write to a frozen row."""


class GenomeImmutable(VnexusConflict):
    """The version is not editable (in review, approved, rejected or superseded)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _rec(row: Any, json_fields: Iterable[tuple[str, Any]]) -> Optional[dict]:
    if row is None:
        return None
    rec = normalize_record(row)
    for key, default in json_fields:
        rec[key] = decode_json(rec.get(key), default)
    return rec


# --------------------------------------------------------------------------- audit


def _lock_chain(db: Any, chain_ref: str) -> None:
    if is_postgres():
        # Serialize appends to one chain so two writers cannot both extend the same head.
        db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (chain_ref,))


def append_audit(db: Any, *, tenant_id: str, chain_ref: str, subject_type: str, subject_id: str, action: str, actor: str,
                 from_state: Optional[str] = None, to_state: Optional[str] = None, detail: Optional[dict] = None) -> dict:
    _lock_chain(db, chain_ref)
    prev = db.execute(f"SELECT entry_hash FROM {table('vnexus_audit_log')} WHERE chain_ref = ? ORDER BY entry_id DESC LIMIT 1",
                      (chain_ref,)).fetchone()
    prev_hash = normalize_record(prev)["entry_hash"] if prev else None
    created_at = now_iso()
    body = {"tenant_id": tenant_id, "chain_ref": chain_ref, "subject_type": subject_type, "subject_id": subject_id,
            "action": action, "actor": actor, "from_state": from_state, "to_state": to_state, "detail": detail or {},
            "prev_hash": prev_hash, "created_at": created_at}
    entry_hash = canonical_hash(body)
    db.execute(
        f"""INSERT INTO {table('vnexus_audit_log')} (tenant_id, chain_ref, subject_type, subject_id, action, actor, from_state,
        to_state, detail, prev_hash, entry_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (tenant_id, chain_ref, subject_type, subject_id, action, actor, from_state, to_state, json_param(detail or {}),
         prev_hash, entry_hash, created_at),
    )
    return {**body, "entry_hash": entry_hash}


def list_audit(chain_ref: str, *, subject_id: Optional[str] = None, limit: int = 500) -> list[dict]:
    query = f"SELECT * FROM {table('vnexus_audit_log')} WHERE chain_ref = ?"
    params: list[Any] = [chain_ref]
    if subject_id:
        query += " AND subject_id = ?"
        params.append(subject_id)
    query += " ORDER BY entry_id LIMIT ?"
    params.append(limit)
    with transaction() as db:
        return [_rec(r, (("detail", {}),)) for r in db.execute(query, params).fetchall()]


def verify_audit_chain(chain_ref: str) -> dict:
    """Recompute every entry hash and link. Returns the first break, if any."""
    entries = list_audit(chain_ref, limit=100_000)
    prev: Optional[str] = None
    for i, e in enumerate(entries):
        body = {k: e[k] for k in ("tenant_id", "chain_ref", "subject_type", "subject_id", "action", "actor", "from_state",
                                  "to_state", "detail", "prev_hash", "created_at")}
        if e["prev_hash"] != prev:
            return {"intact": False, "entries": len(entries), "break_at": i, "reason": "prev_hash does not link"}
        if canonical_hash(body) != e["entry_hash"]:
            return {"intact": False, "entries": len(entries), "break_at": i, "reason": "entry content changed"}
        prev = e["entry_hash"]
    return {"intact": True, "entries": len(entries), "head": prev}


# --------------------------------------------------------------------------- brands


def create_brand(*, tenant_id: str, brand_id: str, owner_project_id: str, display_name: str, actor: str) -> dict:
    created_at = now_iso()
    with transaction(write=True) as db:
        ensure_tenant_project(db, tenant_id, owner_project_id)
        if db.execute(f"SELECT 1 FROM {table('vnexus_brands')} WHERE brand_id = ?", (brand_id,)).fetchone():
            raise VnexusConflict(f"brand {brand_id} already exists")
        db.execute(
            f"""INSERT INTO {table('vnexus_brands')} (brand_id, tenant_id, owner_project_id, display_name, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""", (brand_id, tenant_id, owner_project_id, display_name, actor, created_at))
        append_audit(db, tenant_id=tenant_id, chain_ref=brand_id, subject_type="brand", subject_id=brand_id, action="create",
                     actor=actor, to_state="ACTIVE", detail={"owner_project_id": owner_project_id, "display_name": display_name})
    return get_brand(brand_id)


def get_brand(brand_id: str) -> Optional[dict]:
    with transaction() as db:
        return _rec(db.execute(f"SELECT * FROM {table('vnexus_brands')} WHERE brand_id = ?", (brand_id,)).fetchone(), ())


def list_brands(tenant_id: str) -> list[dict]:
    with transaction() as db:
        rows = db.execute(f"SELECT * FROM {table('vnexus_brands')} WHERE tenant_id = ? ORDER BY brand_id", (tenant_id,)).fetchall()
    return [_rec(r, ()) for r in rows]


# --------------------------------------------------------------------------- genome versions

_VERSION_JSON = (("document", {}),)
_EDITABLE = ("DRAFT", "EXPERIMENTAL")


def get_version(version_id: str) -> Optional[dict]:
    with transaction() as db:
        return _rec(db.execute(f"SELECT * FROM {table('vnexus_genome_versions')} WHERE version_id = ?", (version_id,)).fetchone(),
                    _VERSION_JSON)


def list_versions(brand_id: str, *, scope: Optional[str] = None, scope_ref: Optional[str] = None,
                  statuses: Optional[Iterable[str]] = None) -> list[dict]:
    query = f"SELECT * FROM {table('vnexus_genome_versions')} WHERE brand_id = ?"
    params: list[Any] = [brand_id]
    if scope:
        query += " AND scope = ?"
        params.append(scope)
    if scope_ref:
        query += " AND scope_ref = ?"
        params.append(scope_ref)
    wanted = list(statuses or [])
    if wanted:
        query += f" AND status IN ({','.join('?' * len(wanted))})"
        params += wanted
    query += " ORDER BY scope, scope_ref, version"
    with transaction() as db:
        return [_rec(r, _VERSION_JSON) for r in db.execute(query, params).fetchall()]


def approved_version(brand_id: str, scope: str, scope_ref: str) -> Optional[dict]:
    found = list_versions(brand_id, scope=scope, scope_ref=scope_ref, statuses=["APPROVED"])
    return found[0] if found else None


def create_version(*, tenant_id: str, brand_id: str, scope: str, scope_ref: str, project_id: str, document: dict,
                   content_hash: str, actor: str, status: str = "DRAFT", origin: str = "AUTHORED",
                   origin_ref: Optional[str] = None, parent_version_id: Optional[str] = None) -> dict:
    if status not in _EDITABLE:
        raise VnexusConflict("new versions start as DRAFT or EXPERIMENTAL")
    version_id = f"gv-{uuid4().hex}"
    stamp = now_iso()
    with transaction(write=True) as db:
        ensure_tenant_project(db, tenant_id, project_id)
        row = db.execute(f"SELECT COALESCE(MAX(version), 0) AS v FROM {table('vnexus_genome_versions')} "
                         "WHERE brand_id = ? AND scope = ? AND scope_ref = ?", (brand_id, scope, scope_ref)).fetchone()
        version = int(normalize_record(row)["v"]) + 1
        db.execute(
            f"""INSERT INTO {table('vnexus_genome_versions')} (version_id, tenant_id, brand_id, scope, scope_ref, project_id,
            version, parent_version_id, status, document, content_hash, revision, origin, origin_ref, created_by, created_at,
            updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
            (version_id, tenant_id, brand_id, scope, scope_ref, project_id, version, parent_version_id, status,
             json_param(document), content_hash, origin, origin_ref, actor, stamp, stamp))
        append_audit(db, tenant_id=tenant_id, chain_ref=brand_id, subject_type="genome_version", subject_id=version_id,
                     action="create", actor=actor, to_state=status,
                     detail={"scope": scope, "scope_ref": scope_ref, "version": version, "content_hash": content_hash,
                             "origin": origin, "origin_ref": origin_ref, "parent_version_id": parent_version_id})
    return get_version(version_id)


def update_version_document(version_id: str, *, expected_revision: int, document: dict, content_hash: str, actor: str) -> dict:
    with transaction(write=True) as db:
        cur = db.execute(
            f"""UPDATE {table('vnexus_genome_versions')} SET document = ?, content_hash = ?, revision = revision + 1,
            updated_at = ? WHERE version_id = ? AND revision = ? AND status IN ('DRAFT','EXPERIMENTAL')""",
            (json_param(document), content_hash, now_iso(), version_id, expected_revision))
        if cur.rowcount != 1:
            current = _rec(db.execute(f"SELECT * FROM {table('vnexus_genome_versions')} WHERE version_id = ?",
                                      (version_id,)).fetchone(), _VERSION_JSON)
            if current is None:
                raise VnexusNotFound(f"genome version {version_id} not found")
            if current["status"] not in _EDITABLE:
                raise GenomeImmutable(f"genome version {version_id} is {current['status']} and cannot be edited")
            raise VnexusConflict(f"stale revision: expected {expected_revision}, current {current['revision']}")
        row = _rec(db.execute(f"SELECT * FROM {table('vnexus_genome_versions')} WHERE version_id = ?", (version_id,)).fetchone(),
                   _VERSION_JSON)
        append_audit(db, tenant_id=row["tenant_id"], chain_ref=row["brand_id"], subject_type="genome_version",
                     subject_id=version_id, action="edit", actor=actor, from_state=row["status"], to_state=row["status"],
                     detail={"revision": row["revision"], "content_hash": content_hash})
    return row


def transition_version(version_id: str, *, from_status: str, to_status: str, actor: str, action: str,
                       detail: Optional[dict] = None, **fields: Any) -> dict:
    """Compare-and-set a status. Approving supersedes the scope's previous approved version in the same transaction."""
    allowed = {"submitted_by", "submitted_at", "approval_id", "decided_by", "decided_at"}
    if set(fields) - allowed:
        raise ValueError(f"cannot set {sorted(set(fields) - allowed)} on a genome version")
    stamp = now_iso()
    with transaction(write=True) as db:
        row = _rec(db.execute(f"SELECT * FROM {table('vnexus_genome_versions')} WHERE version_id = ?", (version_id,)).fetchone(),
                   _VERSION_JSON)
        if row is None:
            raise VnexusNotFound(f"genome version {version_id} not found")
        if to_status == "APPROVED":
            previous = db.execute(
                f"SELECT version_id FROM {table('vnexus_genome_versions')} WHERE brand_id = ? AND scope = ? AND scope_ref = ? "
                "AND status = 'APPROVED'", (row["brand_id"], row["scope"], row["scope_ref"])).fetchall()
            for prev in previous:
                prev_id = normalize_record(prev)["version_id"]
                db.execute(f"UPDATE {table('vnexus_genome_versions')} SET status = 'SUPERSEDED', updated_at = ? "
                           "WHERE version_id = ? AND status = 'APPROVED'", (stamp, prev_id))
                append_audit(db, tenant_id=row["tenant_id"], chain_ref=row["brand_id"], subject_type="genome_version",
                             subject_id=prev_id, action="supersede", actor=actor, from_state="APPROVED", to_state="SUPERSEDED",
                             detail={"superseded_by": version_id})
        sets = ", ".join(["status = ?", "updated_at = ?"] + [f"{k} = ?" for k in sorted(fields)])
        params = [to_status, stamp] + [fields[k] for k in sorted(fields)] + [version_id, from_status]
        cur = db.execute(f"UPDATE {table('vnexus_genome_versions')} SET {sets} WHERE version_id = ? AND status = ?", params)
        if cur.rowcount != 1:
            raise VnexusConflict(f"genome version {version_id} is no longer {from_status}")
        append_audit(db, tenant_id=row["tenant_id"], chain_ref=row["brand_id"], subject_type="genome_version",
                     subject_id=version_id, action=action, actor=actor, from_state=from_status, to_state=to_status,
                     detail={"content_hash": row["content_hash"], **(detail or {})})
    return get_version(version_id)


__all__ = [
    "GenomeImmutable", "VnexusConflict", "VnexusNotFound", "append_audit", "approved_version", "create_brand", "create_version",
    "get_brand", "get_version", "list_audit", "list_brands", "list_versions", "now_iso", "transition_version",
    "update_version_document", "verify_audit_chain",
]
