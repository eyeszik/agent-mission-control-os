"""Drive export runner: manifest, delta, packaging, Google Drive and Notion.

The Drive and Notion clients are the production adapters. They run here
against an in-process HTTP emulator of the endpoints they call, so the
requests (JWT exchange, query syntax, resumable upload, read-back) are
exercised end to end without a network or a credential.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from services.langgraph.integrations.drive_export import manifest as mf
from services.langgraph.integrations.drive_export._http import ApiError, request_with_retry
from services.langgraph.integrations.drive_export.google_drive import (
    DriveClient,
    DriveConfigError,
    OAuthUser,
    ServiceAccount,
    signed_assertion,
)
from services.langgraph.integrations.drive_export.oauth_setup import (
    build_authorization_url,
    exchange_code,
    new_pkce_pair,
)
from services.langgraph.integrations.drive_export.notion import (
    MAX_BLOCKS_PER_REQUEST,
    MAX_TEXT_RUN,
    NotionClient,
    paragraph_blocks,
)
from services.langgraph.integrations.drive_export.runner import (
    ExportConfig,
    ExportConfigError,
    ExportVerificationError,
    check_access,
    run_export,
)

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = RSA_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
SA_JSON = json.dumps({"type": "service_account", "client_email": "exporter@proj.iam.gserviceaccount.com",
                      "private_key": PEM, "token_uri": "https://oauth2.googleapis.com/token"})


def _verify_jwt(assertion: str) -> dict:
    header, claims, signature = assertion.split(".")
    pad = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))  # noqa: E731
    RSA_KEY.public_key().verify(pad(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return json.loads(pad(claims))


class DriveEmulator:
    """The subset of OAuth token + Drive v3 behaviour the client relies on."""

    def __init__(self) -> None:
        self.files: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.permissions: list[tuple[str, dict]] = []
        self.uploads = 0
        self.corrupt_md5 = False
        self.reject_refresh = False
        self.refresh_grants = 0
        self.fail_next: list[int] = []
        self._seq = 0

    def _id(self) -> str:
        self._seq += 1
        return f"f{self._seq:03d}"

    def add_folder(self, name: str, *, parent: str | None = None, drive_id: str = "sd1") -> str:
        fid = self._id()
        self.files[fid] = {"id": fid, "name": name, "mimeType": "application/vnd.google-apps.folder",
                           "parents": [parent] if parent else [], "trashed": False, "appProperties": {},
                           "createdTime": self._created(), "driveId": drive_id,
                           "capabilities": {"canAddChildren": True}}
        return fid

    def _created(self) -> str:
        return (NOW + timedelta(seconds=self._seq)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _matches(self, item: dict, query: str) -> bool:
        for clause in re.split(r"\s+and\s+(?![^{]*})", query):
            clause = clause.strip()
            if clause == "trashed = false":
                ok = not item["trashed"]
            elif m := re.fullmatch(r"mimeType = '(.+)'", clause):
                ok = item.get("mimeType") == m.group(1)
            elif m := re.fullmatch(r"name = '(.+)'", clause):
                ok = item["name"] == m.group(1)
            elif m := re.fullmatch(r"'(.+)' in parents", clause):
                ok = m.group(1) in item["parents"]
            elif m := re.fullmatch(r"appProperties has \{ key='(.+)' and value='(.+)' \}", clause):
                ok = item["appProperties"].get(m.group(1)) == m.group(2)
            else:
                raise AssertionError(f"unsupported query clause: {clause}")
            if not ok:
                return False
        return True

    def _public(self, item: dict) -> dict:
        return {k: v for k, v in item.items() if k not in ("content", "parents")}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url, method = request.url, request.method
        self.calls.append((method, url.path))
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), headers={"Retry-After": "0"})
        if url.host == "oauth2.googleapis.com":
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["refresh_token"]:
                assert form["client_id"] == ["cid"] and form["client_secret"] == ["csecret"]
                if self.reject_refresh or form["refresh_token"] != ["rtoken"]:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.refresh_grants += 1
                return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
            assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
            claims = _verify_jwt(form["assertion"][0])
            assert claims["scope"] == "https://www.googleapis.com/auth/drive"
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer tok"
        params = dict(url.params)
        if url.path == "/upload/drive/v3/files" and method == "POST":
            sid = f"s{len(self.sessions) + 1}"
            self.sessions[sid] = {"meta": json.loads(request.content), "data": b"",
                                  "total": int(request.headers["X-Upload-Content-Length"])}
            return httpx.Response(200, headers={"Location": f"https://www.googleapis.com/upload/drive/v3/files?upload_id={sid}"})
        if url.path == "/upload/drive/v3/files" and method == "PUT":
            session = self.sessions[params["upload_id"]]
            start, end, total = map(int, re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", request.headers["Content-Range"]).groups())
            assert start == len(session["data"]) and total == session["total"]
            session["data"] += request.content
            if len(session["data"]) < total:
                return httpx.Response(308, headers={"Range": f"bytes=0-{end}"})
            self.uploads += 1
            meta, data, fid = session["meta"], session["data"], self._id()
            md5 = hashlib.md5(data).hexdigest()
            self.files[fid] = {"id": fid, "name": meta["name"], "parents": meta["parents"], "trashed": False,
                               "appProperties": meta.get("appProperties", {}), "mimeType": meta["mimeType"],
                               "size": str(len(data)), "md5Checksum": "0" * 32 if self.corrupt_md5 else md5,
                               "webViewLink": f"https://drive.google.com/file/d/{fid}/view",
                               "createdTime": self._created(), "content": data}
            return httpx.Response(200, json=self._public(self.files[fid]))
        if url.path == "/drive/v3/files" and method == "GET":
            found = [f for f in self.files.values() if self._matches(f, params["q"])]
            found.sort(key=lambda f: f["createdTime"], reverse=params.get("orderBy", "").endswith("desc"))
            return httpx.Response(200, json={"files": [self._public(f) for f in found]})
        if url.path == "/drive/v3/files" and method == "POST":
            body = json.loads(request.content)
            fid = self.add_folder(body["name"], parent=body["parents"][0])
            return httpx.Response(200, json={"id": fid})
        if m := re.fullmatch(r"/drive/v3/files/([^/]+)/permissions", url.path):
            self.permissions.append((m.group(1), json.loads(request.content)))
            return httpx.Response(200, json={"id": "perm1"})
        if m := re.fullmatch(r"/drive/v3/files/([^/]+)", url.path):
            item = self.files.get(m.group(1))
            if item is None:
                return httpx.Response(404)
            if method == "PATCH":
                item["trashed"] = json.loads(request.content)["trashed"]
                return httpx.Response(200, json={"id": item["id"]})
            if params.get("alt") == "media":
                return httpx.Response(200, content=item["content"])
            return httpx.Response(200, json=self._public(item))
        raise AssertionError(f"unexpected Drive call {method} {url}")


class NotionEmulator:
    def __init__(self) -> None:
        self.pages: dict[str, dict] = {}
        self.appended: list[int] = []
        self.fail_pages = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-notion"
        assert request.headers["Notion-Version"] == "2022-06-28"
        path, body = request.url.path, json.loads(request.content or b"{}")
        if path == "/v1/pages" and request.method == "POST":
            if self.fail_pages:
                self.fail_pages -= 1
                return httpx.Response(400, json={"message": "validation_error"})
            assert len(body["children"]) <= MAX_BLOCKS_PER_REQUEST
            pid = f"page{len(self.pages) + 1}"
            self.pages[pid] = {"id": pid, **body}
            return httpx.Response(200, json={"id": pid})
        if m := re.fullmatch(r"/v1/blocks/([^/]+)/children", path):
            assert len(body["children"]) <= MAX_BLOCKS_PER_REQUEST
            self.pages[m.group(1)]["children"] += body["children"]
            self.appended.append(len(body["children"]))
            return httpx.Response(200, json={"results": []})
        if m := re.fullmatch(r"/v1/databases/([^/]+)/query", path):
            wanted = body["filter"]["rich_text"]["equals"]
            hits = [p for p in self.pages.values()
                    if p["properties"].get("manifest_hash", {}).get("rich_text", [{}])[0].get("text", {}).get("content") == wanted]
            return httpx.Response(200, json={"results": hits[:1]})
        if m := re.fullmatch(r"/v1/databases/([^/]+)", path):
            return httpx.Response(200, json={"id": m.group(1), "object": "database"})
        raise AssertionError(f"unexpected Notion call {request.method} {path}")


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "velune-demo"
    (root / "branding").mkdir(parents=True)
    (root / "prompts").mkdir()
    (root / "brief.md").write_text("# Quiet tailoring\n\nMade to order in eight weeks.\n")
    (root / "branding" / "palette.json").write_text('{"ink": "black"}\n')
    (root / "prompts" / "hero-prompt.txt").write_text("A fitting room at dawn, single window light, wool on a table.\n")
    (root / "branding" / "mark.svg").write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'>" + b" " * 3000 + b"</svg>")
    return root


def _config(tmp_path: Path, root: Path, **env) -> ExportConfig:
    base = {"RUNNER_MODE": "ci", "GOOGLE_SA_JSON": SA_JSON, "DRIVE_PARENT_FOLDER_ID": "parent",
            "NOTION_TOKEN": "secret-notion", "NOTION_DATABASE_ID": "db1", "REPO_COMMIT_SHA": "abc123def4567890"}
    base.update(env)
    return ExportConfig.from_env({k: v for k, v in base.items() if v is not None},
                                 project_path=str(root), out_dir=str(tmp_path / "out"), brand_id="velune")


def _clients(drive_em: DriveEmulator, notion_em: NotionEmulator, account=None):
    drive = DriveClient(account or ServiceAccount.from_value(SA_JSON), transport=httpx.MockTransport(drive_em),
                        sleep=lambda s: None, chunk_bytes=1024)
    notion = NotionClient("secret-notion", transport=httpx.MockTransport(notion_em), sleep=lambda s: None)
    return drive, notion


@pytest.fixture
def emulators():
    drive_em, notion_em = DriveEmulator(), NotionEmulator()
    drive_em.files["parent"] = {"id": "parent", "name": "AMC exports", "mimeType": "application/vnd.google-apps.folder",
                                "parents": [], "trashed": False, "appProperties": {}, "createdTime": "2026-01-01T00:00:00.000Z",
                                "driveId": "sd1", "capabilities": {"canAddChildren": True}}
    drive_em.files["root"] = {"id": "root", "name": "My Drive", "mimeType": "application/vnd.google-apps.folder",
                              "parents": [], "trashed": False, "appProperties": {},
                              "createdTime": "2026-01-01T00:00:00.000Z", "capabilities": {"canAddChildren": True}}
    return drive_em, notion_em


# -- manifest, delta, packaging ---------------------------------------------

def test_manifest_is_deterministic_and_skips_symlinks_and_excluded_dirs(tmp_path):
    root = _project(tmp_path)
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref")
    (root / "link.md").symlink_to(root / "brief.md")
    first, second = mf.collect_manifest(root), mf.collect_manifest(root)
    assert first == second
    assert [e.path for e in first.entries] == sorted(e.path for e in first.entries)
    assert not any(e.path.startswith(".git") for e in first.entries)
    assert "link.md: not a regular file" in first.skipped
    assert mf.manifest_hash(first.entries) == mf.manifest_hash(second.entries)
    brief = next(e for e in first.entries if e.path == "brief.md")
    assert brief.sha256 == hashlib.sha256((root / "brief.md").read_bytes()).hexdigest()


def test_oversized_files_are_skipped_and_reported(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setattr(mf, "MAX_FILE_BYTES", 1000)
    collected = mf.collect_manifest(root)
    assert "branding/mark.svg" not in {e.path for e in collected.entries}
    assert any(s.startswith("branding/mark.svg:") for s in collected.skipped)


def test_delta_contains_only_new_and_changed_files_and_reports_removed(tmp_path):
    root = _project(tmp_path)
    before = mf.previous_shas(mf.manifest_document(mf.collect_manifest(root).entries))
    (root / "brief.md").write_text("# Quiet tailoring, revised\n")
    (root / "branding" / "palette.json").unlink()
    (root / "new.md").write_text("# New\n")
    after = mf.collect_manifest(root).entries
    assert [e.path for e in mf.delta(after, before)] == ["brief.md", "new.md"]
    assert mf.removed_paths(after, before) == ("branding/palette.json",)


def test_zip_holds_the_files_with_manifest_graph_and_audit(tmp_path):
    root = _project(tmp_path)
    entries = mf.collect_manifest(root).entries
    extras = {"manifest.json": mf.manifest_document(entries), "graph.json": {"x": 1}, "audit.json": {"y": 2}}
    first = mf.write_zip(root, entries, extras, tmp_path / "a.zip")
    second = mf.write_zip(root, entries, extras, tmp_path / "b.zip")
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names[:3] == ["audit.json", "graph.json", "manifest.json"]
        for entry in entries:
            assert hashlib.sha256(archive.read(f"files/{entry.path}")).hexdigest() == entry.sha256


def test_graph_index_is_deterministic_and_finds_prompts_headings_and_kinds(tmp_path):
    root = _project(tmp_path)
    entries = mf.collect_manifest(root).entries
    graph = mf.build_graph_index(root, entries)
    assert graph == mf.build_graph_index(root, entries)
    assert graph["kinds"] == {"data": 1, "document": 2, "vector": 1}
    assert graph["prompts"][0]["path"] == "prompts/hero-prompt.txt"
    assert graph["headings"] == [{"path": "brief.md", "heading": "Quiet tailoring"}]
    assert "tailoring" in graph["keywords"]


# -- credentials -------------------------------------------------------------

def test_service_account_parsing_rejects_bad_input_and_never_shows_the_key(tmp_path):
    for bad in ("", "{not json", json.dumps({"type": "authorized_user"}), json.dumps({"type": "service_account"}),
                str(tmp_path / "missing.json")):
        with pytest.raises(DriveConfigError) as caught:
            ServiceAccount.from_value(bad)
        assert "PRIVATE KEY" not in str(caught.value)
    key_file = tmp_path / "sa.json"
    key_file.write_text(SA_JSON)
    account = ServiceAccount.from_value(str(key_file))
    assert account.client_email == "exporter@proj.iam.gserviceaccount.com"
    assert "PRIVATE KEY" not in repr(account)
    config = ExportConfig.from_env({"RUNNER_MODE": "ci", "GOOGLE_SA_JSON": SA_JSON, "DRIVE_PARENT_FOLDER_ID": "p",
                                    "NOTION_TOKEN": "secret-notion", "NOTION_DATABASE_ID": "db",
                                    "EXPORT_ENCRYPTION_KEY": base64.b64encode(b"k" * 32).decode()},
                                   project_path=str(_project(tmp_path)))
    assert "PRIVATE KEY" not in repr(config) and "secret-notion" not in repr(config)


def test_signed_assertion_verifies_with_the_public_key_and_carries_the_subject():
    account = ServiceAccount.from_value(SA_JSON, subject="owner@example.com")
    claims = _verify_jwt(signed_assertion(account, now=1_800_000_000))
    assert claims == {"iss": "exporter@proj.iam.gserviceaccount.com", "scope": "https://www.googleapis.com/auth/drive",
                      "aud": "https://oauth2.googleapis.com/token", "iat": 1_800_000_000,
                      "exp": 1_800_003_600, "sub": "owner@example.com"}


# -- configuration and dry run ----------------------------------------------

def test_dry_run_is_the_default_and_builds_locally_without_credentials(tmp_path):
    root = _project(tmp_path)
    config = ExportConfig.from_env({}, project_path=str(root), out_dir=str(tmp_path / "out"))
    assert config.mode == "dry_run" and not config.uploads
    first = run_export(config, now=NOW)
    assert first.status == "DRY_RUN" and first.export_kind == "full" and first.files_in_zip == 4
    assert Path(first.zip_path).is_file()
    assert run_export(config, now=NOW).status == "NO_CHANGES"
    (root / "brief.md").write_text("# Changed\n")
    third = run_export(config, now=NOW + timedelta(minutes=1))
    assert (third.status, third.export_kind, third.files_in_zip) == ("DRY_RUN", "delta", 1)


@pytest.mark.parametrize("env, message", [
    ({"RUNNER_MODE": "live"}, "RUNNER_MODE must be one of"),
    ({"RUNNER_MODE": "ci"}, "needs GOOGLE_SA_JSON"),
    ({"RUNNER_MODE": "local", "GOOGLE_SA_JSON": SA_JSON}, "needs DRIVE_PARENT_FOLDER_ID"),
    ({"RUNNER_MODE": "ci", "GOOGLE_SA_JSON": SA_JSON, "DRIVE_PARENT_FOLDER_ID": "p", "NOTION_TOKEN": "t"},
     "NOTION_DATABASE_ID or NOTION_PARENT_PAGE_ID"),
    ({"UPLOAD_PUBLIC": "yes"}, "UPLOAD_PUBLIC must be true or false"),
    ({"EXPORT_ENCRYPTION_KEY": "c2hvcnQ="}, "32 bytes"),
    ({"EXPORT_RETENTION_FULL_KEEP": "0"}, "positive integer"),
])
def test_invalid_or_incomplete_configuration_fails_closed(tmp_path, env, message):
    with pytest.raises(ExportConfigError, match=message):
        ExportConfig.from_env(env, project_path=str(_project(tmp_path)))


# -- Google Drive and Notion -------------------------------------------------

def test_upload_is_read_back_verified_and_recorded_in_notion(tmp_path, emulators):
    drive_em, notion_em = emulators
    drive, notion = _clients(drive_em, notion_em)
    result = run_export(_config(tmp_path, _project(tmp_path)), drive=drive, notion=notion, now=NOW)
    assert result.status == "UPLOADED" and result.export_kind == "full"
    folder = next(f for f in drive_em.files.values() if f["name"] == "velune-demo")
    assert folder["parents"] == ["parent"]
    exported = drive_em.files[result.drive_file_id]
    assert exported["parents"] == [folder["id"]]
    assert exported["appProperties"]["amc_manifest_hash"] == result.manifest_hash
    assert exported["appProperties"]["amc_export_kind"] == "full"
    assert exported["name"] == "project-velune-demo-abc123def456-20261018T090000Z.zip"
    assert sum(1 for m, p in drive_em.calls if m == "PUT") > 1, "multi-chunk resumable upload"
    with zipfile.ZipFile(__import__("io").BytesIO(exported["content"])) as archive:
        assert json.loads(archive.read("manifest.json"))["manifest_hash"] == result.manifest_hash
    sidecars = [f for f in drive_em.files.values() if f["appProperties"].get("amc_kind") == "manifest"]
    assert len(sidecars) == 1
    page = notion_em.pages[result.notion_page_id]
    props = page["properties"]
    assert page["parent"] == {"database_id": "db1"}
    assert props["manifest_hash"]["rich_text"][0]["text"]["content"] == result.manifest_hash
    assert props["drive_web_view_link"]["url"] == exported["webViewLink"]
    assert props["artifacts_count"]["number"] == 4
    assert props["approvals_state"]["select"]["name"] == "draft"
    text = json.dumps(page["children"])
    assert "fitting room at dawn" in text and exported["webViewLink"] in text
    assert drive_em.permissions == []


def test_rerun_with_unchanged_content_uploads_nothing_and_does_not_duplicate_the_record(tmp_path, emulators):
    drive_em, notion_em = emulators
    root = _project(tmp_path)
    first = run_export(_config(tmp_path, root), drive=_clients(drive_em, notion_em)[0],
                       notion=_clients(drive_em, notion_em)[1], now=NOW)
    second = run_export(_config(tmp_path, root), drive=_clients(drive_em, notion_em)[0],
                        notion=_clients(drive_em, notion_em)[1], now=NOW + timedelta(hours=1))
    assert second.status == "ALREADY_UPLOADED"
    assert second.drive_file_id == first.drive_file_id
    assert second.notion_page_id == first.notion_page_id
    assert drive_em.uploads == 2 and len(notion_em.pages) == 1


def test_second_export_is_a_delta_against_the_manifest_stored_on_drive(tmp_path, emulators):
    drive_em, notion_em = emulators
    root = _project(tmp_path)
    run_export(_config(tmp_path, root), drive=_clients(drive_em, notion_em)[0], notion=_clients(drive_em, notion_em)[1], now=NOW)
    (root / "brief.md").write_text("# Quiet tailoring, second edition\n")
    (root / "branding" / "palette.json").unlink()
    second = run_export(_config(tmp_path, root, NOTION_TOKEN=None, NOTION_DATABASE_ID=None),
                        drive=_clients(drive_em, notion_em)[0], now=NOW + timedelta(hours=1))
    assert (second.status, second.export_kind, second.files_in_zip) == ("UPLOADED", "delta", 1)
    assert second.removed == ["branding/palette.json"]
    exported = drive_em.files[second.drive_file_id]
    with zipfile.ZipFile(__import__("io").BytesIO(exported["content"])) as archive:
        assert [n for n in archive.namelist() if n.startswith("files/")] == ["files/brief.md"]
        audit = json.loads(archive.read("audit.json"))
    assert audit["base_manifest_hash"] != second.manifest_hash and audit["removed_since_base"] == ["branding/palette.json"]


def test_a_failed_notion_write_is_completed_by_the_next_run_without_a_second_upload(tmp_path, emulators):
    drive_em, notion_em = emulators
    root = _project(tmp_path)
    notion_em.fail_pages = 1
    with pytest.raises(ApiError, match="returned 400"):
        run_export(_config(tmp_path, root), drive=_clients(drive_em, notion_em)[0],
                   notion=_clients(drive_em, notion_em)[1], now=NOW)
    assert drive_em.uploads == 2 and notion_em.pages == {}
    repaired = run_export(_config(tmp_path, root), drive=_clients(drive_em, notion_em)[0],
                          notion=_clients(drive_em, notion_em)[1], now=NOW)
    assert repaired.status == "ALREADY_UPLOADED" and repaired.notion_page_id in notion_em.pages
    assert drive_em.uploads == 2


def test_a_read_back_mismatch_stops_before_anything_is_recorded(tmp_path, emulators):
    drive_em, notion_em = emulators
    drive_em.corrupt_md5 = True
    with pytest.raises(ExportVerificationError, match="md5"):
        run_export(_config(tmp_path, _project(tmp_path)), drive=_clients(drive_em, notion_em)[0],
                   notion=_clients(drive_em, notion_em)[1], now=NOW)
    assert notion_em.pages == {}


def test_encrypted_export_round_trips_and_keeps_prompt_text_out_of_notion(tmp_path, emulators):
    drive_em, notion_em = emulators
    key = b"\x01" * 32
    config = _config(tmp_path, _project(tmp_path), EXPORT_ENCRYPTION_KEY=base64.b64encode(key).decode())
    result = run_export(config, drive=_clients(drive_em, notion_em)[0], notion=_clients(drive_em, notion_em)[1], now=NOW)
    exported = drive_em.files[result.drive_file_id]
    assert exported["name"].endswith(".zip.enc") and exported["appProperties"]["amc_encrypted"] == "1"
    with zipfile.ZipFile(__import__("io").BytesIO(mf.decrypt_bytes(exported["content"], key))) as archive:
        assert "files/prompts/hero-prompt.txt" in archive.namelist()
    assert "fitting room" not in json.dumps(notion_em.pages)
    (tmp_path / "velune-demo" / "brief.md").write_text("# Next\n")
    second = run_export(config, drive=_clients(drive_em, notion_em)[0], notion=_clients(drive_em, notion_em)[1],
                        now=NOW + timedelta(hours=1))
    assert second.export_kind == "delta", "the encrypted Drive manifest was read back as the baseline"


def test_sharing_by_link_happens_only_when_upload_public_is_true(tmp_path, emulators):
    drive_em, notion_em = emulators
    result = run_export(_config(tmp_path, _project(tmp_path), UPLOAD_PUBLIC="true"),
                        drive=_clients(drive_em, notion_em)[0], notion=_clients(drive_em, notion_em)[1], now=NOW)
    assert drive_em.permissions == [(result.drive_file_id, {"role": "reader", "type": "anyone"})]


def test_retention_trashes_only_exports_older_than_the_kept_full_exports(tmp_path, emulators):
    drive_em, notion_em = emulators
    root = _project(tmp_path)
    ids = []
    for step, full in enumerate([True, False, True, False]):
        (root / "brief.md").write_text(f"# Edition {step}\n")
        cfg = _config(tmp_path, root, NOTION_TOKEN=None, NOTION_DATABASE_ID=None,
                      EXPORT_RETENTION_FULL_KEEP="1" if step == 3 else None)
        cfg = ExportConfig(**{**cfg.__dict__, "full": full})
        ids.append(run_export(cfg, drive=_clients(drive_em, notion_em)[0], now=NOW + timedelta(hours=step)))
    trashed = set(ids[3].trashed)
    assert ids[0].drive_file_id in trashed and ids[1].drive_file_id in trashed
    assert ids[2].drive_file_id not in trashed and ids[3].drive_file_id not in trashed
    assert all(drive_em.files[i]["trashed"] for i in trashed), "trashed, not permanently deleted"


def test_check_access_reads_the_folder_and_database_without_writing(tmp_path, emulators):
    drive_em, notion_em = emulators
    report = check_access(_config(tmp_path, _project(tmp_path)), drive=_clients(drive_em, notion_em)[0],
                          notion=_clients(drive_em, notion_em)[1])
    assert report["drive_folder"] == {"id": "parent", "name": "AMC exports", "is_folder": True,
                                      "in_shared_drive": True, "can_add_children": True}
    assert report["notion"] == {"id": "db1", "object": "database"}
    assert all(method == "GET" or "oauth2" in path or path == "/token" for method, path in drive_em.calls)
    assert notion_em.pages == {}


# -- transport limits ---------------------------------------------------------

def test_retry_honours_retry_after_and_stops_after_three_retries():
    statuses = [429, 503, 200]
    sleeps: list[float] = []

    def handler(request):
        return httpx.Response(statuses.pop(0), headers={"Retry-After": "2"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert request_with_retry(client, "GET", "https://x.test/a", sleep=sleeps.append).status_code == 200
    assert sleeps == [2.0, 2.0]
    attempts = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: attempts.append(1) or httpx.Response(500)))
    with pytest.raises(ApiError, match="GET /b returned 500"):
        request_with_retry(client, "GET", "https://x.test/b", sleep=lambda s: None)
    assert len(attempts) == 4
    client = httpx.Client(transport=httpx.MockTransport(lambda r: attempts.append(1) or httpx.Response(403)))
    with pytest.raises(ApiError, match="returned 403"):
        request_with_retry(client, "GET", "https://x.test/c", sleep=lambda s: None)


def test_notion_text_is_split_within_the_api_limits(tmp_path):
    blocks = paragraph_blocks("x" * 13_000)
    assert len(blocks) == 3
    assert all(len(run["text"]["content"]) <= MAX_TEXT_RUN for b in blocks for run in b["paragraph"]["rich_text"])
    emulator = NotionEmulator()
    client = NotionClient("secret-notion", transport=httpx.MockTransport(emulator), sleep=lambda s: None)
    page = client.create_page({"database_id": "db"}, {"Title": {"title": []}}, paragraph_blocks("y" * 6000 * 230))
    assert len(emulator.pages[page["id"]]["children"]) == 230
    assert emulator.appended == [100, 30]


def test_cli_dry_run_and_configuration_error_exit_codes(tmp_path):
    root = _project(tmp_path)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    script = [sys.executable, str(ROOT / "scripts" / "export_to_drive.py"), "--project-path", str(root),
              "--out-dir", str(tmp_path / "cli")]
    ok = subprocess.run(script, env=env, capture_output=True, text=True, cwd=ROOT)
    assert ok.returncode == 0 and json.loads(ok.stdout)["status"] == "DRY_RUN"
    bad = subprocess.run(script, env={**env, "RUNNER_MODE": "ci"}, capture_output=True, text=True, cwd=ROOT)
    assert bad.returncode == 2 and json.loads(bad.stderr)["status"] == "CONFIG_ERROR"


# -- personal Google account: signed-in user instead of a service account ------

OAUTH_ENV = {"GOOGLE_SA_JSON": None, "DRIVE_PARENT_FOLDER_ID": None, "GOOGLE_OAUTH_CLIENT_ID": "cid",
             "GOOGLE_OAUTH_CLIENT_SECRET": "csecret", "GOOGLE_OAUTH_REFRESH_TOKEN": "rtoken"}


def test_signed_in_user_exports_into_an_amc_exports_folder_created_in_my_drive(tmp_path, emulators):
    drive_em, notion_em = emulators
    root = _project(tmp_path)
    config = _config(tmp_path, root, **OAUTH_ENV)
    assert config.uses_oauth and config.drive_parent_folder_id is None
    drive, notion = _clients(drive_em, notion_em, account=config.drive_credential())
    result = run_export(config, drive=drive, notion=notion, now=NOW)
    assert result.status == "UPLOADED" and drive_em.refresh_grants == 1
    top = next(f for f in drive_em.files.values() if f["name"] == "AMC exports" and f["parents"] == ["root"])
    project = next(f for f in drive_em.files.values() if f["name"] == "velune-demo")
    assert top["parents"] == ["root"] and project["parents"] == [top["id"]]
    assert drive_em.files[result.drive_file_id]["parents"] == [project["id"]]
    again = run_export(_config(tmp_path, root, **OAUTH_ENV), drive=_clients(drive_em, notion_em, account=config.drive_credential())[0],
                       notion=_clients(drive_em, notion_em)[1], now=NOW + timedelta(hours=1))
    assert again.status == "ALREADY_UPLOADED"
    assert sum(1 for f in drive_em.files.values() if f["name"] == "AMC exports" and f["parents"] == ["root"]) == 1


@pytest.mark.parametrize("env, message", [
    ({**OAUTH_ENV, "GOOGLE_OAUTH_REFRESH_TOKEN": None}, "also set GOOGLE_OAUTH_REFRESH_TOKEN"),
    ({**OAUTH_ENV, "GOOGLE_OAUTH_CLIENT_ID": None, "GOOGLE_OAUTH_CLIENT_SECRET": None}, "also set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET"),
    ({**OAUTH_ENV, "GOOGLE_SA_JSON": SA_JSON}, "not both"),
    ({**OAUTH_ENV, "GOOGLE_OAUTH_CLIENT_ID": None, "GOOGLE_OAUTH_CLIENT_SECRET": None,
      "GOOGLE_OAUTH_REFRESH_TOKEN": None}, "needs GOOGLE_SA_JSON"),
])
def test_partial_or_conflicting_google_credentials_fail_closed(tmp_path, env, message):
    with pytest.raises(ExportConfigError, match=message):
        _config(tmp_path, _project(tmp_path), **env)


def test_a_rejected_refresh_token_tells_the_user_how_to_recover_and_hides_secrets(tmp_path, emulators):
    drive_em, notion_em = emulators
    drive_em.reject_refresh = True
    account = OAuthUser("cid", "csecret", "rtoken")
    with pytest.raises(ApiError, match="drive_authorize.py") as caught:
        run_export(_config(tmp_path, _project(tmp_path), **OAUTH_ENV), drive=_clients(drive_em, notion_em, account=account)[0],
                   notion=_clients(drive_em, notion_em)[1], now=NOW)
    assert "rtoken" not in str(caught.value) and "csecret" not in str(caught.value)
    assert "rtoken" not in repr(account) and "csecret" not in repr(account)
    assert repr(_clients(drive_em, notion_em, account=account)[0]) == "DriveClient(oauth_user)"
    with pytest.raises(DriveConfigError):
        OAuthUser("cid", "", "rtoken")


def test_check_access_for_a_signed_in_user_reads_my_drive_root(tmp_path, emulators):
    drive_em, notion_em = emulators
    config = _config(tmp_path, _project(tmp_path), **OAUTH_ENV)
    report = check_access(config, drive=_clients(drive_em, notion_em, account=config.drive_credential())[0],
                          notion=_clients(drive_em, notion_em)[1])
    assert report["drive_folder"]["id"] == "root" and report["drive_folder"]["can_add_children"]


def test_authorization_url_uses_pkce_the_narrow_scope_and_a_loopback_redirect():
    verifier, challenge = new_pkce_pair()
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert new_pkce_pair()[0] != verifier
    url = build_authorization_url("cid", "http://127.0.0.1:5555", "st", challenge)
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert query["scope"] == "https://www.googleapis.com/auth/drive.file"
    assert query["code_challenge"] == challenge and query["code_challenge_method"] == "S256"
    assert query["access_type"] == "offline" and query["prompt"] == "consent" and query["state"] == "st"
    assert urlsplit(url).netloc == "accounts.google.com"


def test_code_exchange_returns_only_the_refresh_token_and_sends_the_pkce_verifier():
    seen = {}

    def handler(request):
        seen.update({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "rt-123", "scope": "x"})

    token = exchange_code("cid", "csecret", "code-1", "http://127.0.0.1:5555", "verifier-1",
                          transport=httpx.MockTransport(handler))
    assert token == "rt-123"
    assert seen["grant_type"] == "authorization_code" and seen["code_verifier"] == "verifier-1"
    with pytest.raises(ApiError, match="no refresh token"):
        exchange_code("cid", "csecret", "c", "http://127.0.0.1:5555", "v",
                      transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "a"})))


def test_loopback_receiver_ignores_a_wrong_state_and_returns_the_matching_code():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    spec = importlib.util.spec_from_file_location("drive_authorize", ROOT / "scripts" / "drive_authorize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    base = f"http://127.0.0.1:{server.server_port}"
    found: dict = {}
    thread = threading.Thread(target=lambda: found.update(code=module._wait_for_code(server, "good", wait_seconds=20)))
    thread.start()
    try:
        httpx.get(f"{base}/?state=evil&code=stolen", timeout=10)
        httpx.get(f"{base}/?state=good&code=the-code", timeout=10)
        thread.join(timeout=20)
    finally:
        server.server_close()
    assert found == {"code": "the-code"}


# -- GitHub Actions workflow ---------------------------------------------------

def _workflow() -> dict:
    import yaml

    return yaml.safe_load((ROOT / ".github" / "workflows" / "export-to-drive.yml").read_text())


def test_workflow_is_manual_read_only_and_pins_every_action_by_commit():
    workflow = _workflow()
    assert set(workflow[True]) == {"workflow_dispatch"}, "no push, pull_request or schedule trigger"
    assert workflow["permissions"] == {"contents": "read"}
    text = (ROOT / ".github" / "workflows" / "export-to-drive.yml").read_text()
    for line in re.findall(r"uses:\s*(\S+)", text):
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", line), f"action not pinned to a commit: {line}"


def test_workflow_gives_secrets_only_to_the_environment_gated_upload_job_and_never_inlines_inputs():
    workflow = _workflow()
    dry, export = workflow["jobs"]["dry-run"], workflow["jobs"]["export"]
    assert "environment" not in dry and export["environment"] == "drive-export"
    assert "secrets." not in json.dumps(dry), "the dry-run job must not see any secret"
    assert dry["if"] == "${{ inputs.mode == 'dry_run' }}" and export["if"] == "${{ inputs.mode == 'ci' }}"
    for job in (dry, export):
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), f"expression inlined in a shell script: {step.get('name')}"
    text = (ROOT / ".github" / "workflows" / "export-to-drive.yml").read_text()
    for name in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN", "GOOGLE_SA_JSON",
                 "NOTION_TOKEN", "NOTION_DATABASE_ID", "EXPORT_ENCRYPTION_KEY"):
        assert f"secrets.{name}" in text
    assert 'UPLOAD_PUBLIC: "false"' in text, "CI exports are never shared by link"
