"""Artifact graph v2 and DAM over the canonical N4 registry."""

from __future__ import annotations

import base64
import threading
from datetime import datetime, timedelta, timezone

import pytest

from _project_os_support import as_user, client, export_root, new_project  # noqa: F401


@pytest.fixture(autouse=True)
def _admin(monkeypatch, export_root):  # noqa: F811
    as_user(monkeypatch, "designer-1")


def _artifact(pid: str, key: str, artifact_type: str, text: str, **extra) -> dict:
    response = client.post(f"/projects/{pid}/artifacts", json={"artifact_key": key, "artifact_type": artifact_type, "content_text": text, **extra})
    assert response.status_code == 201, response.text
    return response.json()["artifact"]


def test_artifact_type_must_respect_n1_vocabulary():
    pid = new_project()["project_id"]
    bad = client.post(f"/projects/{pid}/artifacts", json={"artifact_key": "x", "artifact_type": "not_a_type", "content_text": "x"})
    assert bad.status_code == 422
    made = _artifact(pid, "hero", "media_asset", "placeholder", v2={"media_type": "image", "channel": "web"})
    assert made["owner_department"] == "creative" and made["version_ref"].endswith(":v1")


def test_stale_version_edit_is_rejected():
    pid = new_project()["project_id"]
    art = _artifact(pid, "positioning", "positioning_statement", "v1 text")
    ok = client.post(f"/projects/{pid}/artifacts/{art['artifact_id']}/revisions", json={"expected_version": 1, "content_text": "v2 text"})
    assert ok.status_code == 200 and ok.json()["artifact"]["version"] == 2
    stale = client.post(f"/projects/{pid}/artifacts/{art['artifact_id']}/revisions", json={"expected_version": 1, "content_text": "lost update"})
    assert stale.status_code == 409


