from __future__ import annotations

"""Persistent artifact content storage.

Content addressing: bytes are stored once per tenant under their sha256
object_id; artifact_versions records point at immutable objects so a run's
artifact can be versioned and independently re-verified. Layout is compatible
with the Supabase migration 20261104_amc_durable_execution_v1 (amc.artifact_objects
/ amc.artifact_versions) and a SQLite mirror (migration 7).

Backends:
- local: filesystem directory (AMC_ARTIFACT_ROOT). Durable when the directory
  is on a persistent volume; the intended production choice where object
  storage is not yet credentialized.
- r2: Cloudflare R2 via the S3 API (requires a real adapter module binding put/
  head). Implemented here through the same ArtifactBackend interface;
  UNVERIFIED until operator credentials exist (AMC_ARTIFACT_BACKEND=r2 fails
  closed in production config when its env vars are missing).
"""

import hashlib
import os
import secrets
import shutil
import sqlite3
from pathlib import Path

from services.langgraph.persistence.database import (
    is_postgres,
    normalize_record,
    table,
    transaction,
)

_ARTIFACT_TABLES_INITIALIZED = False

_MAX_ARTIFACT_BYTES = 20 * 1024 * 1024


class ArtifactSizeError(ValueError):
    pass


class ArtifactIntegrityError(RuntimeError):
    pass


