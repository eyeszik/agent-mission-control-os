"""Project workspaces, the project activity stream, and artifact graph v2.

Canonical state lives here (relational). The filesystem mirror and object
storage are written *after* the relational commit and are reconstructable, so
a mirror failure never loses or forks project state.

Artifact operations do not introduce a second registry: every artifact is an
N4 ``agency_artifacts`` row created through ``agency_kernel`` (so N1 ownership
is enforced at write time), and every revision goes through
``record_artifact_revision`` (so dependency invalidation, stale approvals and
lineage remediation keep working). ``artifact_versions`` only adds the history
the registry row overwrites, which is what compare/restore need.
"""

from __future__ import annotations

import difflib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from uuid import uuid4

from services.langgraph.agency.kernel.ontology import owning_department, resolve_artifact_type
from services.langgraph.agency.project_os.models import (
    ArtifactDiff,
    ArtifactHead,
    ArtifactMetadataV2,
    ArtifactVersionRecord,
    AssetRights,
    ProjectEvent,
    ProjectSnapshot,
    ProjectWorkspaceV2,
    StorageObject,
)
from services.langgraph.agency.project_os.storage import StorageAdapter, StoredObject
from services.langgraph.agency.project_os.vocabulary import (
    PROJECT_TRANSITIONS,
    ActivityType,
    ProjectLifecycle,
    can_transition,
)
from services.langgraph.agency.project_os.workspace import (
    build_manifest,
    canonical_json,
    folder_path,
    manifest_hash,
    materialize_manifest,
    project_root,
    sha256_bytes,
    slugify,
)
from services.langgraph.persistence.agency_kernel import (
    StaleArtifactVersionError,
    create_artifact,
    create_engagement,
    ensure_artifact_dependency,
    get_artifact,
    get_engagement,
    record_artifact_revision,
)
from services.langgraph.persistence.database import (
    decode_json,
    is_postgres,
    json_param,
    normalize_record,
    table,
    transaction,
)
from services.langgraph.persistence.tenancy import ProjectOwnershipError, ensure_tenant_project

__all__ = [
    "ProjectConflictError",
    "ProjectNotFoundError",
    "StaleArtifactVersionError",
]

_TEXT_DIFF_LIMIT = 400


class ProjectNotFoundError(LookupError):
    pass


class ProjectConflictError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list(value: Any) -> list:
    decoded = decode_json(value, [])
    return list(decoded or [])


def _dict(value: Any) -> dict:
    decoded = decode_json(value, {})
    return dict(decoded or {})


def project_engagement_id(project_id: str) -> str:
    return f"eng-project-{project_id}"


# --------------------------------------------------------------------------
# Project workspaces
# --------------------------------------------------------------------------


def _workspace_from_row(row: Any) -> ProjectWorkspaceV2:
    record = normalize_record(row)
    return ProjectWorkspaceV2(
        project_id=record["project_id"],
        tenant_id=record["tenant_id"],
        slug=record["slug"],
        display_name=record["display_name"],
        description=record.get("description") or "",
        lifecycle_state=record["lifecycle_state"],
        brand_id=record.get("brand_id"),
        brand_name=record.get("brand_name"),
        manifest_hash=record["manifest_hash"],
        created_by=record["created_by"],
        created_at=str(record["created_at"]),
        updated_at=str(record["updated_at"]),
    )


def get_project_workspace(project_id: str) -> Optional[ProjectWorkspaceV2]:
    with transaction() as db:
        row = db.execute(f"SELECT * FROM {table('project_workspaces')} WHERE project_id = ?", (project_id,)).fetchone()
    return _workspace_from_row(row) if row else None


def require_project_workspace(project_id: str) -> ProjectWorkspaceV2:
    workspace = get_project_workspace(project_id)
    if workspace is None:
        raise ProjectNotFoundError(project_id)
    return workspace


def list_project_workspaces(tenant_id: str, *, project_ids: Optional[Iterable[str]] = None, limit: int = 200) -> list[ProjectWorkspaceV2]:
    query = f"SELECT * FROM {table('project_workspaces')} WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]
    allowed = None if project_ids is None else sorted(set(project_ids))
    if allowed is not None:
        if not allowed:
            return []
        query += f" AND project_id IN ({','.join('?' for _ in allowed)})"
        params.extend(allowed)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_workspace_from_row(row) for row in rows]


