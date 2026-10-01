"""Project-first workspace mirror.

Layout (adapting the legacy run-first ``<root>/<brand>-<run>/``)::

    <AMC_EXPORT_ROOT>/projects/<tenant>/<project>/
        00_admin/ ... 21_archive/          semantic folders, created lazily
        .amc/runs/<run_id>/                 machine materializations per run
        .amc/manifests/project-manifest.json
        .amc/objects/<hh>/<sha256>          local object storage

The mirror is a materialized view. Nothing reads it back as authority: the
relational store owns identity, versions, lineage and approvals, and every
file here can be regenerated from that state.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

from .models import ProjectManifest
from .vocabulary import SYSTEM_FOLDERS, WORKSPACE_FOLDERS, ProjectLifecycle

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

# Legacy run-first export subpaths → project semantic folders. Order matters:
# the first matching prefix wins.
LEGACY_FOLDER_MAP: tuple[tuple[str, str], ...] = (
    ("business/", "03_strategy/business/"),
    ("branding/design-system/", "06_design/design-system/"),
    ("branding/rendered/", "08_creative/rendered/"),
    ("branding/prompts/", "07_prompts/run-prompts/"),
    ("branding/", "04_brand/"),
    ("design-system/", "06_design/design-system/"),
)


class WorkspacePathError(ValueError):
    """A path segment could escape the project root or is not addressable."""


def safe_segment(value: str, *, label: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_SEGMENT.match(text) or text in {".", ".."}:
        raise WorkspacePathError(f"{label} is not a safe workspace path segment")
    return text


def slugify(value: str, *, fallback: str = "project") -> str:
    slug = _SLUG_STRIP.sub("-", (value or "").lower()).strip("-")[:64].strip("-")
    return slug or fallback


def projects_base(export_root: Path) -> Path:
    return Path(export_root) / "projects"


def project_root(export_root: Path, tenant_id: str, project_id: str) -> Path:
    return projects_base(export_root) / safe_segment(tenant_id, label="tenant_id") / safe_segment(project_id, label="project_id")


def _contained(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise WorkspacePathError("path escapes the project workspace")
    return candidate


def folder_path(root: Path, folder: str, *parts: str) -> Path:
    if folder not in WORKSPACE_FOLDERS:
        raise WorkspacePathError(f"unknown workspace folder {folder!r}")
    clean = [safe_segment(part, label="path segment") for part in parts]
    return _contained(root, root.joinpath(folder, *clean))


def system_path(root: Path, folder: str, *parts: str) -> Path:
    if folder not in SYSTEM_FOLDERS:
        raise WorkspacePathError(f"unknown system folder {folder!r}")
    clean = [safe_segment(part, label="path segment") for part in parts]
    return _contained(root, root.joinpath(".amc", folder, *clean))


def run_root(root: Path, run_id: str) -> Path:
    return system_path(root, "runs", run_id)


def canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    *,
    project_id: str,
    tenant_id: str,
    slug: str,
    display_name: str,
    lifecycle_state: ProjectLifecycle | str = ProjectLifecycle.ACTIVE,
    brand_id: str | None = None,
) -> ProjectManifest:
    return ProjectManifest(
        project_id=project_id,
        tenant_id=tenant_id,
        slug=slug,
        display_name=display_name,
        brand_id=brand_id,
        lifecycle_state=ProjectLifecycle(lifecycle_state),
        folders=WORKSPACE_FOLDERS,
        system_folders=SYSTEM_FOLDERS,
        memory_namespace=f"memory://{tenant_id}/{project_id}",
        artifact_index_ref=f"db://agency_artifacts?project_id={project_id}",
        source_registry_ref=f"db://knowledge_items?project_id={project_id}",
        rights_registry_ref=f"db://asset_rights?project_id={project_id}",
    )


def manifest_hash(manifest: ProjectManifest) -> str:
    return sha256_bytes(canonical_json(manifest.model_dump(mode="json")))


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def materialize_manifest(root: Path, manifest: ProjectManifest) -> dict[str, str]:
    """Write the manifest mirror and a human README. Idempotent."""
    body = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True).encode("utf-8") + b"\n"
    manifest_file = system_path(root, "manifests", "project-manifest.json")
    _write_bytes_atomic(manifest_file, body)
    readme = folder_path(root, "00_admin", "PROJECT.md")
    readme_text = "\n".join([
        f"# {manifest.display_name}",
        "",
        f"- project_id: `{manifest.project_id}`",
        f"- tenant_id: `{manifest.tenant_id}`",
        f"- lifecycle: {manifest.lifecycle_state.value}",
        "",
        manifest.authority_note,
        "",
        "Folders are created when something is first written into them.",
        "",
    ])
    _write_bytes_atomic(readme, readme_text.encode("utf-8"))
    return {"manifest": str(manifest_file), "readme": str(readme), "manifest_hash": manifest_hash(manifest)}


def existing_folders(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return [folder for folder in WORKSPACE_FOLDERS if (root / folder).is_dir()]


def map_legacy_relative(relative: str) -> str:
    """Map a legacy run-first export path to its project-workspace location."""
    for prefix, target in LEGACY_FOLDER_MAP:
        if relative.startswith(prefix):
            return target + relative[len(prefix):]
    return relative


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def mirror_legacy_export(*, project_dir: Path, run_id: str, legacy_root: Path) -> dict[str, Any]:
    """Dual-materialize a legacy run-first export into the project workspace.

    The legacy export is left untouched (existing bindings point at it). Every
    file is copied into its semantic project folder and its hash is verified
    against the source, so the mirror can never silently diverge from what the
    canonical artifact bindings describe. ``workspace-package.json`` belongs to
    the run, so it lands under ``.amc/runs/<run_id>/``.
    """
    legacy_root = Path(legacy_root)
    if not legacy_root.is_dir():
        raise WorkspacePathError("legacy export root does not exist")
    run_dir = run_root(project_dir, run_id)
    entries: list[dict[str, str]] = []
    mismatches: list[str] = []
    for source in _iter_files(legacy_root):
        relative = source.relative_to(legacy_root).as_posix()
        if relative == "workspace-package.json":
            target = run_dir / "workspace-package.json"
        else:
            target = _contained(project_dir, project_dir / map_legacy_relative(relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        source_hash = sha256_file(source)
        target_hash = sha256_file(target)
        if source_hash != target_hash:
            mismatches.append(relative)
        entries.append({"legacy_path": relative, "project_path": target.relative_to(project_dir).as_posix(), "sha256": target_hash})
    index = {
        "run_id": run_id,
        "legacy_root": str(legacy_root),
        "files": entries,
        "hashes_verified": not mismatches,
        "mismatches": mismatches,
    }
    _write_bytes_atomic(run_dir / "mirror-index.json", json.dumps(index, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return {
        "project_root": str(project_dir),
        "run_root": str(run_dir),
        "file_count": len(entries),
        "hashes_verified": not mismatches,
        "mismatches": mismatches,
        "folders": existing_folders(project_dir),
    }


def tree(root: Path, *, max_entries: int = 500) -> list[dict[str, Any]]:
    """Flat, bounded listing of the human mirror (system folders excluded)."""
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for folder in WORKSPACE_FOLDERS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if len(rows) >= max_entries:
                return rows
            if path.is_file():
                rows.append({
                    "folder": folder,
                    "path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                })
    return rows
