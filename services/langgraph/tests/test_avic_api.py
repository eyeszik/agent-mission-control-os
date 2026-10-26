"""/avic API: the operator path over the AVIC service, plus a security sweep of every /avic route.

The sweep reads the route table from the application, so a route added later is covered
automatically: another tenant, a read-only role and an unauthenticated caller are each refused.
Tests that need local Chromium skip with an explicit NOT_RUN reason; they never fake a pass.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

import pytest

from services.langgraph.agency.visual.browser import probe_browser
from services.langgraph.app.main import app
from services.langgraph.tests._project_os_support import as_user, client, export_root, headers, new_project  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = json.loads((ROOT / "sample_avic_request.json").read_text())
NEEDS_BROWSER = pytest.mark.skipif(not probe_browser()["available"], reason="NOT_RUN: node, Chromium or @playwright/test missing")
ASSET = SAMPLE["requirement"]["asset_id"]
BODY = {"requirement": SAMPLE["requirement"], "style_profile": SAMPLE["style_profile"], "seed": SAMPLE["seed"]}
AVIC_ROUTES = sorted({(m.upper(), path) for path, ops in app.openapi()["paths"].items() if path.startswith("/avic/")
                      for m in ops if m.upper() in {"GET", "POST", "PUT", "DELETE"}})
TENANT_FREE = {("GET", "/avic/capabilities")}
WRITES = {"/assets", "/edits", "/recompile", "/approval", "/release"}


def _base(project: str) -> str:
    return f"/avic/projects/{project}/assets"


@pytest.fixture
def owned(monkeypatch, export_root):  # noqa: F811
    as_user(monkeypatch, "alice")
    project = new_project("AVIC API")["project_id"]
    r = client.post(_base(project), json=BODY, headers=headers())
    assert r.status_code == 201, r.text
    return project


def _url(path: str, project: str) -> str:
    return re.sub(r"\{([a-z_]+)\}", lambda m: {"project_id": project, "asset_id": ASSET}[m.group(1)], path)


def _body(path: str, svg_sha: str) -> dict:
    if path.endswith("/edits"):
        return {"op": "recolor", "args": {"object_id": "motif-ring-inner", "palette_key": "fog", "field": "stroke"},
                "base_svg_sha256": svg_sha}
    if path.endswith("/assets"):
        return BODY
    return {}


def _call(method: str, url: str, body: dict):
    kw: dict = {"headers": headers()}
    if method == "POST":
        kw["json"] = body
    return client.request(method, url, **kw)


def test_route_inventory_is_what_the_sweep_covers():
    paths = {p for _, p in AVIC_ROUTES}
    assert len(AVIC_ROUTES) == 10, AVIC_ROUTES
    assert {"/avic/projects/{project_id}/assets/{asset_id}/edits", "/avic/projects/{project_id}/assets/{asset_id}/master.svg"} <= paths


def test_another_tenant_learns_nothing(owned, monkeypatch):
    sha = client.get(f"{_base(owned)}/{ASSET}").json()["svg_sha256"]
    as_user(monkeypatch, "mallory", role="admin", tenant=f"tenant-evil-{uuid4().hex[:6]}")
    leaks = [f"{m} {p} -> {r.status_code}" for m, p in AVIC_ROUTES if (m, p) not in TENANT_FREE
             for r in [_call(m, _url(p, owned), _body(p, sha))] if r.status_code < 400 or r.status_code >= 500]
    assert not leaks, leaks


def test_read_only_role_reads_but_cannot_write(owned, monkeypatch):
    from services.langgraph.tests._project_os_support import TENANT

    sha = client.get(f"{_base(owned)}/{ASSET}").json()["svg_sha256"]
    as_user(monkeypatch, "victor", role="viewer", tenant=TENANT)
    writes, reads = [], 0
    for method, path in AVIC_ROUTES:
        r = _call(method, _url(path, owned), _body(path, sha))
        if method == "GET":
            reads += r.status_code == 200 or (path.endswith("preview.png") and r.status_code == 404)
        elif r.status_code < 400:
            writes.append(f"{method} {path} -> {r.status_code}")
    assert not writes, writes
    assert reads == sum(m == "GET" for m, _ in AVIC_ROUTES)


def test_every_route_requires_authentication(owned, monkeypatch):
    monkeypatch.setenv("AMC_AUTH_MODE", "supabase")
    unguarded = [f"{m} {p} -> {r.status_code}" for m, p in AVIC_ROUTES
                 for r in [_call(m, _url(p, owned), _body(p, "0" * 64))] if r.status_code not in (401, 403, 503)]
    assert not unguarded, unguarded


def test_client_supplied_authority_is_rejected(owned):
    for url, body in [
        (_base(owned), {**BODY, "brand": {"palette": {"x": "#ff00ff"}}}),
        (_base(owned), {**BODY, "approved_by": "me"}),
        (f"{_base(owned)}/{ASSET}/edits", {"op": "recolor", "args": {}}),                      # no base: refused
        (f"{_base(owned)}/{ASSET}/edits", {**_body("/edits", "0" * 64), "force": True}),
        (f"{_base(owned)}/{ASSET}/release", {"approval_id": "x", "tenant_id": "other"}),
    ]:
        r = client.post(url, json=body, headers=headers())
        assert r.status_code == 422, (url, r.status_code, r.text)


def test_stored_svg_is_served_inert(owned):
    r = client.get(f"{_base(owned)}/{ASSET}/master.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"
    assert hashlib.sha256(r.content).hexdigest() == client.get(f"{_base(owned)}/{ASSET}").json()["svg_sha256"]


def test_unknown_assets_and_bad_ids_are_404(owned):
    for path in ("nope", "NOPE", "..%2Fx"):
        assert client.get(f"{_base(owned)}/{path}").status_code == 404, path
        assert client.get(f"{_base(owned)}/{path}/master.svg").status_code == 404, path


@NEEDS_BROWSER
def test_operator_path_edit_conflict_recovery_approval_release(owned, monkeypatch):
    view = client.get(f"{_base(owned)}/{ASSET}").json()
    assert view["evaluation"]["passed"] and view["consistency"] == {"consistent": True, "stale": []}
    assert any("recolor" in o["operations"] for o in view["objects"]) and view["palette"]
    assert client.get(f"{_base(owned)}/{ASSET}/preview.png").content.startswith(b"\x89PNG")
    base = view["svg_sha256"]
    edit = {"op": "recolor", "args": {"object_id": "motif-ring-inner", "palette_key": "fog", "field": "stroke"},
            "base_svg_sha256": base}
    key = {"Idempotency-Key": str(uuid4())}
    first = client.post(f"{_base(owned)}/{ASSET}/edits", json=edit, headers=key)
    assert first.status_code == 200 and first.json()["status"] == "EVALUATED", first.text
    assert client.post(f"{_base(owned)}/{ASSET}/edits", json=edit, headers=key).json() == first.json()  # replay
    stale = client.post(f"{_base(owned)}/{ASSET}/edits", json={**edit, "args": {**edit["args"], "palette_key": "amber"}},
                        headers=headers())
    assert stale.status_code == 409 and stale.json()["detail"]["status"] == "CONFLICT"
    again = client.post(f"{_base(owned)}/{ASSET}/recompile", headers=headers())
    assert again.status_code == 200 and all(a["action"] == "reused_unchanged" for a in again.json()["artifacts"].values())
    current = client.get(f"{_base(owned)}/{ASSET}").json()
    assert current["svg_sha256"] != base and current["consistency"]["consistent"]
    blocked = client.post(f"{_base(owned)}/{ASSET}/release", json={"approval_id": None}, headers=headers()).json()
    assert blocked["status"] == "BLOCKED" and blocked["manifest"]["external_effects"] == "none"
    opened = client.post(f"{_base(owned)}/{ASSET}/approval", headers=headers()).json()
    assert opened["status"] == "PENDING"
    assert client.post(f"/approvals/{opened['approval_id']}/decide", json={"decision": "approve"}, headers=headers()).status_code == 403
    as_user(monkeypatch, "bob", role="approver")
    assert client.post(f"/approvals/{opened['approval_id']}/decide", json={"decision": "approve"}, headers=headers()).status_code == 200
    as_user(monkeypatch, "alice")
    done = client.post(f"{_base(owned)}/{ASSET}/release", json={"approval_id": opened["approval_id"]}, headers=headers()).json()
    assert done["status"] == "RELEASED_LOCAL", done
    final = client.get(f"{_base(owned)}/{ASSET}").json()
    assert final["release"]["release_allowed"] and any(a["current"] and a["decision"] == "approve" and a["reviewer"] == "bob" for a in final["approvals"]), final["approvals"]


def test_capabilities_are_the_registry():
    from services.langgraph.agency.avic.capabilities import CAPABILITIES

    body = client.get("/avic/capabilities").json()
    assert [c["name"] for c in body["capabilities"]] == [c.name for c in CAPABILITIES]
    assert body["renderer"]["concurrency"] >= 1 and body["brand"]["palette"]