def create_project_workspace(
    *,
    tenant_id: str,
    project_id: str,
    actor: str,
    display_name: str,
    slug: Optional[str] = None,
    description: str = "",
    brand_id: Optional[str] = None,
    brand_name: Optional[str] = None,
    export_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Initialize a project. Idempotent per project_id.

    Order: tenant ownership → canonical rows (workspace, engagement, first
    event, memory namespace) in one transaction → filesystem mirror. A second
    call for the same project returns the existing workspace unchanged.
    """
    existing = get_project_workspace(project_id)
    if existing is not None:
        if existing.tenant_id != tenant_id:
            raise ProjectOwnershipError("Project is registered to a different tenant")
        return {"workspace": existing, "created": False, "mirror": None}

    clean_slug = slugify(slug or display_name, fallback=slugify(project_id))
    manifest = build_manifest(
        project_id=project_id,
        tenant_id=tenant_id,
        slug=clean_slug,
        display_name=display_name,
        brand_id=brand_id,
    )
    digest = manifest_hash(manifest)
    now = _now()
    with transaction(write=True) as db:
        ensure_tenant_project(db, tenant_id, project_id)
        if is_postgres():
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))", (f"amc-project-create|{project_id}",))
        row = db.execute(f"SELECT * FROM {table('project_workspaces')} WHERE project_id = ?", (project_id,)).fetchone()
        if row is not None:
            return {"workspace": _workspace_from_row(row), "created": False, "mirror": None}
        clash = db.execute(
            f"SELECT project_id FROM {table('project_workspaces')} WHERE tenant_id = ? AND slug = ?",
            (tenant_id, clean_slug),
        ).fetchone()
        if clash is not None:
            raise ProjectConflictError(f"slug {clean_slug!r} is already used by another project in this tenant")
        db.execute(
            f"""
            INSERT INTO {table('project_workspaces')}
            (project_id, tenant_id, slug, display_name, description, lifecycle_state, brand_id, brand_name,
             workspace_schema_version, manifest, manifest_hash, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, tenant_id, clean_slug, display_name, description, ProjectLifecycle.ACTIVE.value,
                brand_id, brand_name, manifest.schema_version, json_param(manifest.model_dump(mode="json")),
                digest, actor, now, now,
            ),
        )
        _append_event(
            db,
            tenant_id=tenant_id,
            project_id=project_id,
            event_type=ActivityType.PROJECT_CREATED,
            actor=actor,
            subject_ref=f"project:{project_id}",
            payload={"slug": clean_slug, "manifest_hash": digest},
        )
        _insert_memory_namespace(db, tenant_id=tenant_id, project_id=project_id, actor=actor, description=description, now=now)

    # The canonical engagement that hosts project-level artifacts in N4.
    engagement_id = project_engagement_id(project_id)
    if not get_engagement(engagement_id):
        create_engagement(
            engagement_id,
            tenant_id,
            project_id,
            f"Project workspace: {display_name}",
            "Canonical artifact graph for this project across all runs",
            status="active",
            metadata={"project_workspace": True},
        )

    mirror: dict[str, Any]
    try:
        root = project_root(_export_root(export_root), tenant_id, project_id)
        mirror = {"ok": True, **materialize_manifest(root, manifest), "root": str(root)}
    except Exception as exc:  # the mirror is reconstructable; never fail creation on it
        mirror = {"ok": False, "error": type(exc).__name__}
    return {"workspace": require_project_workspace(project_id), "created": True, "mirror": mirror}


def ensure_project_workspace(*, tenant_id: str, project_id: str, actor: str) -> ProjectWorkspaceV2:
    """Give a legacy project (one that only ever had runs) a workspace."""
    existing = get_project_workspace(project_id)
    if existing is not None:
        return existing
    try:
        result = create_project_workspace(
            tenant_id=tenant_id,
            project_id=project_id,
            actor=actor,
            display_name=project_id,
            slug=project_id,
        )
    except ProjectConflictError:
        # Slug collision with a differently-named project: fall back to the id.
        result = create_project_workspace(
            tenant_id=tenant_id,
            project_id=project_id,
            actor=actor,
            display_name=project_id,
            slug=f"{slugify(project_id)}-{uuid4().hex[:6]}",
        )
    return result["workspace"]


def transition_project(project_id: str, target: str, actor: str) -> ProjectWorkspaceV2:
    workspace = require_project_workspace(project_id)
    target_state = ProjectLifecycle(target).value
    if not can_transition(PROJECT_TRANSITIONS, workspace.lifecycle_state.value, target_state):
        raise ProjectConflictError(f"cannot move project from {workspace.lifecycle_state.value} to {target_state}")
    now = _now()
    with transaction(write=True) as db:
        cursor = db.execute(
            f"UPDATE {table('project_workspaces')} SET lifecycle_state = ?, updated_at = ? WHERE project_id = ? AND lifecycle_state = ?",
            (target_state, now, project_id, workspace.lifecycle_state.value),
        )
        if cursor.rowcount != 1:
            raise ProjectConflictError("project lifecycle changed concurrently")
        _append_event(
            db,
            tenant_id=workspace.tenant_id,
            project_id=project_id,
            event_type=ActivityType.MESSAGE,
            actor=actor,
            subject_ref=f"project:{project_id}",
            payload={"lifecycle_from": workspace.lifecycle_state.value, "lifecycle_to": target_state},
        )
    return require_project_workspace(project_id)


def _export_root(explicit: Optional[Path]) -> Path:
    if explicit is not None:
        return Path(explicit)
    from services.langgraph.agency.exporter import resolve_export_root

    return resolve_export_root()


def workspace_root_for(tenant_id: str, project_id: str, export_root: Optional[Path] = None) -> Path:
    return project_root(_export_root(export_root), tenant_id, project_id)


def _insert_memory_namespace(db: Any, *, tenant_id: str, project_id: str, actor: str, description: str, now: str) -> None:
    body = {"namespace": f"memory://{tenant_id}/{project_id}", "charter": description}
    db.execute(
        f"""
        INSERT INTO {table('memory_records')}
        (memory_id, tenant_id, project_id, thread_id, scope, authority, subject_key, body, source_refs, fresh_until, status, supersedes, content_hash, created_by, created_at)
        VALUES (?, ?, ?, NULL, 'M2_PROJECT', 'WORKING_CONTEXT', 'project.charter', ?, ?, NULL, 'ACTIVE', NULL, ?, ?, ?)
        """,
        (f"mem-{uuid4().hex}", tenant_id, project_id, json_param(body), json_param([]), sha256_bytes(canonical_json(body)), actor, now),
    )


# --------------------------------------------------------------------------
# Project activity stream
# --------------------------------------------------------------------------


def _event_from_row(row: Any) -> ProjectEvent:
    record = normalize_record(row)
    return ProjectEvent(
        event_id=record["event_id"],
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        sequence=int(record["sequence"]),
        event_type=record["event_type"],
        actor=record["actor"],
        thread_id=record.get("thread_id"),
        subject_ref=record.get("subject_ref"),
        payload=_dict(record.get("payload")),
        created_at=str(record["created_at"]),
    )


