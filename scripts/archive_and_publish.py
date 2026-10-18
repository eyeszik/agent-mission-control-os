#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "Missing optional dependency 'google-api-python-client'. Install with: "
        "pip install google-api-python-client"
    ) from exc

try:
    from notion_client import Client
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "Missing optional dependency 'notion-client'. Install with: "
        "pip install notion-client"
    ) from exc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(project_dir: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    include_patterns = ("**/*.md", "**/*.txt", "**/*.json", "**/*.yaml", "**/*.yml", "**/*.csv", "**/*.html", "**/*.svg", "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp")

    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(project_dir).as_posix()
        if rel.startswith(".git/"):
            continue
        if rel.endswith(".pyc"):
            continue
        # keep a bounded manifest; skip huge files > 50MB unless explicitly requested
        size = path.stat().st_size
        if size > 50 * 1024 * 1024:
            continue
        entries.append({
            "path": rel,
            "sha256": sha256_file(path),
            "size": size,
        })

    return {
        "project": project_dir.name,
        "files": entries,
    }


def graph_index(manifest: dict[str, Any]) -> dict[str, Any]:
    file_paths = [entry["path"] for entry in manifest["files"]]
    output = {
        "project": manifest["project"],
        "file_count": len(file_paths),
        "types": {},
        "root_files": sorted(file_paths)[:50],
    }
    for path in file_paths:
        suffix = Path(path).suffix.lower().lstrip(".")
        output["types"][suffix] = output["types"].get(suffix, 0) + 1
    return output


def write_archive(project_dir: Path, archive_path: Path, manifest: dict[str, Any], graph: dict[str, Any]) -> str:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(project_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(project_dir).as_posix()
            if rel.startswith(".git/"):
                continue
            if rel.endswith(".pyc"):
                continue
            if path.stat().st_size > 50 * 1024 * 1024:
                continue
            zf.write(path, arcname=rel)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        zf.writestr("graph.json", json.dumps(graph, indent=2, sort_keys=True))
    return sha256_file(archive_path)


def parse_google_service_account(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        path = Path(raw)
        if not path.exists():
            raise ValueError(
                "GOOGLE_SA_JSON must be either JSON text or a path to a service-account file"
            )
        return json.loads(path.read_text(encoding="utf-8"))


def ensure_drive_folder(drive_service: Any, folder_name: str, parent_folder_id: str | None) -> str:
    q = "mimeType = 'application/vnd.google-apps.folder' and name = '{}'".format(folder_name.replace("'", "\\'"))
    if parent_folder_id:
        q += " and '{}' in parents".format(parent_folder_id)
    response = drive_service.files().list(
        q=q,
        spaces="drive",
        fields="files(id,name)",
        pageSize=100,
    ).execute()
    folders = response.get("files", [])
    if folders:
        return folders[0]["id"]

    folder_metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_folder_id:
        folder_metadata["parents"] = [parent_folder_id]
    folder = drive_service.files().create(body=folder_metadata, fields="id").execute()
    return folder["id"]


def upload_to_drive(project_dir: Path, archive_path: Path, project_id: str, brand_id: str) -> dict[str, str]:
    service_account_json = os.environ.get("GOOGLE_SA_JSON")
    if not service_account_json:
        raise RuntimeError("GOOGLE_SA_JSON is required for Drive uploads")

    creds = service_account.Credentials.from_service_account_info(
        parse_google_service_account(service_account_json),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    folder_name = f"{project_id}-{brand_id}" if brand_id else project_id
    parent_id = os.environ.get("DRIVE_PARENT_FOLDER_ID")
    target_folder_id = ensure_drive_folder(drive, folder_name, parent_id)

    media = MediaFileUpload(str(archive_path), mimetype="application/zip", resumable=True)
    file_metadata = {"name": archive_path.name, "parents": [target_folder_id]}
    file_info = drive.files().create(body=file_metadata, media_body=media, fields="id,name,webViewLink").execute()

    return {
        "file_id": file_info["id"],
        "file_name": file_info["name"],
        "web_view_link": file_info.get("webViewLink", ""),
        "folder_id": target_folder_id,
    }


def build_notion_properties(title: str, project_id: str, brand_id: str, archive_info: dict[str, str], commit_sha: str, manifest_hash: str, file_count: int) -> dict[str, Any]:
    props = {
        "Title": {"title": [{"text": {"content": title}}]},
        "project_id": {"rich_text": [{"text": {"content": project_id}}]},
        "brand_id": {"rich_text": [{"text": {"content": brand_id}}]},
        "commit_sha": {"rich_text": [{"text": {"content": commit_sha}}]},
        "archive_file": {"url": archive_info.get("web_view_link", "")},
        "drive_file_id": {"rich_text": [{"text": {"content": archive_info.get("file_id", "")}}]},
        "manifest_hash": {"rich_text": [{"text": {"content": manifest_hash}}]},
        "artifact_count": {"number": file_count},
    }
    return props


def notion_blocks(summary: str, archive_link: str, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    snippets = [
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Summary"}}]}},
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": summary[:2000]}}]}},
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"Archive: {archive_link}"}}]}},
    ]
    # include manifest preview
    manifest_preview = "\n".join(f"- {item['path']} ({item['sha256'][:12]})" for item in manifest["files"][:30])
    snippets.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": manifest_preview[:2000]}}]},
    })
    return snippets


