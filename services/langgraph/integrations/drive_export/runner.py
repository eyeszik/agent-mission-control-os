"""Export runner: manifest → delta zip → Google Drive → verify → Notion record.

``RUNNER_MODE`` selects what happens:

- ``dry_run`` (default): build the zip, manifest, graph index and audit record
  under the output directory. No credential is read and no network call is
  made. The previous manifest is the one the last dry run wrote locally.
- ``local`` / ``ci``: also upload to Google Drive and record the export in
  Notion. Both modes require ``GOOGLE_SA_JSON`` and ``DRIVE_PARENT_FOLDER_ID``;
  a missing value is a configuration error, never a silent skip.

An upload is identified by its manifest hash, stored in the Drive file's
``appProperties``. A rerun for unchanged content finds the existing file and
uploads nothing; a rerun after a Notion failure records the existing file.
Each upload is read back and its MD5, size and manifest hash compared with the
local zip before it is recorded anywhere.
"""

from __future__ import annotations

import getpass
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from . import manifest as mf
from .google_drive import DriveClient, ServiceAccount
from .notion import NotionClient, bookmark_block, database_properties, heading_block, paragraph_blocks, rich_text

VALID_MODES = ("dry_run", "local", "ci")
UPLOAD_MODES = ("local", "ci")
ZIP_MIME = "application/zip"
ENCRYPTED_MIME = "application/octet-stream"
JSON_MIME = "application/json"
LOCK_STALE_SECONDS = 2 * 60 * 60
NOTION_PROMPT_SNIPPET_CHARS = 2048


class ExportConfigError(ValueError):
    """The runner cannot start: a required setting is missing or invalid."""


class ExportVerificationError(RuntimeError):
    """An upload's read-back did not match the local file."""