def _append_event(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    event_type: ActivityType | str,
    actor: str,
    payload: Optional[dict] = None,
    thread_id: Optional[str] = None,
    subject_ref: Optional[str] = None,
) -> ProjectEvent:
    if is_postgres():
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))", (f"amc-project-events|{project_id}",))
    row = db.execute(
        f"SELECT COALESCE(MAX(sequence), 0) AS seq FROM {table('project_events')} WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    sequence = int(row["seq"]) + 1
    event_id = f"pev-{uuid4().hex}"
    db.execute(
        f"""
        INSERT INTO {table('project_events')}
        (event_id, tenant_id, project_id, sequence, event_type, actor, thread_id, subject_ref, payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event_id, tenant_id, project_id, sequence, ActivityType(event_type).value, actor, thread_id, subject_ref, json_param(payload or {}), _now()),
    )
    inserted = db.execute(f"SELECT * FROM {table('project_events')} WHERE event_id = ?", (event_id,)).fetchone()
    return _event_from_row(inserted)


def append_project_event(
    *,
    tenant_id: str,
    project_id: str,
    event_type: ActivityType | str,
    actor: str,
    payload: Optional[dict] = None,
    thread_id: Optional[str] = None,
    subject_ref: Optional[str] = None,
) -> ProjectEvent:
    with transaction(write=True) as db:
        return _append_event(
            db,
            tenant_id=tenant_id,
            project_id=project_id,
            event_type=event_type,
            actor=actor,
            payload=payload,
            thread_id=thread_id,
            subject_ref=subject_ref,
        )


def list_project_events(project_id: str, *, after_sequence: int = 0, limit: int = 200, thread_id: Optional[str] = None) -> list[ProjectEvent]:
    query = f"SELECT * FROM {table('project_events')} WHERE project_id = ? AND sequence > ?"
    params: list[Any] = [project_id, after_sequence]
    if thread_id is not None:
        query += " AND thread_id = ?"
        params.append(thread_id)
    query += " ORDER BY sequence ASC LIMIT ?"
    params.append(max(1, min(limit, 1000)))
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [_event_from_row(row) for row in rows]


def project_snapshot(project_id: str) -> ProjectSnapshot:
    workspace = require_project_workspace(project_id)
    with transaction() as db:
        artifacts = db.execute(
            f"SELECT artifact_id, artifact_type, version, status, content_hash FROM {table('agency_artifacts')} WHERE project_id = ? ORDER BY artifact_id",
            (project_id,),
        ).fetchall()
        runs = db.execute(
            f"SELECT run_id FROM {table('runs')} WHERE project_id = ? ORDER BY created_at, run_id",
            (project_id,),
        ).fetchall()
        open_approvals = db.execute(
            f"SELECT COUNT(*) AS n FROM {table('approvals')} WHERE project_id = ? AND status = 'pending'",
            (project_id,),
        ).fetchone()
    heads = tuple(
        ArtifactHead(
            artifact_id=row["artifact_id"],
            artifact_type=row["artifact_type"],
            version=int(row["version"]),
            version_ref=f"{row['artifact_id']}:v{row['version']}",
            status=row["status"],
            content_hash=row["content_hash"],
        )
        for row in (normalize_record(item) for item in artifacts)
    )
    run_ids = tuple(normalize_record(row)["run_id"] for row in runs)
    stale = sum(1 for head in heads if head.status in {"invalidated", "review_required"})
    body = {
        "project_id": project_id,
        "lifecycle_state": workspace.lifecycle_state.value,
        "heads": [head.model_dump(mode="json") for head in heads],
        "runs": list(run_ids),
    }
    return ProjectSnapshot(
        project_id=project_id,
        tenant_id=workspace.tenant_id,
        lifecycle_state=workspace.lifecycle_state,
        artifact_heads=heads,
        run_ids=run_ids,
        open_approval_count=int(normalize_record(open_approvals)["n"]),
        stale_artifact_count=stale,
        snapshot_hash=sha256_bytes(canonical_json(body)),
    )


# --------------------------------------------------------------------------
# Storage objects
# --------------------------------------------------------------------------


def _storage_from_row(row: Any) -> StorageObject:
    record = normalize_record(row)
    return StorageObject(
        object_id=record["object_id"],
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        backend=record["backend"],
        storage_uri=record["storage_uri"],
        content_hash=record["content_hash"],
        byte_size=int(record["byte_size"]),
        mime_type=record["mime_type"],
        status=record["status"],
        created_at=str(record["created_at"]),
        verified_at=str(record["verified_at"]) if record.get("verified_at") else None,
    )


def register_storage_object(*, tenant_id: str, project_id: str, stored: StoredObject, mime_type: str) -> StorageObject:
    now = _now()
    with transaction(write=True) as db:
        row = db.execute(
            f"SELECT * FROM {table('storage_objects')} WHERE project_id = ? AND backend = ? AND content_hash = ?",
            (project_id, stored.backend.value, stored.content_hash),
        ).fetchone()
        if row is None:
            object_id = f"obj-{uuid4().hex}"
            db.execute(
                f"""
                INSERT INTO {table('storage_objects')}
                (object_id, tenant_id, project_id, backend, storage_uri, content_hash, byte_size, mime_type, status, created_at, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PRESENT', ?, ?)
                """,
                (object_id, tenant_id, project_id, stored.backend.value, stored.storage_uri, stored.content_hash, stored.byte_size, mime_type, now, now),
            )
            row = db.execute(f"SELECT * FROM {table('storage_objects')} WHERE object_id = ?", (object_id,)).fetchone()
        else:
            db.execute(
                f"UPDATE {table('storage_objects')} SET status = 'PRESENT', verified_at = ? WHERE object_id = ?",
                (now, normalize_record(row)["object_id"]),
            )
            row = db.execute(f"SELECT * FROM {table('storage_objects')} WHERE object_id = ?", (normalize_record(row)["object_id"],)).fetchone()
    return _storage_from_row(row)


def list_storage_objects(project_id: str) -> list[StorageObject]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('storage_objects')} WHERE project_id = ? ORDER BY created_at, object_id",
            (project_id,),
        ).fetchall()
    return [_storage_from_row(row) for row in rows]


def reconcile_storage_objects(project_id: str, adapter: StorageAdapter) -> dict[str, Any]:
    """Compare relational object records with what storage actually holds."""
    present: list[str] = []
    missing: list[str] = []
    now = _now()
    for item in list_storage_objects(project_id):
        if item.backend != adapter.backend:
            continue
        ok = adapter.exists(item.storage_uri)
        (present if ok else missing).append(item.object_id)
        with transaction(write=True) as db:
            db.execute(
                f"UPDATE {table('storage_objects')} SET status = ?, verified_at = ? WHERE object_id = ?",
                ("PRESENT" if ok else "MISSING", now, item.object_id),
            )
    return {"project_id": project_id, "present": present, "missing": missing, "reconciled_at": now}


# --------------------------------------------------------------------------
# Artifact graph v2
# --------------------------------------------------------------------------

_V2_KEYS = (
    "campaign_id", "media_type", "mime_type", "language", "locale", "channel", "dimensions",
    "duration_seconds", "parent_artifact_id", "master_artifact_id", "variant_of", "source_refs",
    "evidence_refs", "prompt_refs", "storage_uri", "preview_uri", "thumbnail_uri", "rights_ref",
    "provenance_ref",
)


def _artifact_key(record: dict) -> str:
    return str((record.get("metadata") or {}).get("artifact_key") or record["artifact_id"])


def _dependency_refs(artifact_id: str) -> tuple[str, ...]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT depends_on_artifact_id FROM {table('artifact_dependencies')} WHERE artifact_id = ? ORDER BY depends_on_artifact_id",
            (artifact_id,),
        ).fetchall()
    return tuple(normalize_record(row)["depends_on_artifact_id"] for row in rows)


def _approval_state(record: dict) -> str:
    approval = record.get("approval") or {}
    state = approval.get("state")
    if state in {"pending", "approved", "rejected", "stale"}:
        if state == "approved" and approval.get("version") not in (None, record["version"]):
            return "stale"
        return state
    return "none"


def artifact_metadata_v2(record: dict) -> ArtifactMetadataV2:
    metadata = record.get("metadata") or {}
    v2 = metadata.get("v2") or {}
    return ArtifactMetadataV2(
        artifact_id=record["artifact_id"],
        project_id=record["project_id"],
        artifact_key=_artifact_key(record),
        artifact_type=record["artifact_type"],
        owner_department=record["owner_department"],
        subtype=record.get("subtype"),
        version=int(record["version"]),
        version_ref=f"{record['artifact_id']}:v{record['version']}",
        dependency_refs=_dependency_refs(record["artifact_id"]),
        content_hash=record.get("content_hash"),
        status=record["status"],
        approval_state=_approval_state(record),
        **{key: (tuple(v2[key]) if isinstance(v2.get(key), list) else v2[key]) for key in _V2_KEYS if v2.get(key) is not None},
    )


def list_project_artifacts(
    project_id: str,
    *,
    media_type: Optional[str] = None,
    channel: Optional[str] = None,
    artifact_type: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 200,
) -> list[ArtifactMetadataV2]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('agency_artifacts')} WHERE project_id = ? ORDER BY updated_at DESC, artifact_id LIMIT ?",
            (project_id, max(1, min(limit, 1000))),
        ).fetchall()
    from services.langgraph.persistence.agency_kernel import _row_to_record

    results: list[ArtifactMetadataV2] = []
    needle = (query or "").strip().lower()
    for row in rows:
        meta = artifact_metadata_v2(_row_to_record(row, "agency_artifacts"))
        if media_type and meta.media_type != media_type:
            continue
        if channel and meta.channel != channel:
            continue
        if artifact_type and meta.artifact_type != artifact_type:
            continue
        if needle and needle not in f"{meta.artifact_key} {meta.subtype or ''} {meta.channel or ''}".lower():
            continue
        results.append(meta)
    return results


def _insert_version(
    db: Any,
    *,
    artifact: dict,
    change_kind: str,
    actor: str,
    restored_from_version: Optional[int] = None,
) -> None:
    db.execute(
        f"""
        INSERT INTO {table('artifact_versions')}
        (artifact_id, version, tenant_id, project_id, content_hash, content_location, semantic_fingerprint, metadata, change_kind, restored_from_version, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact["artifact_id"], int(artifact["version"]), artifact["tenant_id"], artifact["project_id"],
            artifact.get("content_hash"), artifact.get("content_location"), artifact.get("semantic_fingerprint"),
            json_param(artifact.get("metadata") or {}), change_kind, restored_from_version, actor, _now(),
        ),
    )


def _set_metadata(artifact_id: str, metadata: dict) -> None:
    with transaction(write=True) as db:
        db.execute(
            f"UPDATE {table('agency_artifacts')} SET metadata = ?, updated_at = ? WHERE artifact_id = ?",
            (json_param(metadata), _now(), artifact_id),
        )


def _store_text(adapter: StorageAdapter, tenant_id: str, project_id: str, text: str, mime_type: str) -> StorageObject:
    stored = adapter.put_bytes(tenant_id=tenant_id, project_id=project_id, data=text.encode("utf-8"))
    return register_storage_object(tenant_id=tenant_id, project_id=project_id, stored=stored, mime_type=mime_type)


def project_artifact_id(project_id: str, artifact_key: str) -> str:
    return f"art-{project_id}-{slugify(artifact_key, fallback='artifact')}"


def create_project_artifact(
    *,
    tenant_id: str,
    project_id: str,
    actor: str,
    artifact_key: str,
    artifact_type: str,
    adapter: StorageAdapter,
    content_text: Optional[str] = None,
    content_hash: Optional[str] = None,
    storage_uri: Optional[str] = None,
    subtype: Optional[str] = None,
    v2: Optional[dict] = None,
    depends_on: Iterable[str] = (),
) -> ArtifactMetadataV2:
    require_project_workspace(project_id)
    artifact_type = resolve_artifact_type(artifact_type).value
    owner = owning_department(artifact_type).value
    artifact_id = project_artifact_id(project_id, artifact_key)
    if get_artifact(artifact_id) is not None:
        raise ProjectConflictError(f"artifact key {artifact_key!r} already exists in this project")
    v2_meta = {key: value for key, value in dict(v2 or {}).items() if key in _V2_KEYS and value is not None}
    if content_text is not None:
        obj = _store_text(adapter, tenant_id, project_id, content_text, v2_meta.get("mime_type") or "text/plain")
        content_hash = obj.content_hash
        v2_meta["storage_uri"] = obj.storage_uri
        v2_meta.setdefault("media_type", "text")
    elif storage_uri is not None:
        v2_meta["storage_uri"] = storage_uri
    if not content_hash:
        raise ValueError("an artifact needs content_text, or a content_hash for externally stored bytes")
    created = create_artifact(
        artifact_id,
        project_engagement_id(project_id),
        tenant_id,
        project_id,
        artifact_type,
        owner,
        subtype=subtype,
        content_hash=content_hash,
        content_location=v2_meta.get("storage_uri"),
        semantic_fingerprint=content_hash,
        metadata={"artifact_key": artifact_key, "project_artifact": True, "v2": v2_meta},
    )
    with transaction(write=True) as db:
        _insert_version(db, artifact=created, change_kind="create", actor=actor)
        _append_event(
            db,
            tenant_id=tenant_id,
            project_id=project_id,
            event_type=ActivityType.ARTIFACT_CREATED,
            actor=actor,
            subject_ref=f"{artifact_id}:v1",
            payload={"artifact_id": artifact_id, "artifact_type": artifact_type, "artifact_key": artifact_key},
        )
    for upstream in depends_on:
        ensure_artifact_dependency(artifact_id, upstream)
    return artifact_metadata_v2(get_artifact(artifact_id))


def _scoped_artifact(artifact_id: str, project_id: str) -> dict:
    artifact = get_artifact(artifact_id)
    if artifact is None or artifact["project_id"] != project_id:
        raise ProjectNotFoundError(f"artifact {artifact_id} not found in project")
    return artifact


def revise_project_artifact(
    *,
    project_id: str,
    artifact_id: str,
    actor: str,
    adapter: StorageAdapter,
    expected_version: int,
    content_text: Optional[str] = None,
    content_hash: Optional[str] = None,
    storage_uri: Optional[str] = None,
    v2_patch: Optional[dict] = None,
    change_kind: str = "revise",
    restored_from_version: Optional[int] = None,
) -> dict[str, Any]:
    """New version of an artifact. Fails with StaleArtifactVersionError if the
    edit was based on anything but the current head."""
    artifact = _scoped_artifact(artifact_id, project_id)
    metadata = dict(artifact.get("metadata") or {})
    v2_meta = dict(metadata.get("v2") or {})
    for key, value in dict(v2_patch or {}).items():
        if key in _V2_KEYS:
            v2_meta[key] = value
    location = storage_uri
    if content_text is not None:
        obj = _store_text(adapter, artifact["tenant_id"], project_id, content_text, v2_meta.get("mime_type") or "text/plain")
        content_hash = obj.content_hash
        location = obj.storage_uri
    if location:
        v2_meta["storage_uri"] = location
    revision = record_artifact_revision(
        artifact_id,
        content_hash=content_hash,
        semantic_fingerprint=content_hash,
        content_location=location,
        expected_version=expected_version,
    )
    metadata["v2"] = v2_meta
    _set_metadata(artifact_id, metadata)
    updated = get_artifact(artifact_id)
    remediation: list[str] = []
    with transaction(write=True) as db:
        _insert_version(db, artifact=updated, change_kind=change_kind, actor=actor, restored_from_version=restored_from_version)
        for affected in revision["affected"]:
            if affected["status"] != "invalidated":
                continue
            downstream = get_artifact(affected["artifact_id"])
            if downstream is None or downstream["project_id"] != project_id:
                continue
            request_id = f"edit-{uuid4().hex}"
            db.execute(
                f"""
                INSERT INTO {table('artifact_edit_requests')}
                (request_id, tenant_id, project_id, artifact_id, base_version_ref, instruction, status, requested_by, created_at, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, NULL)
                """,
                (
                    request_id, updated["tenant_id"], project_id, downstream["artifact_id"],
                    f"{downstream['artifact_id']}:v{downstream['version']}",
                    f"Regenerate against {revision['changed_version_ref']} (upstream changed)",
                    "system:dependency-invalidation", _now(),
                ),
            )
            remediation.append(request_id)
        _append_event(
            db,
            tenant_id=updated["tenant_id"],
            project_id=project_id,
            event_type=ActivityType.ARTIFACT_UPDATED,
            actor=actor,
            subject_ref=revision["changed_version_ref"],
            payload={
                "artifact_id": artifact_id,
                "change_kind": change_kind,
                "affected": revision["affected"],
                "remediation_requests": remediation,
            },
        )
    return {
        "artifact": artifact_metadata_v2(updated),
        "changed_version_ref": revision["changed_version_ref"],
        "blast_radius": {
            "changed_ref": revision["changed_version_ref"],
            "affected": revision["affected"],
            "remediation_requests": remediation,
        },
    }


def _version_row(artifact_id: str, version: int) -> dict:
    with transaction() as db:
        row = db.execute(
            f"SELECT * FROM {table('artifact_versions')} WHERE artifact_id = ? AND version = ?",
            (artifact_id, version),
        ).fetchone()
    if row is None:
        raise ProjectNotFoundError(f"{artifact_id}:v{version} has no recorded history")
    record = normalize_record(row)
    record["metadata"] = _dict(record.get("metadata"))
    return record


def artifact_history(project_id: str, artifact_id: str) -> list[ArtifactVersionRecord]:
    _scoped_artifact(artifact_id, project_id)
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('artifact_versions')} WHERE artifact_id = ? ORDER BY version",
            (artifact_id,),
        ).fetchall()
    history = []
    for row in rows:
        record = normalize_record(row)
        history.append(ArtifactVersionRecord(
            artifact_id=record["artifact_id"],
            version=int(record["version"]),
            version_ref=f"{record['artifact_id']}:v{record['version']}",
            content_hash=record.get("content_hash"),
            content_location=record.get("content_location"),
            semantic_fingerprint=record.get("semantic_fingerprint"),
            change_kind=record["change_kind"],
            restored_from_version=record.get("restored_from_version"),
            created_by=record["created_by"],
            created_at=str(record["created_at"]),
        ))
    return history


