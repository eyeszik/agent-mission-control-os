"""Storage authority: relational canon, object storage for bytes, mirror for humans.

Object storage is content-addressed (``sha256``). A write is idempotent: the
same bytes always land at the same URI, and a read re-verifies the hash so a
corrupted or substituted object is detected instead of served.

``LocalStorageAdapter`` is the zero-credential implementation used locally and
in CI. ``R2StorageAdapter`` describes the configured Cloudflare R2 binding but
cannot write: no reviewed R2 client is installed, so it reports
``UNVERIFIED_EXTERNAL_BINDING`` and fails closed. It never pretends a write
happened.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .vocabulary import StorageBackend
from .workspace import project_root, safe_segment

_HEX64 = frozenset("0123456789abcdef")


class StorageUnavailable(RuntimeError):
    """The configured storage backend cannot perform the operation."""


class StorageIntegrityError(RuntimeError):
    """Stored bytes no longer match their content hash."""


@dataclass(frozen=True)
class StoredObject:
    backend: StorageBackend
    storage_uri: str
    content_hash: str
    byte_size: int


class StorageAdapter(Protocol):
    backend: StorageBackend

    def put_bytes(self, *, tenant_id: str, project_id: str, data: bytes) -> StoredObject: ...

    def get_bytes(self, storage_uri: str) -> bytes: ...

    def exists(self, storage_uri: str) -> bool: ...

    def status(self) -> dict: ...


def _is_hash(value: str) -> bool:
    return len(value) == 64 and set(value) <= _HEX64


class LocalStorageAdapter:
    backend = StorageBackend.LOCAL

    def __init__(self, export_root: Path) -> None:
        self.export_root = Path(export_root)

    def _path(self, tenant_id: str, project_id: str, content_hash: str) -> Path:
        if not _is_hash(content_hash):
            raise StorageIntegrityError("content hash must be a sha256 hex digest")
        root = project_root(self.export_root, tenant_id, project_id)
        return root / ".amc" / "objects" / content_hash[:2] / content_hash

    @staticmethod
    def _parse(storage_uri: str) -> tuple[str, str, str]:
        prefix = "local://"
        if not storage_uri.startswith(prefix):
            raise StorageUnavailable("not a local storage URI")
        parts = storage_uri[len(prefix):].split("/")
        if len(parts) != 3:
            raise StorageUnavailable("malformed local storage URI")
        tenant_id, project_id, content_hash = parts
        safe_segment(tenant_id, label="tenant_id")
        safe_segment(project_id, label="project_id")
        return tenant_id, project_id, content_hash

    def put_bytes(self, *, tenant_id: str, project_id: str, data: bytes) -> StoredObject:
        content_hash = hashlib.sha256(data).hexdigest()
        path = self._path(tenant_id, project_id, content_hash)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{content_hash}.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return StoredObject(
            backend=self.backend,
            storage_uri=f"local://{tenant_id}/{project_id}/{content_hash}",
            content_hash=content_hash,
            byte_size=len(data),
        )

    def get_bytes(self, storage_uri: str) -> bytes:
        tenant_id, project_id, content_hash = self._parse(storage_uri)
        path = self._path(tenant_id, project_id, content_hash)
        if not path.is_file():
            raise FileNotFoundError(storage_uri)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != content_hash:
            raise StorageIntegrityError(f"object {storage_uri} failed hash verification")
        return data

    def exists(self, storage_uri: str) -> bool:
        tenant_id, project_id, content_hash = self._parse(storage_uri)
        return self._path(tenant_id, project_id, content_hash).is_file()

    def status(self) -> dict:
        return {"backend": self.backend.value, "available": True, "binding": "LOCAL_FILESYSTEM"}


class R2StorageAdapter:
    """Configuration-aware, fail-closed description of a Cloudflare R2 binding."""

    backend = StorageBackend.R2

    def __init__(self) -> None:
        self.bucket = (os.environ.get("AMC_R2_BUCKET") or "").strip()
        self.account_configured = bool((os.environ.get("AMC_R2_ACCOUNT_ID") or "").strip())
        self.credentials_configured = bool((os.environ.get("AMC_R2_ACCESS_KEY_ID") or "").strip()) and bool(
            (os.environ.get("AMC_R2_SECRET_ACCESS_KEY") or "").strip()
        )

    def _refuse(self) -> StorageUnavailable:
        return StorageUnavailable(
            "UNVERIFIED_EXTERNAL_BINDING: R2 object storage has no reviewed client adapter; "
            "use AMC_OBJECT_STORAGE_BACKEND=local until one is installed"
        )

    def put_bytes(self, *, tenant_id: str, project_id: str, data: bytes) -> StoredObject:
        raise self._refuse()

    def get_bytes(self, storage_uri: str) -> bytes:
        raise self._refuse()

    def exists(self, storage_uri: str) -> bool:
        raise self._refuse()

    def status(self) -> dict:
        # Presence booleans only; never echo a credential value.
        return {
            "backend": self.backend.value,
            "available": False,
            "binding": "UNVERIFIED_EXTERNAL_BINDING",
            "bucket_configured": bool(self.bucket),
            "account_configured": self.account_configured,
            "credentials_configured": self.credentials_configured,
        }


def object_storage_backend() -> StorageBackend:
    value = (os.environ.get("AMC_OBJECT_STORAGE_BACKEND") or "local").strip().upper()
    try:
        return StorageBackend(value)
    except ValueError as exc:
        raise StorageUnavailable(f"Unsupported AMC_OBJECT_STORAGE_BACKEND={value.lower()!r}") from exc


def resolve_storage_adapter(export_root: Path) -> StorageAdapter:
    if object_storage_backend() is StorageBackend.R2:
        return R2StorageAdapter()
    return LocalStorageAdapter(export_root)
