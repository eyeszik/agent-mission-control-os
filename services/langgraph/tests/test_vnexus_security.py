"""VNEXUS security sweep: every route, three hostile principals.

The route list is read from the application, so a route added later is
covered automatically. Path parameters are filled with real ids owned by
tenant A; the requests come from:

* another tenant (must never succeed or learn anything: 403/404/422 only);
* a read-only role in the same tenant (must never write);
* nobody, under production-style auth (must be refused before any handler).
"""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from services.langgraph.app.main import app
from services.langgraph.tests._project_os_support import as_user, client, headers
from services.langgraph.tests._vnexus_support import FULL_DOC, _approve, _draft, make_world

# Routes that hold no tenant data: capability discovery and a pure, labelled simulation.
TENANT_FREE = {("GET", "/vnexus/fabric/providers"), ("POST", "/vnexus/forecast")}
# Tenant-scoped listings: another tenant gets 200 with *its own* (empty) list, checked below.
SCOPED_LISTINGS = {("GET", "/vnexus/brands")}
# Settlement applies a decision already made through /approvals/{id}/decide (approver role and
# separation of duties are enforced there); the same reconciliation runs on every read. It
# holds no authority of its own, which test_settle_by_a_viewer_changes_nothing_without_a_decision proves.
RECONCILE = {("POST", "/vnexus/versions/{version_id}/settle"), ("POST", "/vnexus/branches/{branch_id}/settle")}

# The OpenAPI document is the flattened route table (included routers are not plain APIRoutes).
VNEXUS_ROUTES = sorted({(m.upper(), path) for path, ops in app.openapi()["paths"].items() if path.startswith("/vnexus/")
                        for m in ops if m.upper() in {"GET", "POST", "PUT", "DELETE"}})


@pytest.fixture
def owned(monkeypatch, tmp_path):
    w = make_world(monkeypatch, tmp_path)
    v = _approve(w, _draft(w, "brand", w["brand"], FULL_DOC))
    br = client.post(f"/vnexus/brands/{w['brand']}/branches", json={"base_version_id": v["version_id"], "name": "b",
                     "changes": {"set": {"verbal.voice.tone": ["calm"]}}}, headers=headers()).json()["branch"]
    job = client.post(f"/vnexus/projects/{w['owner']}/media-jobs", json={"provider_id": "local.svg", "request": {"capability": "VECTOR_SVG",
                      "spec": {"svg": '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4" viewBox="0 0 4 4"><title>t</title></svg>'},
                      "width": 4, "height": 4}}, headers=headers()).json()["job"]
    prompt = client.post(f"/vnexus/brands/{w['brand']}/prompts", json={"prompt_id": "p", "document": {
        "intent": "x", "family": "IMAGE", "asset_type": "image"}}).json()["prompt"]
    graph = client.get(f"/vnexus/brands/{w['brand']}/graph").json()
    ids = {"brand_id": w["brand"], "project_id": w["owner"], "version_id": v["version_id"], "branch_id": br["branch_id"],
           "other_id": br["branch_id"], "job_id": job["job_id"], "prompt_version_id": prompt["prompt_version_id"], "prompt_id": "p",
           "node_id": graph["nodes"][0]["node_id"], "edge_id": graph["edges"][0]["edge_id"], "campaign_ref": "c",
           "provider_id": "local.svg"}
    return w, ids


def _url(path: str, ids: dict) -> str:
    def sub(m):
        return ids[m.group(1)]
    url = re.sub(r"\{([a-z_]+)\}", sub, path)
    if path.endswith("/compare"):
        url += f"?from={ids['version_id']}&to={ids['version_id']}"
    if path.endswith("/resolve"):
        url += f"?scope=brand&scope_ref={ids['brand_id']}"
    if path.endswith("/graph/diff"):
        url += "?from=2000-01-01"
    return url


def _body(path: str, ids: dict) -> dict:
    """A plausible body so requests reach authorization instead of failing validation first."""
    target = {"scope": "brand", "scope_ref": ids["brand_id"]}
    if path.endswith("/production/identity"):
        return {**target, "project_id": ids["project_id"], "deliverables": ["monogram"]}
    if path.endswith("/production/art-direction"):
        return {**target, "project_id": ids["project_id"], "request": {"objective": "x", "medium": "POSTER"}}
    if path.endswith("/immune/scan") or path.endswith("/twin/simulate") or path.endswith("/compile") or path.endswith("/regression"):
        return {**target, "changes": {"set": {}}} if path.endswith("/simulate") else target
    if path.endswith("/media-jobs"):
        return {"provider_id": "local.svg", "request": {"capability": "VECTOR_SVG", "spec": {"svg": "<svg/>"}}}
    if path.endswith("/graph/nodes"):
        return {"kind": "Asset", "label": "x"}
    if path.endswith("/feedback"):
        return {"text": "x"}
    if path.endswith("/measurements"):
        return {"campaign_ref": "c", "metric": "m", "value": 1, "unit": "u", "source": "s", "source_ref": "r", "observed_at": "2026-01-01"}
    if path == "/vnexus/brands":
        return {"brand_id": f"x-{uuid4().hex[:6]}", "display_name": "x", "owner_project_id": ids["project_id"]}
    return {}