def _read_text(adapter: StorageAdapter, uri: Optional[str]) -> Optional[str]:
    if not uri:
        return None
    try:
        data = adapter.get_bytes(uri)
    except Exception:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def compare_artifact_versions(*, project_id: str, artifact_id: str, from_version: int, to_version: int, adapter: StorageAdapter) -> ArtifactDiff:
    _scoped_artifact(artifact_id, project_id)
    old = _version_row(artifact_id, from_version)
    new = _version_row(artifact_id, to_version)
    old_v2 = (old["metadata"] or {}).get("v2") or {}
    new_v2 = (new["metadata"] or {}).get("v2") or {}
    metadata_changes = {
        key: {"from": old_v2.get(key), "to": new_v2.get(key)}
        for key in sorted(set(old_v2) | set(new_v2))
        if old_v2.get(key) != new_v2.get(key)
    }
    text_diff: tuple[str, ...] = ()
    old_text = _read_text(adapter, old.get("content_location"))
    new_text = _read_text(adapter, new.get("content_location"))
    if old_text is not None and new_text is not None:
        lines = list(difflib.unified_diff(
            old_text.splitlines(), new_text.splitlines(),
            fromfile=f"v{from_version}", tofile=f"v{to_version}", lineterm="",
        ))
        text_diff = tuple(lines[:_TEXT_DIFF_LIMIT])
    visual_diff = None
    if (old_v2.get("media_type") or new_v2.get("media_type")) in {"image", "video"}:
        # Metadata-level visual comparison only: no pixel diffing is claimed.
        visual_diff = {
            "method": "METADATA_ONLY",
            "dimensions": {"from": old_v2.get("dimensions"), "to": new_v2.get("dimensions")},
            "bytes_changed": old.get("content_hash") != new.get("content_hash"),
        }
    return ArtifactDiff(
        artifact_id=artifact_id,
        from_version_ref=f"{artifact_id}:v{from_version}",
        to_version_ref=f"{artifact_id}:v{to_version}",
        content_changed=old.get("content_hash") != new.get("content_hash"),
        location_changed=old.get("content_location") != new.get("content_location"),
        fingerprint_changed=old.get("semantic_fingerprint") != new.get("semantic_fingerprint"),
        metadata_changes=metadata_changes,
        text_diff=text_diff,
        visual_diff=visual_diff,
    )


