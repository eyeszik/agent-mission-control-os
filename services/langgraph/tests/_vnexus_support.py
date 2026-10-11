"""Shared fixtures for the VNEXUS test suites: a tenant with two projects, a brand, and approval helpers."""

from __future__ import annotations

from uuid import uuid4

from services.langgraph.agency.vnexus.genome import GenomeConstraint, GenomeDocument, document_from_flat
from services.langgraph.tests._project_os_support import as_user, client, headers


def _c(cid: str, key: str, kind: str, **params) -> GenomeConstraint:
    return GenomeConstraint(constraint_id=cid, key=key, kind=kind, params=params)


BRAND_DOC = document_from_flat(
    {"visual.color.ink": "#14161a", "visual.color.paper": "#f7f4ee", "visual.color.accent": "#c2410c",
     "visual.typography.display": "Schibsted Grotesk", "verbal.voice.register": "plain", "strategy.positioning.promise":
     "Made slowly, used daily"},
    constraints=[_c("ink-lock", "visual.color.ink", "IMMUTABLE"), _c("ink-hex", "visual.color.ink", "HEX_COLOR"),
                 _c("ink-contrast", "visual.color.ink", "MIN_CONTRAST", against="visual.color.paper", ratio=4.5),
                 _c("register", "verbal.voice.register", "ALLOWED_VALUES", values=["plain", "warm"]),
                 _c("promise-required", "strategy.positioning.promise", "REQUIRED")],
)


def make_world(monkeypatch, tmp_path) -> dict:
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path / "exports"))
    monkeypatch.setenv("AMC_OBJECT_STORAGE_BACKEND", "local")
    tenant = f"tenant-vnx-{uuid4().hex[:8]}"
    owner, other = f"prj-vnx-{uuid4().hex[:8]}", f"prj-vnx-{uuid4().hex[:8]}"
    as_user(monkeypatch, "olivia", role="owner", tenant=tenant)
    for pid in (owner, other):
        r = client.post("/projects", json={"display_name": f"VNX {pid}", "project_id": pid, "slug": pid}, headers=headers())
        assert r.status_code == 201, r.text
    as_user(monkeypatch, "alice", role="editor", tenant=tenant)
    brand_id = f"brand-{uuid4().hex[:8]}"
    r = client.post("/vnexus/brands", json={"brand_id": brand_id, "display_name": "Halden & Fen (fictional)",
                                            "owner_project_id": owner}, headers=headers())
    assert r.status_code == 201, r.text
    return {"tenant": tenant, "owner": owner, "other": other, "brand": brand_id, "mp": monkeypatch}


def _draft(w, scope: str, scope_ref: str, doc: GenomeDocument, **extra):
    r = client.post(f"/vnexus/brands/{w['brand']}/versions", json={"scope": scope, "scope_ref": scope_ref,
                                                                   "document": doc.model_dump(mode="json"), **extra}, headers=headers())
    assert r.status_code == 201, r.text
    return r.json()["version"]


def _approve(w, version: dict, reviewer: str = "bob") -> dict:
    as_user(w["mp"], "alice", role="editor", tenant=w["tenant"])
    sub = client.post(f"/vnexus/versions/{version['version_id']}/submit", headers=headers())
    assert sub.status_code == 200, sub.text
    approval_id = sub.json()["version"]["approval_id"]
    as_user(w["mp"], reviewer, role="reviewer", tenant=w["tenant"])
    d = client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=headers())
    assert d.status_code == 200, d.text
    got = client.get(f"/vnexus/versions/{version['version_id']}")
    assert got.status_code == 200, got.text
    as_user(w["mp"], "alice", role="editor", tenant=w["tenant"])
    return got.json()["version"]
