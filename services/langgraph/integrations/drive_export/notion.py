"""Notion client for the export record: one page per uploaded export.

Uses the stable ``2022-06-28`` API version, which addresses databases by id.
Text is split into rich-text runs of at most 2,000 characters and pages are
created with at most 100 child blocks per request, appending the rest, which
are the API's documented limits. The integration token is read from
``NOTION_TOKEN`` by the runner and never logged.
"""

from __future__ import annotations

import time
from typing import Callable

import httpx

from ._http import request_with_retry

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
MAX_TEXT_RUN = 2000
MAX_BLOCKS_PER_REQUEST = 100


def rich_text(text: str) -> list[dict]:
    runs = [text[i:i + MAX_TEXT_RUN] for i in range(0, len(text), MAX_TEXT_RUN)] or [""]
    return [{"type": "text", "text": {"content": run}} for run in runs]


def paragraph_blocks(text: str, *, block_chars: int = 6000) -> list[dict]:
    """Split ``text`` into paragraph blocks of at most ``block_chars`` characters."""
    pieces = [text[i:i + block_chars] for i in range(0, len(text), block_chars)]
    return [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(p)}} for p in pieces]


def heading_block(text: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(text[:MAX_TEXT_RUN])}}


def bookmark_block(url: str) -> dict:
    return {"object": "block", "type": "bookmark", "bookmark": {"url": url}}


class NotionClient:
    def __init__(self, token: str, *, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._http = httpx.Client(
            transport=transport, timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
        )
        self._sleep = sleep

    def __repr__(self) -> str:
        return "NotionClient()"

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, **kwargs) -> dict:
        return request_with_retry(self._http, method, f"{NOTION_API}{path}", sleep=self._sleep, **kwargs).json()

    def find_page_by_manifest_hash(self, database_id: str, manifest_hash: str) -> dict | None:
        body = self._call("POST", f"/databases/{database_id}/query", json={
            "filter": {"property": "manifest_hash", "rich_text": {"equals": manifest_hash}}, "page_size": 1,
        })
        results = body.get("results", [])
        return results[0] if results else None

    def create_page(self, parent: dict, properties: dict, children: list[dict]) -> dict:
        first, rest = children[:MAX_BLOCKS_PER_REQUEST], children[MAX_BLOCKS_PER_REQUEST:]
        page = self._call("POST", "/pages", json={"parent": parent, "properties": properties, "children": first})
        for start in range(0, len(rest), MAX_BLOCKS_PER_REQUEST):
            self._call("PATCH", f"/blocks/{page['id']}/children",
                       json={"children": rest[start:start + MAX_BLOCKS_PER_REQUEST]})
        return page


def database_properties(record: dict) -> dict:
    """Map an export record onto the documented database schema (docs/drive-export.md)."""
    def text(value) -> dict:
        return {"rich_text": rich_text(str(value)) if value else []}

    properties = {
        "Title": {"title": rich_text(record["title"])},
        "project_id": text(record["project_id"]),
        "brand_id": text(record.get("brand_id")),
        "commit_sha": text(record.get("commit_sha")),
        "timestamp": {"date": {"start": record["timestamp"]}},
        "drive_file_id": text(record["drive_file_id"]),
        "drive_web_view_link": {"url": record.get("drive_web_view_link") or None},
        "manifest_hash": text(record["manifest_hash"]),
        "artifacts_count": {"number": record["artifacts_count"]},
        "approvals_state": {"select": {"name": record.get("approvals_state", "draft")}},
        "tags": {"multi_select": [{"name": tag[:100]} for tag in record.get("tags", [])]},
        "short_summary": text(record.get("short_summary")),
    }
    if record.get("graph_index_url"):
        properties["graph_index"] = {"url": record["graph_index_url"]}
    return properties