def restore_artifact_version(*, project_id: str, artifact_id: str, version: int, actor: str, expected_version: int, adapter: StorageAdapter) -> dict[str, Any]:
    target = _version_row(artifact_id, version)
    return revise_project_artifact(
        project_id=project_id,
        artifact_id=artifact_id,
        actor=actor,
        adapter=adapter,
        expected_version=expected_version,
        content_hash=target.get("content_hash"),
        storage_uri=target.get("content_location"),
        v2_patch=((target.get("metadata") or {}).get("v2") or {}),
        change_kind="restore",
        restored_from_version=version,
    )


def branch_artifact(
    *,
    project_id: str,
    artifact_id: str,
    actor: str,
    branch_key: str,
    adapter: StorageAdapter,
    v2: Optional[dict] = None,
    content_text: Optional[str] = None,
) -> ArtifactMetadataV2:
    """Create a derivative of an artifact (one master, many derivatives)."""
    source = _scoped_artifact(artifact_id, project_id)
    source_v2 = dict((source.get("metadata") or {}).get("v2") or {})
    master = source_v2.get("master_artifact_id") or source["artifact_id"]
    branch_v2 = {**source_v2, **dict(v2 or {}), "variant_of": source["artifact_id"], "master_artifact_id": master, "parent_artifact_id": source["artifact_id"]}
    return create_project_artifact(
        tenant_id=source["tenant_id"],
        project_id=project_id,
        actor=actor,
        artifact_key=branch_key,
        artifact_type=source["artifact_type"],
        adapter=adapter,
        content_text=content_text,
        content_hash=None if content_text is not None else source.get("content_hash"),
        storage_uri=None if content_text is not None else source_v2.get("storage_uri"),
        subtype=source.get("subtype"),
        v2=branch_v2,
        depends_on=(source["artifact_id"],),
    )