@dataclass(frozen=True)
class ExportConfig:
    mode: str
    project_path: Path
    project_id: str
    out_dir: Path
    actor: str
    brand_id: str | None = None
    commit_sha: str | None = None
    upload_public: bool = False
    full: bool = False
    drive_parent_folder_id: str | None = None
    google_sa_json: str | None = field(default=None, repr=False)
    google_impersonate_subject: str | None = None
    notion_token: str | None = field(default=None, repr=False)
    notion_database_id: str | None = None
    notion_parent_page_id: str | None = None
    encryption_key: bytes | None = field(default=None, repr=False)
    retention_full_keep: int | None = None

    @property
    def uploads(self) -> bool:
        return self.mode in UPLOAD_MODES

    @property
    def notion_enabled(self) -> bool:
        return bool(self.notion_token)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        project_path: str | None = None,
        project_id: str | None = None,
        brand_id: str | None = None,
        out_dir: str | None = None,
        full: bool = False,
    ) -> "ExportConfig":
        environ = os.environ if environ is None else environ

        def _env(name: str) -> str:
            return (environ.get(name) or "").strip()

        mode = (_env("RUNNER_MODE") or "dry_run").lower()
        if mode not in VALID_MODES:
            raise ExportConfigError(f"RUNNER_MODE must be one of {', '.join(VALID_MODES)}")
        path_value = project_path or _env("AMC_PROJECT_PATH")
        if not path_value:
            raise ExportConfigError("set AMC_PROJECT_PATH or pass --project-path")
        root = Path(path_value).expanduser().resolve()
        if not root.is_dir():
            raise ExportConfigError("AMC_PROJECT_PATH is not a directory")
        pid = (project_id or root.name).strip()
        if not pid or len(pid) > 100 or any(c in pid for c in "/\\'\""):
            raise ExportConfigError("project id must be 1-100 characters without slashes or quotes")
        public = _env("UPLOAD_PUBLIC").lower()
        if public not in ("", "true", "false"):
            raise ExportConfigError("UPLOAD_PUBLIC must be true or false")
        key_value = _env("EXPORT_ENCRYPTION_KEY")
        try:
            key = mf.decode_encryption_key(key_value) if key_value else None
        except ValueError as exc:
            raise ExportConfigError(str(exc)) from None
        keep_value = _env("EXPORT_RETENTION_FULL_KEEP")
        if keep_value and (not keep_value.isdigit() or int(keep_value) < 1):
            raise ExportConfigError("EXPORT_RETENTION_FULL_KEEP must be a positive integer")
        config = cls(
            mode=mode,
            project_path=root,
            project_id=pid,
            out_dir=Path(out_dir).expanduser().resolve() if out_dir else Path.cwd() / ".amc-export",
            actor=_env("GITHUB_ACTOR") or getpass.getuser(),
            brand_id=brand_id or None,
            commit_sha=_env("REPO_COMMIT_SHA") or None,
            upload_public=public == "true",
            full=full,
            drive_parent_folder_id=_env("DRIVE_PARENT_FOLDER_ID") or None,
            google_sa_json=_env("GOOGLE_SA_JSON") or None,
            google_impersonate_subject=_env("GOOGLE_IMPERSONATE_SUBJECT") or None,
            notion_token=_env("NOTION_TOKEN") or None,
            notion_database_id=_env("NOTION_DATABASE_ID") or None,
            notion_parent_page_id=_env("NOTION_PARENT_PAGE_ID") or None,
            encryption_key=key,
            retention_full_keep=int(keep_value) if keep_value else None,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.uploads:
            if not self.google_sa_json:
                raise ExportConfigError(f"RUNNER_MODE={self.mode} uploads to Google Drive and needs GOOGLE_SA_JSON")
            if not self.drive_parent_folder_id:
                raise ExportConfigError(
                    f"RUNNER_MODE={self.mode} needs DRIVE_PARENT_FOLDER_ID (a folder in a shared drive "
                    "that the service account can edit)")
            if self.notion_enabled and not (self.notion_database_id or self.notion_parent_page_id):
                raise ExportConfigError("NOTION_TOKEN is set; also set NOTION_DATABASE_ID or NOTION_PARENT_PAGE_ID")


@dataclass
class ExportResult:
    status: str
    project_id: str
    mode: str
    manifest_hash: str
    artifacts_count: int
    export_kind: str | None = None
    files_in_zip: int = 0
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    encrypted: bool = False
    zip_path: str | None = None
    drive_file_id: str | None = None
    drive_web_view_link: str | None = None
    notion_page_id: str | None = None
    trashed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _timestamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class _Lock:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> "_Lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime > LOCK_STALE_SECONDS:
            self.path.unlink(missing_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ExportConfigError(f"another export of this project is running (lock {self.path})") from None
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        return self

    def __exit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)


def _state_path(config: ExportConfig) -> Path:
    return config.out_dir / "state" / f"{config.project_id}.latest-manifest.json"


def _sidecar_bytes(document: dict, key: bytes | None) -> bytes:
    data = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
    return mf.encrypt_bytes(data, key) if key else data


def _parse_sidecar(blob: bytes, key: bytes | None) -> dict:
    if blob.startswith(mf.ENCRYPTED_MAGIC):
        if not key:
            raise ExportConfigError("the previous manifest on Drive is encrypted; set EXPORT_ENCRYPTION_KEY")
        blob = mf.decrypt_bytes(blob, key)
    return json.loads(blob.decode("utf-8"))


def run_export(
    config: ExportConfig,
    *,
    drive: DriveClient | None = None,
    notion: NotionClient | None = None,
    now: datetime | None = None,
) -> ExportResult:
    now = now or datetime.now(timezone.utc)
    collected = mf.collect_manifest(config.project_path)
    entries = collected.entries
    if not entries:
        raise ExportConfigError("the project path contains no exportable files")
    mhash = mf.manifest_hash(entries)
    result = ExportResult("PENDING", config.project_id, config.mode, mhash, len(entries),
                          skipped=list(collected.skipped), encrypted=config.encryption_key is not None)

    with _Lock(config.out_dir / "locks" / f"{config.project_id}.lock"):
        if not config.uploads:
            previous = json.loads(_state_path(config).read_text()) if _state_path(config).is_file() else None
            return _package(config, collected, mhash, previous, result, now, drive=None, folder_id=None)

        owns_drive = drive is None
        drive = drive or DriveClient(ServiceAccount.from_value(config.google_sa_json or "",
                                                               subject=config.google_impersonate_subject))
        owns_notion = notion is None and config.notion_enabled
        notion = notion or (NotionClient(config.notion_token or "") if config.notion_enabled else None)
        try:
            folder_id = drive.ensure_folder(config.project_id, config.drive_parent_folder_id or "")
            existing = drive.find_by_app_properties(
                {"amc_project_id": config.project_id, "amc_kind": "export", "amc_manifest_hash": mhash},
                parent_id=folder_id)
            if existing:
                found = existing[0]
                result.status = "ALREADY_UPLOADED"
                result.export_kind = found.get("appProperties", {}).get("amc_export_kind")
                result.drive_file_id = found["id"]
                result.drive_web_view_link = found.get("webViewLink")
                result.notion_page_id = _record_in_notion(config, notion, result, now, graph=None)
                return result
            previous = None
            manifests = drive.find_by_app_properties(
                {"amc_project_id": config.project_id, "amc_kind": "manifest"}, parent_id=folder_id)
            if manifests:
                previous = _parse_sidecar(drive.download(manifests[0]["id"]), config.encryption_key)
            return _package(config, collected, mhash, previous, result, now,
                            drive=drive, folder_id=folder_id, notion=notion)
        finally:
            if owns_drive:
                drive.close()
            if owns_notion and notion is not None:
                notion.close()


def _package(config, collected, mhash, previous, result, now, *, drive, folder_id, notion=None) -> ExportResult:
    entries = collected.entries
    previous_shas = mf.previous_shas(previous)
    base_hash = previous.get("manifest_hash") if previous else None
    if previous and base_hash == mhash and not config.full and drive is None:
        result.status = "NO_CHANGES"
        return result
    # On Drive an unchanged manifest with no export left (for example trashed by
    # hand) is uploaded again as a full export, so the latest state stays restorable.
    is_full = config.full or not previous or base_hash == mhash
    files = entries if is_full else mf.delta(entries, previous_shas)
    result.removed = list(mf.removed_paths(entries, previous_shas)) if previous else []
    result.export_kind = "full" if is_full else "delta"
    result.files_in_zip = len(files)

    graph = mf.build_graph_index(config.project_path, entries)
    manifest_doc = {**mf.manifest_document(entries), "manifest_hash": mhash, "project_id": config.project_id}
    audit = {
        "schema": "amc-export-audit/v1",
        "actor": config.actor,
        "commit_sha": config.commit_sha,
        "created_at": now.astimezone(timezone.utc).isoformat(),
        "mode": config.mode,
        "project_id": config.project_id,
        "brand_id": config.brand_id,
        "manifest_hash": mhash,
        "base_manifest_hash": base_hash,
        "export_kind": result.export_kind,
        "files_in_zip": [e.path for e in files],
        "removed_since_base": result.removed,
        "skipped": result.skipped,
        "signature": None,  # unsigned: no signing key custody is configured for this export path
    }
    stem = f"project-{config.project_id}-{(config.commit_sha or 'nosha')[:12]}-{_timestamp(now)}"
    exports_dir = config.out_dir / "exports" / config.project_id
    zip_path = mf.write_zip(config.project_path, files,
                            {"manifest.json": manifest_doc, "graph.json": graph, "audit.json": audit},
                            exports_dir / f"{stem}.zip")
    if config.encryption_key:
        encrypted = zip_path.with_name(zip_path.name + ".enc")
        encrypted.write_bytes(mf.encrypt_bytes(zip_path.read_bytes(), config.encryption_key))
        zip_path.unlink()
        zip_path = encrypted
    sidecar_path = exports_dir / (f"{stem}.manifest.json" + (".enc" if config.encryption_key else ""))
    sidecar_path.write_bytes(_sidecar_bytes(manifest_doc, config.encryption_key))
    result.zip_path = str(zip_path)

    if drive is None:
        result.status = "DRY_RUN"
        _write_state(config, manifest_doc)
        return result

    common = {"amc_project_id": config.project_id, "amc_manifest_hash": mhash}
    uploaded = _upload_verified(drive, zip_path, folder_id, mhash, {
        **common, "amc_kind": "export", "amc_export_kind": result.export_kind,
        "amc_base_manifest_hash": base_hash or "none", "amc_commit_sha": (config.commit_sha or "none")[:64],
        "amc_encrypted": "1" if config.encryption_key else "0",
    }, ENCRYPTED_MIME if config.encryption_key else ZIP_MIME)
    _upload_verified(drive, sidecar_path, folder_id, mhash, {**common, "amc_kind": "manifest"},
                     ENCRYPTED_MIME if config.encryption_key else JSON_MIME)
    if config.upload_public:
        drive.share_with_anyone_with_link(uploaded["id"])
        uploaded = drive.get(uploaded["id"])
    result.status = "UPLOADED"
    result.drive_file_id = uploaded["id"]
    result.drive_web_view_link = uploaded.get("webViewLink")
    _write_state(config, manifest_doc)
    result.notion_page_id = _record_in_notion(config, notion, result, now, graph=graph)
    if config.retention_full_keep:
        result.trashed = _apply_retention(drive, config, folder_id)
    return result


def _write_state(config: ExportConfig, manifest_doc: dict) -> None:
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest_doc, indent=2, sort_keys=True), encoding="utf-8")