def test_concurrent_edits_from_the_same_head_cannot_both_win():
    pid = new_project()["project_id"]
    art = _artifact(pid, "copy", "copy_variant", "base")
    results: list[int] = []

    def edit(text: str) -> None:
        response = client.post(f"/projects/{pid}/artifacts/{art['artifact_id']}/revisions", json={"expected_version": 1, "content_text": text})
        results.append(response.status_code)

    threads = [threading.Thread(target=edit, args=(f"edit-{i}",)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results).count(200) == 1
    assert all(code in (200, 409) for code in results)
    history = client.get(f"/projects/{pid}/artifacts/{art['artifact_id']}/history").json()["versions"]
    assert [v["version"] for v in history] == [1, 2]


def test_master_replacement_invalidates_derivatives_and_queues_remediation():
    pid = new_project()["project_id"]
    core = _artifact(pid, "brand-core", "brand_core", "voice: calm")
    master = _artifact(pid, "hero-copy", "copy_variant", "Hello", depends_on=[core["artifact_id"]], v2={"channel": "web"})
    ig = client.post(f"/projects/{pid}/artifacts/{master['artifact_id']}/branch", json={"branch_key": "hero-ig", "v2": {"channel": "instagram"}}).json()["artifact"]
    assert ig["master_artifact_id"] == master["artifact_id"] and ig["variant_of"] == master["artifact_id"]
    revised = client.post(f"/projects/{pid}/artifacts/{core['artifact_id']}/revisions", json={"expected_version": 1, "content_text": "voice: bold"}).json()
    affected = {a["artifact_id"]: a["status"] for a in revised["blast_radius"]["affected"]}
    assert affected == {master["artifact_id"]: "invalidated", ig["artifact_id"]: "invalidated"}
    assert len(revised["blast_radius"]["remediation_requests"]) == 2
    # Revising the same upstream again must not trip the policy ledger (regression).
    again = client.post(f"/projects/{pid}/artifacts/{core['artifact_id']}/revisions", json={"expected_version": 2, "content_text": "voice: warm"})
    assert again.status_code == 200, again.text
    open_requests = client.get(f"/projects/{pid}/edit-requests", params={"status": "open"}).json()["edit_requests"]
    assert {r["artifact_id"] for r in open_requests} == {master["artifact_id"], ig["artifact_id"]}


def test_compare_restore_and_merge():
    pid = new_project()["project_id"]
    art = _artifact(pid, "tagline", "copy_variant", "Fast coffee\nfor busy people\n")
    aid = art["artifact_id"]
    client.post(f"/projects/{pid}/artifacts/{aid}/revisions", json={"expected_version": 1, "content_text": "Slow coffee\nfor busy people\n", "v2_patch": {"channel": "x"}})
    diff = client.get(f"/projects/{pid}/artifacts/{aid}/compare", params={"from": 1, "to": 2}).json()["diff"]
    assert diff["content_changed"] is True
    assert "-Fast coffee" in diff["text_diff"] and "+Slow coffee" in diff["text_diff"]
    assert diff["metadata_changes"]["channel"] == {"from": None, "to": "x"}
    restored = client.post(f"/projects/{pid}/artifacts/{aid}/restore", json={"version": 1, "expected_version": 2}).json()
    assert restored["artifact"]["version"] == 3 and restored["artifact"]["content_hash"] == art["content_hash"]
    branch = client.post(f"/projects/{pid}/artifacts/{aid}/branch", json={"branch_key": "tagline-alt", "content_text": "Better coffee\n"}).json()["artifact"]
    merged = client.post(f"/projects/{pid}/artifacts/{aid}/merge", json={"branch_id": branch["artifact_id"], "expected_version": 3, "replace_master": True}).json()
    assert merged["artifact"]["content_hash"] == branch["content_hash"]
    kinds = [v["change_kind"] for v in client.get(f"/projects/{pid}/artifacts/{aid}/history").json()["versions"]]
    assert kinds == ["create", "revise", "restore", "replace_master"]


def test_dam_listing_filters_and_project_isolation():
    a = new_project("Brand A")["project_id"]
    b = new_project("Brand B")["project_id"]
    _artifact(a, "story", "media_asset", "x", v2={"media_type": "image", "channel": "instagram"})
    _artifact(a, "post", "copy_variant", "y", v2={"channel": "linkedin"})
    images = client.get(f"/projects/{a}/artifacts", params={"media_type": "image"}).json()["artifacts"]
    assert [i["artifact_key"] for i in images] == ["story"]
    assert client.get(f"/projects/{b}/artifacts").json()["artifacts"] == []
    # An artifact from project A cannot be addressed through project B.
    foreign = images[0]["artifact_id"]
    assert client.get(f"/projects/{b}/artifacts/{foreign}/history").status_code == 404


def test_uploads_are_sniffed_bounded_and_registered():
    pid = new_project()["project_id"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    ok = client.post(f"/projects/{pid}/uploads", json={"artifact_key": "logo", "content_base64": base64.b64encode(png).decode(), "v2": {"dimensions": "512x512"}})
    assert ok.status_code == 201, ok.text
    meta = ok.json()["artifact"]
    assert meta["artifact_type"] == "media_asset" and meta["mime_type"] == "image/png" and meta["media_type"] == "image"
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    assert client.post(f"/projects/{pid}/uploads", json={"artifact_key": "evil", "content_base64": base64.b64encode(svg).decode()}).status_code == 415
    assert client.post(f"/projects/{pid}/uploads", json={"artifact_key": "bad", "content_base64": "%%%notbase64"}).status_code == 422
    assert client.post(f"/projects/{pid}/uploads", json={"artifact_key": "bin", "content_base64": base64.b64encode(b"\xff\xfe\x00\x81binary").decode()}).status_code == 415


def test_rights_radar_reports_expired_and_unlicensed_media():
    pid = new_project()["project_id"]
    licensed = _artifact(pid, "photo-1", "media_asset", "x", v2={"media_type": "image"})
    _artifact(pid, "photo-2", "media_asset", "y", v2={"media_type": "image"})
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    client.post(f"/projects/{pid}/artifacts/{licensed['artifact_id']}/rights", json={"license": "stock-standard", "expires_at": past})
    radar = client.get(f"/projects/{pid}/rights").json()["radar"]
    assert [r["artifact_id"] for r in radar["expired"]] == [licensed["artifact_id"]]
    assert len(radar["media_without_rights"]) == 1


def test_prompt_ledger_versions_and_materializes(export_root):  # noqa: F811
    pid = new_project()["project_id"]
    body = {"department": "creative", "artifact_target": "hero", "body": {"exact_text": "A calm hero image", "seed": 7}}
    first = client.post(f"/projects/{pid}/prompts", json=body).json()
    same = client.post(f"/projects/{pid}/prompts", json={**body, "prompt_id": first["prompt"]["prompt_id"]}).json()
    assert first["created"] is True and same["created"] is False
    changed = client.post(f"/projects/{pid}/prompts", json={**body, "prompt_id": first["prompt"]["prompt_id"], "body": {"exact_text": "A bold hero image"}}).json()
    assert changed["prompt"]["version"] == 2
    assert client.post(f"/projects/{pid}/prompts", json={"department": "creative", "body": {}}).status_code == 422
    files = client.post(f"/projects/{pid}/workspace/prompts/materialize").json()["files"]
    assert any(path.endswith("07_prompts/ALL_PROMPTS.md") for path in files)
    tree = client.get(f"/projects/{pid}/workspace").json()["files"]
    assert {row["folder"] for row in tree} >= {"00_admin", "07_prompts"}
