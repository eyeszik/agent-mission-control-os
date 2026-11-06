"""/ucpo routes: authentication, tenant isolation, operator role, idempotency, linker, preview."""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.request
from pathlib import Path

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.ucpo.preview import serve
from services.langgraph.tests._project_os_support import TENANT, as_user, client, export_root, headers, new_project  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = json.loads((ROOT / "sample_ucpo_website.json").read_text())


def _compile(project_id: str, key: str | None = None):
    return client.post(f"/ucpo/projects/{project_id}/sites", json={"site_id": "halden", "brief": SAMPLE},
                       headers={"Idempotency-Key": key} if key else headers())


def test_compile_is_idempotent_traceable_and_unresolved_until_built(monkeypatch, export_root):  # noqa: F811
    as_user(monkeypatch, "alice")
    project = new_project("UCPO API")["project_id"]
    first = _compile(project, "ucpo-key-1")
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["compile_coverage"]["unresolved_until_rendered"] > 0 and body["external_effects"] == "none"
    replay = _compile(project, "ucpo-key-1")
    assert replay.status_code == 201 and replay.json() == body
    listed = client.get(f"/ucpo/projects/{project}/sites").json()["sites"]
    assert [s["site_id"] for s in listed] == ["halden"]
    view = client.get(f"/ucpo/projects/{project}/sites/halden").json()
    assert view["release"]["allowed"] is False and view["job"]["state"] == "SCHEDULED"
    trace = client.get(f"/ucpo/projects/{project}/sites/halden/trace/req.index.s1.heading").json()
    assert trace["status"]["status"] == "UNRESOLVED" and trace["ir"] == ["section:index-s1.heading"]
    assert client.get(f"/ucpo/projects/{project}/sites/halden/trace/req.invented").status_code == 404
    omissions = client.get(f"/ucpo/projects/{project}/sites/halden/omissions").json()["omissions"]
    assert omissions and all(o["status"] == "UNRESOLVED" for o in omissions)
    impact = client.post(f"/ucpo/projects/{project}/sites/halden/impact", json={"req_ids": ["req.visit.s1.heading"]})
    assert impact.status_code == 200 and "release_proof" in impact.json()["regenerate"]
    repair = client.get(f"/ucpo/projects/{project}/sites/halden/repair/req.a11y.automated").json()
    assert repair["applied"] is False and repair["proposal"]
    assert client.get(f"/ucpo/projects/{project}/sites/absent").status_code == 404

    # Framework binding: proposals in the framework's own ref format, resolvable by its resolver; nothing is written.
    from services.langgraph.agency.operating_framework.refs import resolve_ref
    from services.langgraph.agency.project_os.storage import LocalStorageAdapter

    bound = client.get(f"/ucpo/projects/{project}/sites/halden/framework-bindings").json()
    by_task = {p["task_id"]: p for p in bound["proposals"]}
    assert by_task["AGM-10-003"]["status"] == "PROPOSED" and by_task["AGM-10-014"]["status"] == "STAGE_NOT_PRODUCED"
    resolved = resolve_ref(by_task["AGM-10-003"]["artifact_ref"], tenant_id=TENANT, project_id=project,
                           adapter=LocalStorageAdapter(export_root))
    assert resolved["status"] == "OK", resolved
    assert {n["task_id"] for n in bound["not_covered"]} >= {"AGM-10-006", "AGM-24-008"}


def test_other_tenant_viewer_and_bad_input_are_refused(monkeypatch, export_root):  # noqa: F811
    as_user(monkeypatch, "alice")
    project = new_project("UCPO isolation")["project_id"]
    assert _compile(project).status_code == 201
    as_user(monkeypatch, "mallory", tenant="tenant-other")
    for response in (client.get(f"/ucpo/projects/{project}/sites/halden"), _compile(project),
                     client.post(f"/ucpo/projects/{project}/sites/halden/build")):
        assert response.status_code in {403, 404}, response.text
    as_user(monkeypatch, "victor", role="viewer")
    assert _compile(project).status_code == 403
    assert client.post(f"/ucpo/projects/{project}/sites/halden/build").status_code == 403
    as_user(monkeypatch, "alice")
    bad = client.post(f"/ucpo/projects/{project}/sites", json={"site_id": "../x", "brief": SAMPLE}, headers=headers())
    assert bad.status_code == 422
    smuggled = client.post(f"/ucpo/projects/{project}/sites", headers=headers(),
                           json={"site_id": "s2", "brief": {**SAMPLE, "tenant_id": "tenant-other"}})
    assert smuggled.status_code == 422


def test_framework_bindings_name_real_catalog_tasks():
    from services.langgraph.agency.operating_framework.catalog import load_catalog
    from services.langgraph.agency.ucpo.framework import BINDINGS, NOT_COVERED

    catalog = load_catalog()
    ids = {t.task_id for t in catalog.tasks} if hasattr(catalog, "tasks") else {t["task_id"] for t in catalog["tasks"]}
    assert set(BINDINGS) | set(NOT_COVERED) <= ids and not set(BINDINGS) & set(NOT_COVERED)


def test_capabilities_route_reports_disciplines_and_gaps(monkeypatch):
    as_user(monkeypatch, "alice")
    caps = client.get("/ucpo/capabilities").json()
    assert len(caps["disciplines"]) == 15 and len(caps["presentation_systems"]) == 5 and len(caps["prompt_modules"]) == 16
    assert caps["generation"]["image"]["status"] == "CAPABILITY_GAP"
    assert caps["deployment"].startswith("NOT_AUTHORIZED")


def test_preview_serves_only_a_matching_export_on_loopback():
    export = {"index.html": base64.b64encode(b"<!doctype html><title>t</title><p>Halden Fen</p>").decode()}
    digest = canonical_hash(sorted((p, hashlib.sha256(base64.b64decode(b)).hexdigest()) for p, b in export.items()))
    refused = serve(export, expected_output_hash="0" * 64)
    assert refused.reachable_endpoint is None and refused.cleanup_state == "NOTHING_CREATED"
    assert serve({"../x": export["index.html"]}, expected_output_hash=digest).reachable_endpoint is None
    running = serve(export, expected_output_hash=digest)
    try:
        assert running.reachable_endpoint.startswith("http://127.0.0.1:")
        assert running.matching_build_revision == digest
        with urllib.request.urlopen(running.reachable_endpoint, timeout=5) as resp:  # noqa: S310 - loopback only
            assert b"Halden Fen" in resp.read() and resp.headers["X-Content-Type-Options"] == "nosniff"
    finally:
        assert running.stop().cleanup_state == "CLEANED"