def _upload_verified(drive: DriveClient, path: Path, folder_id: str, mhash: str,
                     app_properties: dict[str, str], mime_type: str) -> dict:
    created = drive.upload(path, name=path.name, parent_id=folder_id, mime_type=mime_type,
                           app_properties=app_properties)
    observed = drive.get(created["id"])
    expected_md5, expected_size = mf.md5_file(path), path.stat().st_size
    problems = []
    if observed.get("md5Checksum") != expected_md5:
        problems.append("md5")
    if int(observed.get("size", -1)) != expected_size:
        problems.append("size")
    if observed.get("appProperties", {}).get("amc_manifest_hash") != mhash:
        problems.append("manifest_hash")
    if problems:
        raise ExportVerificationError(
            f"Drive read-back of {path.name} (file {created['id']}) does not match the local file: {', '.join(problems)}")
    return observed


def _record_in_notion(config: ExportConfig, notion: NotionClient | None, result: ExportResult,
                      now: datetime, *, graph: dict | None) -> str | None:
    if notion is None:
        return None
    record = {
        "title": f"{config.project_id} · {_timestamp(now)}",
        "project_id": config.project_id,
        "brand_id": config.brand_id,
        "commit_sha": config.commit_sha,
        "timestamp": now.astimezone(timezone.utc).isoformat(),
        "drive_file_id": result.drive_file_id,
        "drive_web_view_link": result.drive_web_view_link,
        "manifest_hash": result.manifest_hash,
        "artifacts_count": result.artifacts_count,
        "approvals_state": "draft",
        "tags": [t for t in ("amc-export", result.export_kind, "encrypted" if result.encrypted else None) if t],
        "short_summary": mf.short_summary(graph) if graph else "Recorded from an existing Drive export.",
    }
    blocks = [heading_block("Export"), *paragraph_blocks(
        f"Manifest {result.manifest_hash} · {result.artifacts_count} files · {result.files_in_zip} in this "
        f"{result.export_kind or 'existing'} zip · commit {config.commit_sha or 'not set'} · actor {config.actor}")]
    if result.drive_web_view_link:
        blocks.append(bookmark_block(result.drive_web_view_link))
    if graph:
        blocks += [heading_block("Summary"), *paragraph_blocks(mf.short_summary(graph))]
        if graph["prompts"] and not result.encrypted:
            snippet = "\n\n".join(f"{p['path']}: {p['excerpt']}" for p in graph["prompts"])
            blocks += [heading_block("Prompts"), *paragraph_blocks(snippet[:NOTION_PROMPT_SNIPPET_CHARS])]
    if config.notion_database_id:
        found = notion.find_page_by_manifest_hash(config.notion_database_id, result.manifest_hash)
        if found:
            return found["id"]
        page = notion.create_page({"database_id": config.notion_database_id}, database_properties(record), blocks)
    else:
        page = notion.create_page({"page_id": config.notion_parent_page_id},
                                  {"title": {"title": rich_text(record["title"])}}, blocks)
    return page["id"]


