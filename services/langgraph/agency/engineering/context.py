"""Immutable, canonical context manifests for bounded engineering work."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import PurePosixPath

from .contracts import (
    ContextFile,
    ContextRecord,
    SourceSpan,
    context_manifest_hash,
    safe_repo_path,
)


class ContextIntegrityError(ValueError):
    """The supplied context bytes do not match their immutable manifest."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _text_files(files: Mapping[str, str | bytes]) -> dict[str, bytes]:
    if not isinstance(files, Mapping) or not files:
        raise ContextIntegrityError("EMPTY_CONTEXT", "at least one scoped text file is required")
    result: dict[str, bytes] = {}
    for raw_path, value in files.items():
        path = safe_repo_path(raw_path)
        if path in result:
            raise ContextIntegrityError("DUPLICATE_PATH", path)
        if isinstance(value, str):
            data = value.encode("utf-8")
        elif isinstance(value, bytes):
            data = value
        else:
            raise ContextIntegrityError("CONTENT_TYPE_REJECTED", path)
        if b"\x00" in data:
            raise ContextIntegrityError("BINARY_CONTENT_REJECTED", path)
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContextIntegrityError("NON_UTF8_CONTENT_REJECTED", path) from exc
        result[path] = data
    paths = set(result)
    for path in paths:
        for parent in PurePosixPath(path).parents:
            if parent.as_posix() != "." and parent.as_posix() in paths:
                raise ContextIntegrityError("PATH_ANCESTOR_CONFLICT", path)
    return result


def build_context_record(*, revision: str, files: Mapping[str, str | bytes], method: str,
                         omissions: tuple[str, ...] = (),
                         spans: Mapping[str, tuple[SourceSpan, ...]] | None = None) -> ContextRecord:
    """Build a content-addressed context manifest from a bounded text file map."""
    contents = _text_files(files)
    spans = spans or {}
    if set(spans) - set(contents):
        raise ContextIntegrityError("SPAN_PATH_MISSING", "source spans refer to a file outside the context")
    manifest = tuple(
        ContextFile(path=path, blob_hash=hashlib.sha256(data).hexdigest(), byte_size=len(data),
                    spans=tuple(spans.get(path, ())))
        for path, data in sorted(contents.items(), key=lambda item: item[0].encode("utf-8"))
    )
    byte_size = sum(item.byte_size for item in manifest)
    digest = context_manifest_hash(revision, manifest, method, omissions, byte_size)
    return ContextRecord(revision=revision, files=manifest, method=method, omissions=omissions,
                         byte_size=byte_size, context_hash=digest)


def verify_context_bytes(context: ContextRecord, files: Mapping[str, str | bytes]) -> None:
    """Require the supplied immutable base snapshot to match the context exactly."""
    contents = _text_files(files)
    expected_paths = {item.path for item in context.files}
    if set(contents) != expected_paths:
        raise ContextIntegrityError("CONTEXT_PATH_SET_MISMATCH", "snapshot has missing or unmanifested files")
    for entry in context.files:
        data = contents[entry.path]
        if len(data) != entry.byte_size or hashlib.sha256(data).hexdigest() != entry.blob_hash:
            raise ContextIntegrityError("CONTEXT_BLOB_MISMATCH", entry.path)
    calculated = context_manifest_hash(context.revision, context.files, context.method,
                                       context.omissions, context.byte_size)
    if calculated != context.context_hash:
        raise ContextIntegrityError("CONTEXT_MANIFEST_MISMATCH", "manifest hash is stale or tampered")


__all__ = ["ContextIntegrityError", "build_context_record", "verify_context_bytes"]
