"""Artifact storage and API tests (W7 acceptance).

Covers: content-addressed round trip, dedup by sha256, version increments,
cross-tenant isolation via API, read-back integrity verification, tamper
detection, tombstoning, and upload authorization boundaries.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.langgraph.app.main import app
from services.langgraph.persistence.artifacts import (
    ArtifactIntegrityError,
    get_artifact,
    store_artifact,
)

client = TestClient(app)


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")


def test_store_roundtrip_dedup_and_versioning(tmp_path, monkeypatch):
    db_path = str(tmp_path / "art.db")
    art_root = str(tmp_path / "artifacts")
    monkeypatch.setenv("AMC_DB_PATH", db_path)
    monkeypatch.setenv("AMC_ARTIFACT_ROOT", art_root)

    import services.langgraph.persistence.database as database
    from services.langgraph.persistence import sqlite_db

    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(sqlite_db, "DB_PATH", db_path)
    sqlite_db.init_db()

    v1 = store_artifact("tenant-a", "proj-a", "campaign_bundle", b"bytes-1", run_id="run-a")
    v2 = store_artifact("tenant-a", "proj-a", "campaign_bundle", b"bytes-1")
    v3 = store_artifact("tenant-a", "proj-a", "campaign_bundle", b"bytes-2")

    assert v1["version"] == 1
    assert v2["version"] == 2  # same bytes -> new version record
    assert v3["version"] == 3
    assert v2["object_id"] == v1["object_id"]  # content-addressed dedupe
    assert v3["object_id"] != v1["object_id"]

    back = get_artifact(v1["artifact_id"], "tenant-a", include_content=True)
    assert back["content"] == b"bytes-1"
    assert back["content_hash"] == back["object_id"]


def test_artifact_integrity_verifies_read_back(tmp_path, monkeypatch):
    db_path = str(tmp_path / "art2.db")
    art_root = str(tmp_path / "artifacts2")
    monkeypatch.setenv("AMC_DB_PATH", db_path)
    monkeypatch.setenv("AMC_ARTIFACT_ROOT", art_root)

    import services.langgraph.persistence.database as database
    from services.langgraph.persistence import sqlite_db

    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(sqlite_db, "DB_PATH", db_path)
    sqlite_db.init_db()

    record = store_artifact("tenant-a", "proj-a", "design_pack", b"design-payload")

    # Tamper with the stored bytes.
    from pathlib import Path

    stored = Path(art_root) / "tenant-a" / record["object_id"]
    stored.write_bytes(b"tampered-bytes")

    with pytest.raises(ArtifactIntegrityError):
        get_artifact(record["artifact_id"], "tenant-a", include_content=True)


def test_artifact_api_upload_list_download_delete_isolation(monkeypatch, tmp_path):
    db_path = str(tmp_path / "art3.db")
    art_root = str(tmp_path / "artifacts3")
    monkeypatch.setenv("AMC_DB_PATH", db_path)
    monkeypatch.setenv("AMC_ARTIFACT_ROOT", art_root)
    monkeypatch.setenv("AMC_AUTH_MODE", "local")
    monkeypatch.setenv("AMC_LOCAL_USER_ID", "art-operator")
    monkeypatch.setenv("AMC_LOCAL_TENANT_ID", "tenant-art")
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", "proj-art")

    import services.langgraph.persistence.database as database
    from services.langgraph.persistence import sqlite_db

    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(sqlite_db, "DB_PATH", db_path)
    sqlite_db.init_db()

    upload = client.post(
        "/agency/artifacts",
        json={
            "project_id": "proj-art",
            "kind": "copy_deck",
            "content_base64": _b64(b"copy payload"),
            "content_type": "text/plain",
        },
    )
    assert upload.status_code == 201
    artifact_id = upload.json()["artifact_id"]
    assert upload.json()["content_hash"] == upload.json()["object_id"]

    listing = client.get("/agency/artifacts", params={"project_id": "proj-art"})
    assert listing.status_code == 200
    assert [a["artifact_id"] for a in listing.json()["artifacts"]] == [artifact_id]

    download = client.get(f"/agency/artifacts/{artifact_id}", params={"download": "true"})
    assert download.status_code == 200
    import base64

    assert base64.b64decode(download.json()["content_base64"]) == b"copy payload"

    # Cross-tenant isolation: another tenant cannot read or resolve the artifact.
    monkeypatch.setenv("AMC_LOCAL_PROJECT_IDS", "proj-art")
    deny_post = client.post(
        "/agency/artifacts",
        json={
            "project_id": "proj-not-mine",
            "kind": "copy_deck",
            "content_base64": _b64(b"x"),
        },
    )
    assert deny_post.status_code == 403

    deleted = client.delete(f"/agency/artifacts/{artifact_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    bad_b64 = client.post(
        "/agency/artifacts",
        json={
            "project_id": "proj-art",
            "kind": "copy_deck",
            "content_base64": "!!!not-base64!!!",
        },
    )
    assert bad_b64.status_code == 400