def merge_branch(*, project_id: str, branch_id: str, into_id: str, actor: str, expected_version: int, adapter: StorageAdapter, replace_master: bool = False) -> dict[str, Any]:
    branch = _scoped_artifact(branch_id, project_id)
    target = _scoped_artifact(into_id, project_id)
    if branch["artifact_type"] != target["artifact_type"]:
        raise ProjectConflictError("a branch can only be merged into an artifact of the same type")
    branch_v2 = (branch.get("metadata") or {}).get("v2") or {}
    return revise_project_artifact(
        project_id=project_id,
        artifact_id=into_id,
        actor=actor,
        adapter=adapter,
        expected_version=expected_version,
        content_hash=branch.get("content_hash"),
        storage_uri=branch_v2.get("storage_uri"),
        v2_patch={"provenance_ref": f"merged_from:{branch_id}:v{branch['version']}"},
        change_kind="replace_master" if replace_master else "revise",
    )


def list_edit_requests(project_id: str, *, status: Optional[str] = None) -> list[dict]:
    query = f"SELECT * FROM {table('artifact_edit_requests')} WHERE project_id = ?"
    params: list[Any] = [project_id]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at, request_id"
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
    return [normalize_record(row) for row in rows]


# --------------------------------------------------------------------------
# Rights registry
# --------------------------------------------------------------------------