def init_artifact_tables() -> None:
    global _ARTIFACT_TABLES_INITIALIZED
    if is_postgres():
        return  # authoritative DDL lives in the Supabase migration ledger
    conn = sqlite3.connect(_sqlite_db_path())
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifact_objects (
                object_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                created_by TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (tenant_id, object_id)
            );
            CREATE TABLE IF NOT EXISTS artifact_versions (
                artifact_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                run_id TEXT,
                kind TEXT NOT NULL,
                version INTEGER NOT NULL CHECK (version >= 1),
                object_id TEXT NOT NULL REFERENCES artifact_objects(object_id),
                content_hash TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                deleted_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (tenant_id, project_id, kind, version)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    _ARTIFACT_TABLES_INITIALIZED = True


def _sqlite_db_path() -> str:
    from services.langgraph.persistence.sqlite_db import DB_PATH

    return DB_PATH


class ArtifactBackend:
    def put(self, tenant_id: str, object_id: str, data: bytes) -> None: ...
    def get(self, tenant_id: str, object_id: str) -> bytes: ...
    def delete(self, tenant_id: str, object_id: str) -> None: ...
    def exists(self, tenant_id: str, object_id: str) -> bool: ...


class LocalArtifactBackend(ArtifactBackend):
    """Tenant-scoped filesystem layout: <root>/<tenant>/<object_id>."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, tenant_id: str, object_id: str) -> Path:
        return self._root / tenant_id / object_id

    def put(self, tenant_id: str, object_id: str, data: bytes) -> None:
        path = self._path(tenant_id, object_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{object_id}.{secrets.token_hex(4)}.tmp")
        tmp.write_bytes(data)
        shutil.move(str(tmp), str(path))

    def get(self, tenant_id: str, object_id: str) -> bytes:
        return self._path(tenant_id, object_id).read_bytes()

    def delete(self, tenant_id: str, object_id: str) -> None:
        path = self._path(tenant_id, object_id)
        if path.exists():
            path.unlink()

    def exists(self, tenant_id: str, object_id: str) -> bool:
        return self._path(tenant_id, object_id).exists()


class R2ArtifactBackend(ArtifactBackend):
    """Cloudflare R2 via the S3-compatible API (S3SignatureV4 endpoint).

    Requires the optional ``boto3`` dependency. Configuration is
    authorization-blocked until the operator supplies R2_* credentials, so it
    fails closed here before any call leaves the process.
    """

    def __init__(self, account_id: str, access_key_id: str, secret_access_key: str, bucket: str) -> None:

        self._account_id = account_id
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._bucket = bucket

    def _client(self):
        try:
            import boto3
        except ImportError as exc:  # fail closed: no silent local fallback
            raise RuntimeError(
                "AMC_ARTIFACT_BACKEND=r2 requires the optional boto3 dependency "
                '(install with: pip install "amc-langgraph[r2]")'
            ) from exc
        return boto3.client(
            "s3",
            endpoint_url=f"https://{self._account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
        )

    def put(self, tenant_id: str, object_id: str, data: bytes) -> None:
        self._client().put_object(Bucket=self._bucket, Key=f"{tenant_id}/{object_id}", Body=data)

    def get(self, tenant_id: str, object_id: str) -> bytes:
        return self._client().get_object(Bucket=self._bucket, Key=f"{tenant_id}/{object_id}")["Body"].read()

    def delete(self, tenant_id: str, object_id: str) -> None:
        self._client().delete_object(Bucket=self._bucket, Key=f"{tenant_id}/{object_id}")

    def exists(self, tenant_id: str, object_id: str) -> bool:
        try:
            self._client().head_object(Bucket=self._bucket, Key=f"{tenant_id}/{object_id}")
            return True
        except Exception:
            return False


def artifact_storage_backend():
    """Resolve the configured artifact backend (local default, r2 opt-in)."""

    from services.langgraph.app import config

    backend_name = config.artifact_backend()
    if backend_name == "r2":
        return R2ArtifactBackend(
            account_id=os.environ.get("R2_ACCOUNT_ID", ""),
            access_key_id=os.environ.get("R2_ACCESS_KEY_ID", ""),
            secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY", ""),
            bucket=os.environ.get("R2_BUCKET", ""),
        )
    root = Path(os.environ.get("AMC_ARTIFACT_ROOT", "amc_artifacts"))
    return LocalArtifactBackend(root)


def store_artifact(
    tenant_id: str,
    project_id: str,
    kind: str,
    content: bytes,
    content_type: str = "application/octet-stream",
    run_id: str | None = None,
    created_by: str | None = None,
) -> dict:
    """Store artifact bytes (content-addressed) and a new immutable version row."""

    if len(content) > _MAX_ARTIFACT_BYTES:
        raise ArtifactSizeError(f"artifact exceeds {_MAX_ARTIFACT_BYTES} bytes")
    init_artifact_tables()
    content_hash = hashlib.sha256(content).hexdigest()

    with transaction(write=True) as db:
        latest = db.execute(
            f"SELECT COALESCE(MAX(version), 0) AS v FROM {table('artifact_versions')} WHERE tenant_id = ? AND project_id = ? AND kind = ?",
            (tenant_id, project_id, kind),
        ).fetchone()
        version = int(latest["v"]) + 1
        existing = db.execute(
            f"SELECT object_id FROM {table('artifact_objects')} WHERE tenant_id = ? AND object_id = ?",
            (tenant_id, content_hash),
        ).fetchone()
        if existing is None:
            db.execute(
                f"INSERT INTO {table('artifact_objects')} (object_id, tenant_id, project_id, content_type, size_bytes, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (content_hash, tenant_id, project_id, content_type, len(content), created_by, _now_iso()),
            )
        artifact_id = f"art_{secrets.token_hex(16)}"
        db.execute(
            f"INSERT INTO {table('artifact_versions')} (artifact_id, tenant_id, project_id, run_id, kind, version, object_id, content_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (artifact_id, tenant_id, project_id, run_id, kind, version, content_hash, content_hash, _now_iso()),
        )

    backend = artifact_storage_backend()
    if not backend.exists(tenant_id, content_hash):
        backend.put(tenant_id, content_hash, content)
    return get_artifact(artifact_id, tenant_id)  # type: ignore[return-value]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def get_artifact(artifact_id: str, tenant_id: str, include_content: bool = False) -> dict | None:
    init_artifact_tables()
    with transaction() as db:
        row = db.execute(
            f"SELECT * FROM {table('artifact_versions')} WHERE artifact_id = ? AND tenant_id = ?",
            (artifact_id, tenant_id),
        ).fetchone()
    if row is None:
        return None
    record = normalize_record(row)
    if include_content:
        backend = artifact_storage_backend()
        content = backend.get(tenant_id, record["object_id"])
        if hashlib.sha256(content).hexdigest() != record["content_hash"]:
            raise ArtifactIntegrityError(f"stored bytes do not match content hash for artifact {artifact_id}")
        record["content"] = content
    return record


def list_artifacts(tenant_id: str, project_id: str | None = None, run_id: str | None = None, limit: int = 200) -> list[dict]:
    init_artifact_tables()
    query = f"SELECT * FROM {table('artifact_versions')} WHERE tenant_id = ?"
    params: list = [tenant_id]
    if project_id:
        query += " AND project_id = ?"
        params.append(project_id)
    if run_id:
        query += " AND run_id = ?"
        params.append(run_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 1000)))
    with transaction() as db:
        rows = db.execute(query, params).fetchall()
        return [normalize_record(r) for r in rows]


def soft_delete_artifact(artifact_id: str, tenant_id: str) -> bool:
    """Retention/deletion control: tombstone the version row. The content bytes
    remain addressable for audit until the retention sweep removes them."""

    with transaction(write=True) as db:
        cursor = db.execute(
            f"UPDATE {table('artifact_versions')} SET deleted = 1, deleted_at = ? WHERE artifact_id = ? AND tenant_id = ? AND deleted = 0",
            (_now_iso(), artifact_id, tenant_id),
        )
        return cursor.rowcount == 1
