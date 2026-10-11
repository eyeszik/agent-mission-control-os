"""VNEXUS brand genome: resolution rules, persistence, approval binding, isolation and audit integrity.

API tests go through the real routes, including the existing
``/approvals/{id}/decide`` route, so separation of duties is the production rule.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from services.langgraph.agency.vnexus.genome import (
    ConflictReason,
    GenomeConstraint,
    GenomeDocument,
    GenomeLayer,
    GenomeTransitionError,
    Scope,
    VersionStatus,
    ancestor_refs,
    diff_documents,
    document_from_flat,
    next_status,
    resolve,
    scope_ref_project,
)
from services.langgraph.persistence.database import table, transaction
from services.langgraph.tests._project_os_support import as_user, client, headers

ROOT = Path(__file__).resolve().parents[3]
PARITY_FIXTURE = ROOT / "apps" / "web" / "tests" / "fixtures" / "vnexus-genome-parity.json"


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


def layer(scope: str, ref: str, doc: GenomeDocument, status: str = "APPROVED") -> GenomeLayer:
    return GenomeLayer(scope=scope, scope_ref=ref, status=status, document=doc)


# --------------------------------------------------------------------------- pure rules


def test_inheritance_immutability_and_constraint_violation():
    child = document_from_flat({"visual.color.ink": "#777777", "visual.color.accent": "#1d4ed8", "verbal.voice.register": "loud",
                                "experience.navigation.style": "top-bar"})
    result = resolve([layer("brand", "b", BRAND_DOC), layer("project", "p", child)])
    assert result.values["visual.color.ink"] == "#14161a"          # immutable parent wins
    assert result.values["visual.color.accent"] == "#1d4ed8"       # ordinary override applies
    assert result.values["verbal.voice.register"] == "plain"       # value outside ALLOWED_VALUES rejected
    assert result.sources["visual.color.accent"] == "p" and result.sources["visual.color.ink"] == "b"
    reasons = {(c.key, c.reason) for c in result.conflicts}
    assert reasons == {("visual.color.ink", ConflictReason.IMMUTABLE_OVERRIDE),
                       ("verbal.voice.register", ConflictReason.CONSTRAINT_VIOLATION)}
    assert all(f.passed for f in result.findings)
    assert result.authoritative


def test_unapproved_layers_never_authoritative_and_preview_is_labelled():
    draft = document_from_flat({"visual.color.accent": "#1d4ed8"})
    auth = resolve([layer("brand", "b", BRAND_DOC), layer("project", "p", draft, "DRAFT")])
    assert auth.values["visual.color.accent"] == "#c2410c"
    assert [c.reason for c in auth.conflicts] == [ConflictReason.UNAPPROVED_OVERRIDE]
    preview = resolve([layer("brand", "b", BRAND_DOC), layer("project", "p", draft, "DRAFT")], preview_ref="p")
    assert preview.values["visual.color.accent"] == "#1d4ed8" and not preview.authoritative and preview.preview_scope == "p"
    assert preview.resolution_hash != auth.resolution_hash


def test_scope_order_required_and_contrast_findings():
    weak = document_from_flat({"visual.color.ink": "#cccccc", "visual.color.paper": "#ffffff"},
                              constraints=[_c("contrast", "visual.color.ink", "MIN_CONTRAST", against="visual.color.paper", ratio=4.5),
                                           _c("needs-voice", "verbal.voice.register", "REQUIRED")])
    out = resolve([layer("project", "p", BRAND_DOC), layer("brand", "b", weak)])
    assert out.conflicts[0].reason is ConflictReason.SCOPE_ORDER
    alone = resolve([layer("brand", "b", weak)])
    failed = {f.constraint_id for f in alone.findings if not f.passed}
    assert failed == {"contrast", "needs-voice"}
    assert {f.constraint_id for f in alone.blocking} == failed


def test_child_cannot_redefine_parent_constraint():
    child = document_from_flat({}, constraints=[_c("register", "verbal.voice.register", "ALLOWED_VALUES", values=["loud"])])
    out = resolve([layer("brand", "b", BRAND_DOC), layer("project", "p", child)])
    assert [c.reason for c in out.conflicts] == [ConflictReason.CONSTRAINT_VIOLATION]
    assert out.constraint_owner["register"] == "b"


def test_resolution_is_deterministic_and_diff_is_exact():
    a = resolve([layer("brand", "b", BRAND_DOC)])
    b = resolve([layer("brand", "b", GenomeDocument.model_validate(json.loads(json.dumps(BRAND_DOC.model_dump(mode="json")))))])
    assert a.resolution_hash == b.resolution_hash and BRAND_DOC.content_hash == GenomeDocument.model_validate(
        BRAND_DOC.model_dump(mode="json")).content_hash
    after = document_from_flat({**BRAND_DOC.flatten(), "visual.color.accent": "#1d4ed8", "verbal.voice.tone": "calm"},
                               constraints=list(BRAND_DOC.constraints[1:]))
    del_key = dict(after.flatten())
    del_key.pop("strategy.positioning.promise")
    after = document_from_flat(del_key, constraints=list(after.constraints))
    d = diff_documents(BRAND_DOC, after)
    assert [c.key for c in d.added] == ["verbal.voice.tone"]
    assert [c.key for c in d.removed] == ["strategy.positioning.promise"]
    assert [(c.key, c.before, c.after) for c in d.modified] == [("visual.color.accent", "#c2410c", "#1d4ed8")]
    assert d.constraints_removed == ("ink-lock",) and not d.constraints_added


def test_lifecycle_matrix_and_scope_paths():
    assert next_status(VersionStatus.DRAFT, "submit") is VersionStatus.IN_REVIEW
    assert next_status(VersionStatus.IN_REVIEW, "approve") is VersionStatus.APPROVED
    for status, action in [("APPROVED", "submit"), ("REJECTED", "submit"), ("DRAFT", "approve"), ("SUPERSEDED", "approve"),
                           ("EXPERIMENTAL", "submit")]:
        with pytest.raises(GenomeTransitionError):
            next_status(VersionStatus(status), action)
    assert scope_ref_project(Scope.COMPONENT, "p1/home/hero", brand_owner_project="o") == "p1"
    for scope, ref in [(Scope.PAGE, "p1"), (Scope.PROJECT, "p1/home"), (Scope.ASSET, "p1/home/hero"), (Scope.PAGE, "../x")]:
        with pytest.raises(ValueError):
            scope_ref_project(scope, ref, brand_owner_project="o")
    assert ancestor_refs(Scope.ASSET, "p1/home/hero/logo", "b") == [
        (Scope.BRAND, "b"), (Scope.PROJECT, "p1"), (Scope.PAGE, "p1/home"), (Scope.COMPONENT, "p1/home/hero"),
        (Scope.ASSET, "p1/home/hero/logo")]


def test_document_validation_rejects_malformed_input():
    for bad in ({"chromosomes": {"visual": {"Bad Key": 1}}}, {"chromosomes": {"mood": {"x": 1}}},
                {"constraints": [{"constraint_id": "r", "key": "visual.x", "kind": "RANGE", "params": {"min": 5, "max": 1}}]},
                {"constraints": [{"constraint_id": "p", "key": "visual.x", "kind": "IMMUTABLE", "params": {"regex": ".*"}}]},
                {"schema_version": "other"}):
        with pytest.raises(ValueError):
            GenomeDocument.model_validate(bad)


def test_web_precheck_parity_fixture_matches_python_resolution():
    """apps/web/lib/design/brand-genome.ts must resolve the TS-expressible subset identically (checked in vitest)."""
    cases = []
    specs = [
        ("approved inheritance", [("brand", "b", "APPROVED", {"visual.color": "blue", "verbal.voice": "calm"}, []),
                                  ("project", "p", "APPROVED", {"visual.color": "red"}, [])]),
        ("immutable and unapproved", [("brand", "b", "APPROVED", {"visual.logo": "approved"}, ["visual.logo"]),
                                      ("project", "p", "APPROVED", {"visual.logo": "different", "visual.size": 3}, []),
                                      ("page", "p/home", "EXPERIMENTAL", {"visual.logo": "other"}, [])]),
        ("reversed scope", [("project", "p", "APPROVED", {"strategy.a": 1}, []), ("brand", "b", "APPROVED", {"strategy.a": 2}, [])]),
        ("same value under lock", [("brand", "b", "APPROVED", {"visual.mark": "ring"}, ["visual.mark"]),
                                   ("asset", "p/h/c/a", "APPROVED", {"visual.mark": "ring"}, [])]),
    ]
    for name, layers in specs:
        py_layers, ts_layers = [], []
        for scope, ref, status, values, immutable in layers:
            doc = document_from_flat(values, constraints=[_c(f"lock-{k.replace('.', '-')}", k, "IMMUTABLE") for k in immutable])
            py_layers.append(layer(scope, ref, doc, status))
            ts_layers.append({"scope": scope, "scopeId": ref, "authority": "APPROVED" if status == "APPROVED" else status,
                              "values": values, "immutableKeys": immutable})
        out = resolve(py_layers)
        cases.append({"name": name, "layers": ts_layers, "expected": {
            "values": out.values, "conflicts": [{"key": c.key, "reason": c.reason.value, "scopeId": c.scope_ref} for c in out.conflicts],
            "appliedScopes": list(out.applied_scopes)}})
    doc = {"generated_by": "services/langgraph/tests/test_vnexus_genome.py", "cases": cases}
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if PARITY_FIXTURE.exists() and not _regenerate():
        assert PARITY_FIXTURE.read_text() == text, "parity fixture is stale: AMC_REGENERATE_FIXTURES=1 pytest this file"
    else:
        PARITY_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        PARITY_FIXTURE.write_text(text)


def _regenerate() -> bool:
    import os

    return os.environ.get("AMC_REGENERATE_FIXTURES") == "1"


# --------------------------------------------------------------------------- API + persistence


@pytest.fixture
def world(monkeypatch, tmp_path):
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


def test_approval_flow_immutability_supersession_and_revert(world):
    w = world
    v1 = _draft(w, "brand", w["brand"], BRAND_DOC)
    assert v1["status"] == "DRAFT" and v1["version"] == 1 and v1["content_hash"] == BRAND_DOC.content_hash
    sub = client.post(f"/vnexus/versions/{v1['version_id']}/submit", headers=headers()).json()["version"]
    assert sub["status"] == "IN_REVIEW" and sub["approval_id"]
    # Editing a version in review is refused; so is the author approving it.
    edit = client.put(f"/vnexus/versions/{v1['version_id']}", json={"expected_revision": 1, "document": BRAND_DOC.model_dump(mode="json")})
    assert edit.status_code == 409
    own = client.post(f"/approvals/{sub['approval_id']}/decide", json={"decision": "approve"}, headers=headers())
    assert own.status_code == 403
    as_user(w["mp"], "bob", role="reviewer", tenant=w["tenant"])
    assert client.post(f"/approvals/{sub['approval_id']}/decide", json={"decision": "approve"}, headers=headers()).status_code == 200
    approved = client.post(f"/vnexus/versions/{v1['version_id']}/settle").json()["version"]
    assert approved["status"] == "APPROVED" and approved["decided_by"] == "bob"
    as_user(w["mp"], "alice", role="editor", tenant=w["tenant"])
    frozen = client.put(f"/vnexus/versions/{v1['version_id']}", json={"expected_revision": 1, "document": BRAND_DOC.model_dump(mode="json")})
    assert frozen.status_code == 409 and "APPROVED" in frozen.text

    doc2 = document_from_flat({**BRAND_DOC.flatten(), "visual.color.accent": "#1d4ed8"}, constraints=list(BRAND_DOC.constraints))
    v2 = _approve(w, _draft(w, "brand", w["brand"], doc2))
    assert v2["status"] == "APPROVED" and v2["parent_version_id"] == v1["version_id"]
    assert client.get(f"/vnexus/versions/{v1['version_id']}").json()["version"]["status"] == "SUPERSEDED"

    rev = client.post(f"/vnexus/versions/{v1['version_id']}/revert", headers=headers())
    assert rev.status_code == 201, rev.text
    v3 = rev.json()["version"]
    assert v3["status"] == "DRAFT" and v3["origin"] == "REVERT" and v3["origin_ref"] == v1["version_id"]
    assert v3["content_hash"] == v1["content_hash"] and v3["version"] == 3
    cmp = client.get("/vnexus/compare", params={"from": v2["version_id"], "to": v3["version_id"]}).json()
    assert [m["key"] for m in cmp["diff"]["modified"]] == ["visual.color.accent"]

    trail = client.get(f"/vnexus/brands/{w['brand']}/audit").json()
    assert trail["verification"]["intact"] is True
    actions = [(e["subject_id"], e["action"]) for e in trail["entries"]]
    assert (v1["version_id"], "approve") in actions and (v1["version_id"], "supersede") in actions


def test_child_scope_cannot_override_immutable_parent(world):
    w = world
    _approve(w, _draft(w, "brand", w["brand"], BRAND_DOC))
    child_doc = document_from_flat({"visual.color.ink": "#777777", "visual.color.accent": "#1d4ed8"})
    child = _draft(w, "project", w["owner"], child_doc)
    ready = client.get(f"/vnexus/versions/{child['version_id']}/readiness").json()["readiness"]
    assert ready["ready"] is False and ready["conflicts"][0]["reason"] == "IMMUTABLE_OVERRIDE"
    blocked = client.post(f"/vnexus/versions/{child['version_id']}/submit", headers=headers())
    assert blocked.status_code == 409 and blocked.json()["detail"]["readiness"]["conflicts"]
    preview = client.get(f"/vnexus/brands/{w['brand']}/resolve", params={"scope": "project", "scope_ref": w["owner"],
                                                                         "preview_version_id": child["version_id"]}).json()
    assert preview["resolution"]["values"]["visual.color.ink"] == "#14161a"
    assert preview["resolution"]["authoritative"] is False
    fixed = document_from_flat({"visual.color.accent": "#1d4ed8"})
    edited = client.put(f"/vnexus/versions/{child['version_id']}", json={"expected_revision": 1, "document": fixed.model_dump(mode="json")})
    assert edited.status_code == 200 and edited.json()["version"]["revision"] == 2
    stale = client.put(f"/vnexus/versions/{child['version_id']}", json={"expected_revision": 1, "document": fixed.model_dump(mode="json")})
    assert stale.status_code == 409 and "stale revision" in stale.text
    _approve(w, client.get(f"/vnexus/versions/{child['version_id']}").json()["version"])
    resolved = client.get(f"/vnexus/brands/{w['brand']}/resolve", params={"scope": "page", "scope_ref": f"{w['owner']}/home"}).json()
    assert resolved["resolution"]["values"]["visual.color.accent"] == "#1d4ed8"
    assert [x["scope"] for x in resolved["layers"]] == ["brand", "project"] and resolved["resolution"]["authoritative"]


def test_reject_withdraw_and_ancestor_change_during_review(world):
    w = world
    v = _draft(w, "brand", w["brand"], BRAND_DOC)
    sub = client.post(f"/vnexus/versions/{v['version_id']}/submit", headers=headers()).json()["version"]
    wd = client.post(f"/vnexus/versions/{v['version_id']}/withdraw")
    assert wd.status_code == 200 and wd.json()["version"]["status"] == "DRAFT"
    as_user(w["mp"], "bob", role="reviewer", tenant=w["tenant"])
    assert client.post(f"/approvals/{sub['approval_id']}/decide", json={"decision": "approve"}, headers=headers()).status_code == 409
    as_user(w["mp"], "alice", role="editor", tenant=w["tenant"])
    sub2 = client.post(f"/vnexus/versions/{v['version_id']}/submit", headers=headers()).json()["version"]
    as_user(w["mp"], "bob", role="reviewer", tenant=w["tenant"])
    assert client.post(f"/approvals/{sub2['approval_id']}/decide", json={"decision": "reject"}, headers=headers()).status_code == 200
    rejected = client.post(f"/vnexus/versions/{v['version_id']}/settle").json()["version"]
    assert rejected["status"] == "REJECTED"
    as_user(w["mp"], "alice", role="editor", tenant=w["tenant"])
    assert client.post(f"/vnexus/versions/{v['version_id']}/submit", headers=headers()).status_code == 409

    # A child in review is refused if the approved parent changes underneath it.
    _approve(w, _draft(w, "brand", w["brand"], BRAND_DOC))
    child = _draft(w, "project", w["owner"], document_from_flat({"visual.color.accent": "#1d4ed8"}))
    child_sub = client.post(f"/vnexus/versions/{child['version_id']}/submit", headers=headers()).json()["version"]
    locked_accent = document_from_flat({**BRAND_DOC.flatten()}, constraints=[*BRAND_DOC.constraints,
                                                                             _c("accent-lock", "visual.color.accent", "IMMUTABLE")])
    _approve(w, _draft(w, "brand", w["brand"], locked_accent))
    as_user(w["mp"], "bob", role="reviewer", tenant=w["tenant"])
    assert client.post(f"/approvals/{child_sub['approval_id']}/decide", json={"decision": "approve"}, headers=headers()).status_code == 200
    settled = client.post(f"/vnexus/versions/{child['version_id']}/settle").json()["version"]
    assert settled["status"] == "DRAFT"
    trail = client.get(f"/vnexus/brands/{w['brand']}/audit", params={"subject_id": child["version_id"]}).json()["entries"]
    assert trail[-1]["action"] == "refuse" and "ancestor" in trail[-1]["detail"]["reason"]


def test_isolation_roles_and_unknown_ids(world, monkeypatch):
    w = world
    v = _draft(w, "brand", w["brand"], BRAND_DOC)
    as_user(monkeypatch, "mallory", role="admin", tenant=f"tenant-other-{uuid4().hex[:6]}")
    assert client.get(f"/vnexus/brands/{w['brand']}").status_code == 404
    assert client.get(f"/vnexus/versions/{v['version_id']}").status_code == 404
    assert client.post(f"/vnexus/brands/{w['brand']}/versions", json={"scope": "project", "scope_ref": w["owner"],
                                                                     "document": BRAND_DOC.model_dump(mode="json")},
                       headers=headers()).status_code == 404
    # A project the principal may not access, within the right tenant.
    as_user(monkeypatch, "carol", role="editor", tenant=w["tenant"], projects=w["other"])
    assert client.get(f"/vnexus/versions/{v['version_id']}").status_code == 403
    assert client.get(f"/vnexus/brands/{w['brand']}/resolve", params={"scope": "brand", "scope_ref": w["brand"]}).status_code == 403
    # Read-only roles cannot write.
    as_user(monkeypatch, "victor", role="viewer", tenant=w["tenant"])
    r = client.post(f"/vnexus/brands/{w['brand']}/versions", json={"scope": "project", "scope_ref": w["other"],
                                                                  "document": BRAND_DOC.model_dump(mode="json")}, headers=headers())
    assert r.status_code == 403
    # Malformed scope refs and body fields are rejected, not guessed.
    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"])
    bad = client.post(f"/vnexus/brands/{w['brand']}/versions", json={"scope": "page", "scope_ref": w["owner"],
                                                                     "document": BRAND_DOC.model_dump(mode="json")}, headers=headers())
    assert bad.status_code == 422
    extra = client.post(f"/vnexus/brands/{w['brand']}/versions", json={"scope": "brand", "scope_ref": w["brand"], "tenant_id": "x",
                                                                       "document": BRAND_DOC.model_dump(mode="json")}, headers=headers())
    assert extra.status_code == 422


def test_tampering_is_detected(world):
    w = world
    v = _draft(w, "brand", w["brand"], BRAND_DOC)
    with transaction(write=True) as db:
        doc = BRAND_DOC.model_dump(mode="json")
        doc["chromosomes"]["visual"]["color.accent"] = "#000000"
        from services.langgraph.persistence.database import json_param

        db.execute(f"UPDATE {table('vnexus_genome_versions')} SET document = ? WHERE version_id = ?", (json_param(doc), v["version_id"]))
    assert client.get(f"/vnexus/versions/{v['version_id']}").status_code == 409
    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('vnexus_audit_log')} SET actor = 'mallory' WHERE subject_id = ?", (v["version_id"],))
    verification = client.get(f"/vnexus/brands/{w['brand']}/audit").json()["verification"]
    assert verification["intact"] is False and verification["reason"] == "entry content changed"


def test_settle_refuses_an_approval_bound_to_other_content(world):
    w = world
    v = _draft(w, "brand", w["brand"], BRAND_DOC)
    sub = client.post(f"/vnexus/versions/{v['version_id']}/submit", headers=headers()).json()["version"]
    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('approvals')} SET subject_hash = ? WHERE approval_id = ?", ("0" * 64, sub["approval_id"]))
    as_user(w["mp"], "bob", role="reviewer", tenant=w["tenant"])
    assert client.post(f"/approvals/{sub['approval_id']}/decide", json={"decision": "approve"}, headers=headers()).status_code == 200
    settled = client.post(f"/vnexus/versions/{v['version_id']}/settle").json()["version"]
    assert settled["status"] == "DRAFT"


def test_one_approved_version_per_scope_is_a_database_invariant(world):
    w = world
    a = _approve(w, _draft(w, "brand", w["brand"], BRAND_DOC))
    b = _draft(w, "brand", w["brand"], BRAND_DOC)
    with pytest.raises(Exception):
        with transaction(write=True) as db:
            db.execute(f"UPDATE {table('vnexus_genome_versions')} SET status = 'APPROVED' WHERE version_id = ?", (b["version_id"],))
    assert client.get(f"/vnexus/versions/{a['version_id']}").json()["version"]["status"] == "APPROVED"