def _rights_from_row(row: Any) -> AssetRights:
    record = normalize_record(row)
    return AssetRights(
        rights_id=record["rights_id"],
        tenant_id=record["tenant_id"],
        project_id=record["project_id"],
        artifact_id=record["artifact_id"],
        license=record["license"],
        territory=record["territory"],
        usage_scope=record["usage_scope"],
        attribution=record.get("attribution"),
        source_ref=record.get("source_ref"),
        expires_at=str(record["expires_at"]) if record.get("expires_at") else None,
        status=record["status"],
        created_at=str(record["created_at"]),
    )


def register_asset_rights(
    *,
    project_id: str,
    artifact_id: str,
    license: str,
    territory: str = "UNSPECIFIED",
    usage_scope: str = "UNSPECIFIED",
    attribution: Optional[str] = None,
    source_ref: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> AssetRights:
    artifact = _scoped_artifact(artifact_id, project_id)
    rights_id = f"rights-{uuid4().hex}"
    with transaction(write=True) as db:
        db.execute(
            f"""
            INSERT INTO {table('asset_rights')}
            (rights_id, tenant_id, project_id, artifact_id, license, territory, usage_scope, attribution, source_ref, expires_at, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (rights_id, artifact["tenant_id"], project_id, artifact_id, license, territory, usage_scope, attribution, source_ref, expires_at, _now()),
        )
        row = db.execute(f"SELECT * FROM {table('asset_rights')} WHERE rights_id = ?", (rights_id,)).fetchone()
    metadata = dict(artifact.get("metadata") or {})
    v2_meta = dict(metadata.get("v2") or {})
    v2_meta["rights_ref"] = rights_id
    metadata["v2"] = v2_meta
    _set_metadata(artifact_id, metadata)
    return _rights_from_row(row)


def list_asset_rights(project_id: str) -> list[AssetRights]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('asset_rights')} WHERE project_id = ? ORDER BY created_at, rights_id",
            (project_id,),
        ).fetchall()
    return [_rights_from_row(row) for row in rows]


def rights_status(artifact_id: str, *, at: Optional[str] = None) -> dict[str, Any]:
    """``ok`` only when at least one active, unexpired rights record exists."""
    moment = datetime.fromisoformat(at) if at else datetime.now(timezone.utc)
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('asset_rights')} WHERE artifact_id = ? AND status = 'active'",
            (artifact_id,),
        ).fetchall()
    records = [_rights_from_row(row) for row in rows]
    valid = [
        record for record in records
        if record.expires_at is None or datetime.fromisoformat(record.expires_at) > moment
    ]
    if valid:
        return {"ok": True, "reason": None, "rights_ids": [record.rights_id for record in valid]}
    if records:
        return {"ok": False, "reason": "RIGHTS_EXPIRED", "rights_ids": [record.rights_id for record in records]}
    return {"ok": False, "reason": "RIGHTS_MISSING", "rights_ids": []}


# --------------------------------------------------------------------------
# Prompt ledger
# --------------------------------------------------------------------------

PROMPT_FIELDS = (
    "workstream", "invariant_set", "variation_axes", "concept_signature", "target_provider", "target_model",
    "exact_text", "negative_constraints", "source_refs", "evidence_refs", "brand_core_ref", "seed",
    "generation_config", "cost_tier", "quality_tier", "output_spec", "generated_artifact_refs", "approval_ref",
)


def record_prompt(
    *,
    tenant_id: str,
    project_id: str,
    actor: str,
    department: str,
    body: dict,
    prompt_id: Optional[str] = None,
    artifact_target: Optional[str] = None,
    family: Optional[str] = None,
    campaign_id: Optional[str] = None,
    status: str = "draft",
) -> dict[str, Any]:
    """Version a prompt. Identical content for an existing prompt is a no-op."""
    from services.langgraph.agency.kernel.ontology import resolve_department

    require_project_workspace(project_id)
    department = resolve_department(department).value
    clean = {key: body[key] for key in PROMPT_FIELDS if key in body}
    if not str(clean.get("exact_text") or "").strip():
        raise ValueError("a prompt record needs exact_text")
    prompt_hash = sha256_bytes(canonical_json({"department": department, "artifact_target": artifact_target, "family": family, **clean}))
    prompt_id = prompt_id or f"prm-{uuid4().hex[:16]}"
    with transaction(write=True) as db:
        latest = db.execute(
            f"SELECT * FROM {table('prompt_records')} WHERE prompt_id = ? ORDER BY version DESC LIMIT 1",
            (prompt_id,),
        ).fetchone()
        if latest is not None:
            latest_record = normalize_record(latest)
            if latest_record["project_id"] != project_id:
                raise ProjectConflictError("prompt belongs to a different project")
            if latest_record["prompt_hash"] == prompt_hash:
                latest_record["body"] = _dict(latest_record.get("body"))
                return {"prompt": latest_record, "created": False}
            version = int(latest_record["version"]) + 1
        else:
            version = 1
        db.execute(
            f"""
            INSERT INTO {table('prompt_records')}
            (prompt_id, version, tenant_id, project_id, artifact_target, department, family, campaign_id, status, prompt_hash, body, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (prompt_id, version, tenant_id, project_id, artifact_target, department, family, campaign_id, status, prompt_hash, json_param(clean), actor, _now()),
        )
        row = db.execute(f"SELECT * FROM {table('prompt_records')} WHERE prompt_id = ? AND version = ?", (prompt_id, version)).fetchone()
    record = normalize_record(row)
    record["body"] = _dict(record.get("body"))
    return {"prompt": record, "created": True}


def list_prompts(project_id: str, *, latest_only: bool = True) -> list[dict]:
    with transaction() as db:
        rows = db.execute(
            f"SELECT * FROM {table('prompt_records')} WHERE project_id = ? ORDER BY prompt_id, version",
            (project_id,),
        ).fetchall()
    records = []
    for row in rows:
        record = normalize_record(row)
        record["body"] = _dict(record.get("body"))
        records.append(record)
    if not latest_only:
        return records
    latest: dict[str, dict] = {}
    for record in records:
        latest[record["prompt_id"]] = record
    return sorted(latest.values(), key=lambda item: item["prompt_id"])


def materialize_prompt_ledger(project_id: str, export_root: Optional[Path] = None) -> dict[str, Any]:
    """Write 07_prompts/ALL_PROMPTS.md, prompt-index.json and prompt-lineage.json.

    These are exports of the database ledger, never an independent authority.
    """
    workspace = require_project_workspace(project_id)
    root = workspace_root_for(workspace.tenant_id, project_id, export_root)
    every_version = list_prompts(project_id, latest_only=False)
    latest = list_prompts(project_id)
    lines = [f"# All prompts — {workspace.display_name}", "", "Generated from the prompt ledger. Do not edit by hand.", ""]
    for record in latest:
        body = record["body"]
        lines += [
            f"## {record['prompt_id']} v{record['version']} ({record['status']})",
            f"- department: {record['department']}",
            f"- target: {record.get('artifact_target') or '—'}",
            f"- family: {record.get('family') or '—'}",
            f"- hash: `{record['prompt_hash']}`",
            "",
            "```text",
            str(body.get("exact_text") or ""),
            "```",
            "",
        ]
    index = [
        {key: record.get(key) for key in ("prompt_id", "version", "status", "department", "artifact_target", "family", "prompt_hash")}
        for record in latest
    ]
    lineage: dict[str, list[dict]] = {}
    for record in every_version:
        lineage.setdefault(record["prompt_id"], []).append({
            "version": record["version"],
            "prompt_hash": record["prompt_hash"],
            "generated_artifact_refs": record["body"].get("generated_artifact_refs") or [],
        })
    files = {
        "ALL_PROMPTS.md": "\n".join(lines).encode("utf-8"),
        "prompt-index.json": json.dumps(index, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        "prompt-lineage.json": json.dumps(lineage, indent=2, sort_keys=True).encode("utf-8") + b"\n",
    }
    written = []
    for name, data in files.items():
        path = folder_path(root, "07_prompts", name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append(str(path))
    return {"files": written, "prompt_count": len(latest)}


# --------------------------------------------------------------------------
# Runs are executions within projects
# --------------------------------------------------------------------------


def record_run_activity(
    *,
    tenant_id: str,
    project_id: str,
    run_id: str,
    actor: str,
    event_type: ActivityType | str,
    payload: Optional[dict] = None,
) -> ProjectEvent:
    """Append a run milestone to its project's activity stream, giving legacy
    run-only projects a workspace on first use."""
    ensure_project_workspace(tenant_id=tenant_id, project_id=project_id, actor=actor)
    return append_project_event(
        tenant_id=tenant_id,
        project_id=project_id,
        event_type=event_type,
        actor=actor,
        subject_ref=f"run:{run_id}",
        payload={"run_id": run_id, **dict(payload or {})},
    )


def mirror_run_export(*, tenant_id: str, project_id: str, run_id: str, workspace_export: Optional[dict]) -> Optional[dict]:
    """Dual-materialize a legacy run-first export under the project workspace.

    The legacy export stays where it is (artifact bindings point at it) and
    canonical artifact hashes are untouched: they are computed from payloads,
    not from either copy on disk. A mirror failure is reported, not raised.
    """
    if not workspace_export or not workspace_export.get("root_folder"):
        return None
    from services.langgraph.agency.project_os.workspace import mirror_legacy_export

    try:
        root = workspace_root_for(tenant_id, project_id)
        return {"ok": True, **mirror_legacy_export(project_dir=root, run_id=run_id, legacy_root=Path(workspace_export["root_folder"]))}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
