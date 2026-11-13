"""Historical version and branch receipts must respect the brand source too."""

from __future__ import annotations

from uuid import uuid4

import pytest

from services.langgraph.agency.vnexus.genome import document_from_flat
from services.langgraph.tests._project_os_support import as_user, client, headers
from services.langgraph.tests._vnexus_support import FULL_DOC, _approve, _draft, make_world


@pytest.mark.parametrize("operation", ("genome.create", "genome.submit", "genome.revert", "branch.fork", "branch.merge", "branch.submit"))
def test_replay_requires_brand_owner_and_narrow_project(monkeypatch, tmp_path, operation):
    w = make_world(monkeypatch, tmp_path)
    _approve(w, _draft(w, "brand", w["brand"], FULL_DOC))
    local_doc = document_from_flat({"verbal.voice.tone": ["calm"]})
    base = _approve(w, _draft(w, "project", w["other"], local_doc))
    brand_branches = f"/vnexus/brands/{w['brand']}/branches"

    def fork(name, changes):
        response = client.post(brand_branches, headers=headers(), json={"base_version_id": base["version_id"], "name": name,
                                                                        "changes": {"set": changes}})
        assert response.status_code == 201, response.text
        return response.json()["branch"]

    if operation == "genome.create":
        path = f"/vnexus/brands/{w['brand']}/versions"
        body = {"scope": "project", "scope_ref": w["other"], "document": local_doc.model_dump(mode="json")}
    elif operation == "genome.submit":
        draft = _draft(w, "project", w["other"], local_doc)
        path, body = f"/vnexus/versions/{draft['version_id']}/submit", None
    elif operation == "genome.revert":
        path, body = f"/vnexus/versions/{base['version_id']}/revert", None
    elif operation == "branch.fork":
        path, body = brand_branches, {"base_version_id": base["version_id"], "name": "fork",
                                      "changes": {"set": {"verbal.voice.tone": ["warm"]}}}
    else:
        a = fork("a", {"verbal.voice.tone": ["warm"]})
        if operation == "branch.merge":
            b = fork("b", {"experience.navigation.style": "top-bar"})
            path, body = f"/vnexus/branches/{a['branch_id']}/merge", {"other_branch_id": b["branch_id"], "name": "merge"}
        else:
            path, body = f"/vnexus/branches/{a['branch_id']}/submit", None
    key = {"Idempotency-Key": f"cross-project-{uuid4().hex}"}
    first = client.post(path, headers=key, json=body)
    assert first.status_code in (200, 201), first.text
    replay = client.post(path, headers=key, json=body)
    assert replay.status_code == first.status_code and replay.json() == first.json()

    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"], projects=w["other"])
    assert client.post(path, headers=key, json=body).status_code == 403
    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"], projects=w["owner"])
    assert client.post(path, headers=key, json=body).status_code == 403