def create_notion_page(project_id: str, brand_id: str, archive_info: dict[str, str], commit_sha: str, manifest_hash: str, file_count: int, summary: str, manifest: dict[str, Any]) -> dict[str, Any]:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_TOKEN is required for Notion publishing")

    database_id = os.environ.get("NOTION_DATABASE_ID")
    parent_page_id = os.environ.get("NOTION_PARENT_PAGE_ID")
    if not database_id and not parent_page_id:
        raise RuntimeError("Set NOTION_DATABASE_ID or NOTION_PARENT_PAGE_ID")

    client = Client(auth=token)
    title = f"{project_id}-{brand_id or 'brand'}"
    properties = build_notion_properties(title, project_id, brand_id, archive_info, commit_sha, manifest_hash, file_count)
    page_payload: dict[str, Any] = {"parent": {"database_id": database_id} if database_id else {"page_id": parent_page_id}, "properties": properties}
    page = client.pages.create(**page_payload)

    for block in notion_blocks(summary, archive_info.get("web_view_link", ""), manifest):
        client.blocks.children.append(block_id=page["id"], children=[block])
    return page


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive generated project artifacts and publish to Drive + Notion")
    parser.add_argument("--project-dir", default="projects", help="Root folder of generated project artifacts")
    parser.add_argument("--project-id", default=os.environ.get("AMC_PROJECT_ID", "project"), help="Project id used in naming")
    parser.add_argument("--brand-id", default=os.environ.get("AMC_BRAND_ID", "brand"), help="Brand id used in naming")
    parser.add_argument("--archive-name", default=None, help="Optional explicit archive filename")
    parser.add_argument("--skip-drive", action="store_true")
    parser.add_argument("--skip-notion", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_dir = Path(args.project_dir).resolve()
    if not project_dir.exists():
        raise SystemExit(f"Project directory does not exist: {project_dir}")

    manifest = build_manifest(project_dir)
    graph = graph_index(manifest)
    summary = f"Archive generated for {args.project_id}/{args.brand_id}. Files: {len(manifest['files'])}."

    archive_name = args.archive_name or f"{args.project_id}-{args.brand_id}-{os.environ.get('REPO_COMMIT_SHA', 'local')}.zip"
    archive_path = Path(tempfile.gettempdir()) / archive_name
    manifest_hash = write_archive(project_dir, archive_path, manifest, graph)

    if args.dry_run:
        print(json.dumps({"archive_path": str(archive_path), "manifest_hash": manifest_hash, "artifact_count": len(manifest["files"])}, indent=2))
        return 0

    archive_info: dict[str, str] = {"file_id": "", "file_name": archive_path.name, "web_view_link": "", "folder_id": ""}
    if not args.skip_drive:
        archive_info = upload_to_drive(project_dir, archive_path, args.project_id, args.brand_id)

    if not args.skip_notion:
        create_notion_page(
            project_id=args.project_id,
            brand_id=args.brand_id,
            archive_info=archive_info,
            commit_sha=os.environ.get("REPO_COMMIT_SHA", "local"),
            manifest_hash=manifest_hash,
            file_count=len(manifest["files"]),
            summary=summary,
            manifest=manifest,
        )

    print(json.dumps({
        "archive_path": str(archive_path),
        "manifest_hash": manifest_hash,
        "archive_info": archive_info,
        "artifact_count": len(manifest["files"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