def _call(method: str, url: str, body: dict):
    kw = {"headers": headers()}
    if method in ("POST", "PUT"):
        kw["json"] = body
    return client.request(method, url, **kw)


def test_route_inventory_is_what_the_sweep_covers():
    assert len(VNEXUS_ROUTES) >= 60, VNEXUS_ROUTES
    assert all(p.startswith("/vnexus/") for _, p in VNEXUS_ROUTES)


def test_another_tenant_can_neither_read_nor_write_anything(owned, monkeypatch):
    w, ids = owned
    as_user(monkeypatch, "mallory", role="admin", tenant=f"tenant-evil-{uuid4().hex[:6]}")
    leaks = []
    for method, path in VNEXUS_ROUTES:
        if (method, path) in TENANT_FREE:
            continue
        r = _call(method, _url(path, ids), _body(path, ids))
        if (method, path) in SCOPED_LISTINGS and r.status_code == 200:
            if any(str(v) in r.text for v in (ids["brand_id"], ids["project_id"], w["tenant"])):
                leaks.append(f"{method} {path} -> 200 with tenant A data")
            continue
        if r.status_code < 400 or r.status_code >= 500:
            leaks.append(f"{method} {path} -> {r.status_code}")
    assert not leaks, leaks


def test_read_only_role_cannot_write(owned, monkeypatch):
    w, ids = owned
    as_user(monkeypatch, "victor", role="viewer", tenant=w["tenant"])
    writes = []
    reads_ok = 0
    for method, path in VNEXUS_ROUTES:
        if (method, path) in TENANT_FREE:
            continue
        r = _call(method, _url(path, ids), _body(path, ids))
        is_read = method == "GET" or path.endswith(("/compare", "/immune/scan", "/twin/simulate", "/graph/impact", "/regression")) \
            or path.endswith("/compile") or (method, path) in RECONCILE
        if is_read:
            reads_ok += r.status_code < 400
        elif r.status_code < 400:
            writes.append(f"{method} {path} -> {r.status_code}")
    assert not writes, writes
    assert reads_ok >= 15  # the same viewer can read: refusals are about writing, not a broken route


def test_settle_by_a_viewer_changes_nothing_without_a_decision(owned, monkeypatch):
    w, ids = owned
    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"])
    pending = _draft(w, "brand", w["brand"], FULL_DOC)
    sub = client.post(f"/vnexus/versions/{pending['version_id']}/submit", headers=headers())
    assert sub.status_code == 200, sub.text
    as_user(monkeypatch, "victor", role="viewer", tenant=w["tenant"])
    r = client.post(f"/vnexus/versions/{pending['version_id']}/settle", headers=headers())
    assert r.status_code == 200 and r.json()["version"]["status"] == "IN_REVIEW"
    approved = client.get(f"/vnexus/versions/{ids['version_id']}", headers=headers()).json()["version"]
    assert approved["status"] == "APPROVED"


def test_every_route_requires_authentication(owned, monkeypatch):
    _, ids = owned
    monkeypatch.setenv("AMC_AUTH_MODE", "supabase")
    unguarded = []
    for method, path in VNEXUS_ROUTES:
        r = _call(method, _url(path, ids), _body(path, ids))
        if r.status_code not in (401, 403, 503):
            unguarded.append(f"{method} {path} -> {r.status_code}")
    assert not unguarded, unguarded


def test_client_supplied_authority_fields_are_rejected(owned):
    w, ids = owned
    for url, body in [
        ("/vnexus/brands", {**_body("/vnexus/brands", ids), "tenant_id": "x"}),
        (f"/vnexus/brands/{ids['brand_id']}/versions", {"scope": "brand", "scope_ref": ids["brand_id"],
                                                       "document": FULL_DOC.model_dump(mode="json"), "approved_by": "me"}),
        (f"/vnexus/projects/{ids['project_id']}/media-jobs", {**_body("/media-jobs", ids), "provider_id": "local.svg",
                                                              "request": {"capability": "VECTOR_SVG", "spec": {}}, "authorized_by": "me"}),
        (f"/vnexus/brands/{ids['brand_id']}/immune/remediate", {"scope": "brand", "scope_ref": ids["brand_id"], "finding_ids": ["x"],
                                                               "force": True}),
    ]:
        r = client.post(url, json=body, headers=headers())
        assert r.status_code == 422, (url, r.status_code, r.text)
