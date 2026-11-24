"""Owner-project authorization for inherited brand data at project scope."""

from __future__ import annotations

from uuid import uuid4

from services.langgraph.agency.vnexus import production
from services.langgraph.agency.vnexus.genome import document_from_flat
from services.langgraph.tests._project_os_support import as_user, client, headers
from services.langgraph.tests._vnexus_support import FULL_DOC, _approve, _draft, make_world


def test_resolve_and_new_production_require_brand_owner_and_target_access(monkeypatch, tmp_path):
    w = make_world(monkeypatch, tmp_path)
    _approve(w, _draft(w, "brand", w["brand"], FULL_DOC))
    url = f"/vnexus/brands/{w['brand']}/resolve"
    params = {"scope": "project", "scope_ref": w["other"]}
    assert client.get(url, params=params).status_code == 200

    # A same-tenant user of the destination project alone must not inherit
    # another project's brand values without access to that brand's owner.
    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"], projects=w["other"])
    assert client.get(url, params=params).status_code == 403
    monkeypatch.setattr(production, "_run_spec", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected render")))
    response = client.post(f"/vnexus/brands/{w['brand']}/production/identity", headers={"Idempotency-Key": str(uuid4())}, json={
        "scope": "project", "scope_ref": w["other"], "project_id": w["other"], "deliverables": ["monogram"]})
    assert response.status_code == 403, response.text

    # Access to the owner alone is also insufficient for the narrower scope.
    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"], projects=w["owner"])
    assert client.get(url, params=params).status_code == 403
    # Viewers who can access both projects may still read the resolution.
    as_user(monkeypatch, "alice", role="viewer", tenant=w["tenant"], projects=f"{w['owner']},{w['other']}")
    assert client.get(url, params=params).status_code == 200


def test_readiness_branch_comparison_and_twin_require_inherited_source_access(monkeypatch, tmp_path):
    w = make_world(monkeypatch, tmp_path)
    _approve(w, _draft(w, "brand", w["brand"], FULL_DOC))
    local_doc = document_from_flat({"verbal.voice.tone": ["calm"]})
    base = _approve(w, _draft(w, "project", w["other"], local_doc))
    candidate = _draft(w, "project", w["other"], local_doc)
    fork = client.post(f"/vnexus/brands/{w['brand']}/branches", headers=headers(), json={
        "base_version_id": base["version_id"], "name": "fixture", "changes": {"set": {"verbal.voice.tone": ["warm"]}}})
    assert fork.status_code == 201, fork.text
    branch_id = fork.json()["branch"]["branch_id"]
    version_path = f"/vnexus/versions/{candidate['version_id']}"
    compare_path = f"/vnexus/branches/{branch_id}/compare"
    twin_path = f"/vnexus/brands/{w['brand']}/twin/simulate"
    twin_body = {"scope": "project", "scope_ref": w["other"], "changes": {"set": {"verbal.voice.tone": ["warm"]}}}
    assert client.get(f"{version_path}/readiness").status_code == 200
    assert client.get(compare_path).status_code == 200
    assert client.post(twin_path, json=twin_body).status_code == 200

    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"], projects=w["other"])
    assert client.get(f"{version_path}/readiness").status_code == 403
    assert client.post(f"{version_path}/submit", headers=headers()).status_code == 403
    assert client.get(compare_path).status_code == 403
    assert client.post(twin_path, json=twin_body).status_code == 403
    # The user's own draft remains readable; its ancestors are not disclosed.
    assert client.get(version_path).status_code == 200


def test_twin_does_not_expose_inaccessible_child_scope(monkeypatch, tmp_path):
    w = make_world(monkeypatch, tmp_path)
    _approve(w, _draft(w, "brand", w["brand"], FULL_DOC))
    child = _approve(w, _draft(w, "project", w["other"], document_from_flat({"verbal.voice.tone": ["calm"]})))
    base = f"/vnexus/brands/{w['brand']}/twin"
    body = {"scope": "brand", "scope_ref": w["brand"], "changes": {"set": {"verbal.voice.tone": ["warm"]}}}
    full = client.get(base)
    assert full.status_code == 200 and any(s["version_id"] == child["version_id"] for s in full.json()["approved_scopes"])
    assert client.post(f"{base}/simulate", json=body).status_code == 200
    # Owner-project access alone must not reveal the child project's scope or
    # computed descendants. Deny the whole aggregate, not a misleading subset.
    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"], projects=w["owner"])
    assert client.get(base).status_code == 403
    assert client.post(f"{base}/simulate", json=body).status_code == 403
    as_user(monkeypatch, "alice", role="viewer", tenant=w["tenant"], projects=f"{w['owner']},{w['other']}")
    assert client.get(base).status_code == 403  # the graph cannot prove that these are all represented projects
    as_user(monkeypatch, "alice", role="viewer", tenant=w["tenant"], projects="*")
    assert client.get(base).status_code == 200


def test_unscoped_brand_graph_is_fail_closed_for_bounded_project_access(monkeypatch, tmp_path):
    w = make_world(monkeypatch, tmp_path)
    _approve(w, _draft(w, "brand", w["brand"], FULL_DOC))
    secret = "synthetic-other-project-objective"
    made = client.post(f"/vnexus/brands/{w['brand']}/production/art-direction", headers=headers(), json={
        "scope": "brand", "scope_ref": w["brand"], "project_id": w["other"],
        "request": {"objective": secret, "medium": "POSTER"}})
    assert made.status_code == 200, made.text
    graph = f"/vnexus/brands/{w['brand']}/graph"
    twin = f"/vnexus/brands/{w['brand']}/twin"
    scan = f"/vnexus/brands/{w['brand']}/immune/scan"
    scope = {"scope": "brand", "scope_ref": w["brand"]}
    assert secret in client.get(graph).text  # the full-tenant test principal can view it

    # Node records have no consistently enforced project ACL. Even explicitly
    # naming the two known projects does not prove visibility of every node.
    for projects in (w["owner"], f"{w['owner']},{w['other']}"):
        as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"], projects=projects)
        for response in (client.get(graph), client.get(twin), client.post(f"{twin}/simulate", json={
                **scope, "changes": {"set": {"verbal.voice.tone": ["warm"]}}}), client.post(scan, json=scope)):
            assert response.status_code == 403, response.text
            assert secret not in response.text
    # This is a deliberately restrictive interim policy, not an instruction
    # to grant wildcard access to someone who should not have every project.
    as_user(monkeypatch, "alice", role="viewer", tenant=w["tenant"], projects="*")
    assert client.get(graph).status_code == 200
    assert client.get(twin).status_code == 200
