"""Project workspaces: identity, idempotent initialization, isolation, mirror."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from _project_os_support import TENANT, as_user, client, export_root, headers, new_project  # noqa: F401
from services.langgraph.agency.project_os.storage import LocalStorageAdapter, R2StorageAdapter, StorageUnavailable
from services.langgraph.agency.project_os.workspace import (
    WorkspacePathError,
    folder_path,
    map_legacy_relative,
    mirror_legacy_export,
    project_root,
)
from services.langgraph.persistence.projects import list_storage_objects, reconcile_storage_objects, register_storage_object


@pytest.fixture(autouse=True)
def _admin(monkeypatch, export_root):  # noqa: F811
    as_user(monkeypatch, "owner-1")


def test_create_project_initializes_canonical_state_and_mirror(export_root):  # noqa: F811
    project = new_project("Northwind Coffee", brand_name="Northwind")
    assert project["lifecycle_state"] == "ACTIVE"
    assert project["workspace_schema_version"] == "amc-workspace/v2"
    detail = client.get(f"/projects/{project['project_id']}").json()
    assert detail["snapshot"]["project_id"] == project["project_id"]
    events = client.get(f"/projects/{project['project_id']}/events").json()["events"]
    assert events[0]["event_type"] == "PROJECT_CREATED" and events[0]["sequence"] == 1
    root = project_root(export_root, TENANT, project["project_id"])
    manifest = json.loads((root / ".amc" / "manifests" / "project-manifest.json").read_text())
    assert manifest["project_id"] == project["project_id"]
    assert "relational store is canonical" in manifest["authority_note"]
    # Folders are lazy: only the admin readme exists after initialization.
    assert sorted(p.name for p in root.iterdir() if not p.name.startswith(".")) == ["00_admin"]
    memory = client.get(f"/projects/{project['project_id']}/memory").json()["memory"]
    assert [m["subject_key"] for m in memory] == ["project.charter"]


def test_same_idempotency_key_never_creates_two_projects():
    key = {"Idempotency-Key": str(uuid4())}
    body = {"display_name": "Replay Co", "project_id": f"prj-rep-{uuid4().hex[:8]}"}
    first = client.post("/projects", json=body, headers=key)
    second = client.post("/projects", json=body, headers=key)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    conflict = client.post("/projects", json={**body, "display_name": "Other"}, headers=key)
    assert conflict.status_code == 409
    listed = [p for p in client.get("/projects").json()["projects"] if p["project_id"] == body["project_id"]]
    assert len(listed) == 1


def test_project_without_explicit_id_requires_tenant_wide_scope(monkeypatch):
    as_user(monkeypatch, "scoped-1", projects="prj-only-this")
    response = client.post("/projects", json={"display_name": "Nope"}, headers=headers())
    assert response.status_code == 403


def test_viewer_role_cannot_create_projects(monkeypatch):
    as_user(monkeypatch, "viewer-1", role="viewer")
    assert client.post("/projects", json={"display_name": "Nope", "project_id": "prj-viewer-x"}, headers=headers()).status_code == 403


def test_slug_is_unique_within_tenant():
    slug = f"dup-{uuid4().hex[:6]}"
    ok = client.post("/projects", json={"display_name": "A", "slug": slug, "project_id": f"prj-a-{uuid4().hex[:6]}"}, headers=headers())
    clash = client.post("/projects", json={"display_name": "B", "slug": slug, "project_id": f"prj-b-{uuid4().hex[:6]}"}, headers=headers())
    assert ok.status_code == 201 and clash.status_code == 409


def test_different_tenant_cannot_read_or_write_project(monkeypatch):
    project = new_project("Tenant A Brand")
    as_user(monkeypatch, "intruder", tenant="tenant-other")
    pid = project["project_id"]
    assert client.get(f"/projects/{pid}").status_code == 403
    assert client.get(f"/projects/{pid}/events").status_code == 403
    assert client.post(f"/projects/{pid}/threads", json={"title": "x"}).status_code == 403
    # Claiming the same project id from another tenant is refused outright.
    hijack = client.post("/projects", json={"display_name": "Hijack", "project_id": pid}, headers=headers())
    assert hijack.status_code == 403


def test_same_tenant_principal_scoped_to_other_project_is_denied(monkeypatch):
    project = new_project("Scoped Brand")
    as_user(monkeypatch, "member-2", projects="prj-something-else")
    assert client.get(f"/projects/{project['project_id']}").status_code == 403
    listed = client.get("/projects").json()["projects"]
    assert all(p["project_id"] != project["project_id"] for p in listed)


def test_lifecycle_transitions_are_guarded():
    pid = new_project()["project_id"]
    assert client.post(f"/projects/{pid}/lifecycle", json={"target": "PAUSED"}).json()["project"]["lifecycle_state"] == "PAUSED"
    assert client.post(f"/projects/{pid}/lifecycle", json={"target": "PAUSED"}).status_code == 409
    assert client.post(f"/projects/{pid}/lifecycle", json={"target": "ARCHIVED"}).status_code == 200
    assert client.post(f"/projects/{pid}/lifecycle", json={"target": "ACTIVE"}).status_code == 200


def test_workspace_paths_cannot_escape_the_project(tmp_path):
    root = tmp_path / "projects" / "t" / "p"
    with pytest.raises(WorkspacePathError):
        folder_path(root, "04_brand", "..")
    with pytest.raises(WorkspacePathError):
        folder_path(root, "not-a-folder")
    with pytest.raises(WorkspacePathError):
        project_root(tmp_path, "../evil", "p")


def test_legacy_export_is_dual_materialized_with_verified_hashes(tmp_path):
    legacy = tmp_path / "acme-1234abcd"
    (legacy / "business").mkdir(parents=True)
    (legacy / "business" / "overview.json").write_text('{"a": 1}\n')
    (legacy / "branding" / "design-system").mkdir(parents=True)
    (legacy / "branding" / "design-system" / "tokens.json").write_text("{}\n")
    (legacy / "branding" / "raw-brand-data.json").write_text("{}\n")
    (legacy / "workspace-package.json").write_text('{"run": true}\n')
    project_dir = tmp_path / "projects" / "t" / "p"
    result = mirror_legacy_export(project_dir=project_dir, run_id="run-1", legacy_root=legacy)
    assert result["hashes_verified"] is True and result["file_count"] == 4
    assert (project_dir / "03_strategy" / "business" / "overview.json").read_text() == '{"a": 1}\n'
    assert (project_dir / "06_design" / "design-system" / "tokens.json").is_file()
    assert (project_dir / ".amc" / "runs" / "run-1" / "workspace-package.json").is_file()
    assert (legacy / "workspace-package.json").is_file(), "legacy export must be left in place"
    assert map_legacy_relative("branding/rendered/hero.svg") == "08_creative/rendered/hero.svg"


def test_interrupted_mirror_is_repaired_by_rerunning(tmp_path):
    legacy = tmp_path / "legacy"
    (legacy / "business").mkdir(parents=True)
    (legacy / "business" / "a.json").write_text("1\n")
    project_dir = tmp_path / "proj"
    target = project_dir / "03_strategy" / "business" / "a.json"
    target.parent.mkdir(parents=True)
    target.write_text("partial")  # simulate a crash mid-copy
    result = mirror_legacy_export(project_dir=project_dir, run_id="run-2", legacy_root=legacy)
    assert result["hashes_verified"] is True
    assert target.read_text() == "1\n"


def test_object_storage_is_content_addressed_and_reconciled(export_root):  # noqa: F811
    pid = new_project()["project_id"]
    adapter = LocalStorageAdapter(export_root)
    stored = adapter.put_bytes(tenant_id=TENANT, project_id=pid, data=b"hello")
    assert adapter.put_bytes(tenant_id=TENANT, project_id=pid, data=b"hello").storage_uri == stored.storage_uri
    register_storage_object(tenant_id=TENANT, project_id=pid, stored=stored, mime_type="text/plain")
    path = project_root(export_root, TENANT, pid) / ".amc" / "objects" / stored.content_hash[:2] / stored.content_hash
    path.unlink()
    report = reconcile_storage_objects(pid, adapter)
    assert report["missing"] and not report["present"]
    assert {obj.status.value for obj in list_storage_objects(pid)} == {"MISSING"}


def test_r2_binding_fails_closed_without_exposing_credentials(monkeypatch):
    monkeypatch.setenv("AMC_R2_ACCESS_KEY_ID", "id-should-not-leak")
    monkeypatch.setenv("AMC_R2_SECRET_ACCESS_KEY", "secret-should-not-leak")
    adapter = R2StorageAdapter()
    status = adapter.status()
    assert status["available"] is False and status["binding"] == "UNVERIFIED_EXTERNAL_BINDING"
    assert "should-not-leak" not in json.dumps(status)
    with pytest.raises(StorageUnavailable):
        adapter.put_bytes(tenant_id="t", project_id="p", data=b"x")


def test_capabilities_report_truthful_statuses(monkeypatch):
    pid = new_project()["project_id"]
    caps = client.get(f"/projects/{pid}/capabilities").json()
    assert caps["object_storage"]["backend"] == "LOCAL"
    assert caps["paid_media"]["execution_available"] is False
    assert caps["publication"]["live_available"] is False
    status = client.get("/project-os/status").json()
    assert status["capabilities"]["publication"] == "DRY_RUN_ONLY"
    assert status["reliability"]["services"]["scheduler"]["objectives"]["scheduler_delay_seconds"] == "GAP_NO_BASELINE"


def test_production_config_rejects_unreviewed_remote_object_storage(monkeypatch):
    from services.langgraph.app.config import production_config_errors

    monkeypatch.setenv("AMC_ENV", "production")
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "r2")
    assert any("R2 stays fail-closed" in error for error in production_config_errors())
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    assert not any("OBJECT_STORAGE" in error for error in production_config_errors())