def _apply_retention(drive: DriveClient, config: ExportConfig, folder_id: str) -> list[str]:
    """Trash exports older than the Nth most recent full export.

    Every delta newer than the oldest kept full export is kept, so each kept
    export can still be restored. Trashed files stay recoverable for 30 days.
    """
    exports = drive.find_by_app_properties(
        {"amc_project_id": config.project_id, "amc_kind": "export"}, parent_id=folder_id)
    fulls = [f for f in exports if f.get("appProperties", {}).get("amc_export_kind") == "full"]
    keep = config.retention_full_keep or 0
    if len(fulls) <= keep:
        return []
    cutoff = sorted(f["createdTime"] for f in fulls)[-keep]
    manifests = drive.find_by_app_properties(
        {"amc_project_id": config.project_id, "amc_kind": "manifest"}, parent_id=folder_id)
    trashed = []
    for item in exports + manifests:
        if item["createdTime"] < cutoff:
            drive.trash(item["id"])
            trashed.append(item["id"])
    return trashed


def check_access(config: ExportConfig, *, drive: DriveClient | None = None,
                 notion: NotionClient | None = None) -> dict:
    """Read-only credential check: fetch the Drive folder and the Notion database."""
    if not config.uploads:
        raise ExportConfigError("--check needs RUNNER_MODE=local or ci")
    report: dict = {}
    drive = drive or DriveClient(ServiceAccount.from_value(config.google_sa_json or "",
                                                           subject=config.google_impersonate_subject))
    folder = drive.get(config.drive_parent_folder_id or "", fields="id,name,mimeType,driveId,capabilities(canAddChildren)")
    report["drive_folder"] = {
        "id": folder.get("id"), "name": folder.get("name"),
        "is_folder": folder.get("mimeType") == "application/vnd.google-apps.folder",
        "in_shared_drive": bool(folder.get("driveId")),
        "can_add_children": bool(folder.get("capabilities", {}).get("canAddChildren")),
    }
    if config.notion_enabled:
        notion = notion or NotionClient(config.notion_token or "")
        target = (f"/databases/{config.notion_database_id}" if config.notion_database_id
                  else f"/pages/{config.notion_parent_page_id}")
        body = notion._call("GET", target)
        report["notion"] = {"id": body.get("id"), "object": body.get("object")}
    return report
