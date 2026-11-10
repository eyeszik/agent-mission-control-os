"""Authorization of same-actor idempotency receipts after permissions change.

These are local test fixtures, not production approvals or a release attestation.
Some production callbacks are synthetic so that replays can be checked without
rendering, spending or changing an external system.
"""

from __future__ import annotations

import ast
import inspect
from uuid import uuid4

import pytest
from fastapi import HTTPException

from services.langgraph.agency.vnexus import creative_service, fabric_service, intelligence_service, production
from services.langgraph.agency.vnexus.brandbook import service as brandbook
from services.langgraph.agency.vnexus.directions import service as directions
from services.langgraph.api.routes import vnexus as routes
from services.langgraph.security.auth import Principal
from services.langgraph.tests._project_os_support import as_user, client, headers
from services.langgraph.tests._vnexus_support import FULL_DOC, _approve, _draft, make_world


PROJECT_OPERATIONS = (
    "production.identity", "production.video", "production.experience", "production.art_direction", "campaign.plan",
    "brandbook.build", "directions.intent", "directions.generate", "directions.import", "directions.review", "directions.reconstruct",
)


def test_new_idempotent_operations_require_an_explicit_replay_policy():
    # Catch a new route whose operation was not added to the policy matrix.
    calls = (n for n in ast.walk(ast.parse(inspect.getsource(routes))) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "idempotent")
    operations = {n.args[1].value for n in calls if len(n.args) > 1 and isinstance(n.args[1], ast.Constant)}
    assert operations == routes._REPLAY_OPERATIONS
    called = []
    principal = Principal("actor", "tenant", "editor", frozenset())
    with pytest.raises(HTTPException) as exc:
        routes.idempotent(principal, "unreviewed.operation", "key", {}, lambda: called.append(True))
    assert exc.value.status_code == 409 and not called


@pytest.mark.parametrize("operation", PROJECT_OPERATIONS)
def test_project_receipts_require_owner_target_and_scope_access(monkeypatch, tmp_path, operation):
    """A current receipt is not a substitute for authority on all three projects."""
    w = make_world(monkeypatch, tmp_path)
    scope_project = f"prj-vnx-{uuid4().hex[:8]}"
    as_user(monkeypatch, "olivia", role="owner", tenant=w["tenant"])
    created = client.post("/projects", json={"display_name": "Scoped project", "project_id": scope_project,
                                             "slug": scope_project}, headers=headers())
    assert created.status_code == 201, created.text
    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"])

    # Later direction operations recover their scope from a real stored intent.
    intent_id = None
    if operation.startswith("directions.") and operation != "directions.intent":
        _approve(w, _draft(w, "brand", w["brand"], FULL_DOC))
        response = client.post(f"/vnexus/brands/{w['brand']}/directions/intents", headers=headers(), json={
            "scope": "project", "scope_ref": scope_project, "project_id": w["other"],
            "brief": {"asset_role": "LOGO_MARK", "objective": "fixture", "exact_text": "@none"}})
        assert response.status_code == 201, response.text
        intent_id = response.json()["intent"]["intent_id"]

    target = {"scope": "project", "scope_ref": scope_project, "project_id": w["other"]}
    brand_base = f"/vnexus/brands/{w['brand']}"
    direction_base = f"{brand_base}/directions/intents/{intent_id}"
    choices = {
        "production.identity": (production, "produce_identity", f"{brand_base}/production/identity",
                                {**target, "deliverables": ["monogram"]}),
        "production.video": (production, "produce_video", f"{brand_base}/production/video",
                             {**target, "brief": {"objective": "fixture"}}),
        "production.experience": (production, "produce_experience", f"{brand_base}/production/experience",
                                  {**target, "request": {"target": "LANDING_PAGE", "objective": "fixture"}}),
        "production.art_direction": (production, "art_direction", f"{brand_base}/production/art-direction",
                                     {**target, "request": {"objective": "fixture", "medium": "POSTER"}}),
        "campaign.plan": (intelligence_service, "plan_campaign", f"{brand_base}/campaigns", {**target, "request": {
            "campaign_ref": "fixture", "objective": "fixture", "channels": ["web_landing"], "start": "2026-11-09"}}),
        "brandbook.build": (brandbook, "build", f"{brand_base}/brandbook/builds", {**target, "mode": "PREVIEW"}),
        "directions.intent": (directions, "create_intent", f"{brand_base}/directions/intents", {**target, "brief": {
            "asset_role": "LOGO_MARK", "objective": "fixture", "exact_text": "@none"}}),
        "directions.generate": (directions, "generate", f"{direction_base}/generate",
                                {"project_id": w["other"], "route_id": "mock.simulated"}),
        "directions.import": (directions, "import_candidate", f"{direction_base}/candidates", {
            "project_id": w["other"], "slot": 1, "mime": "image/svg+xml", "data_base64": "PHN2Zy8+"}),
        "directions.review": (directions, "create_review", f"{direction_base}/reviews", {
            "project_id": w["other"], "mode": "QUICK", "candidate_ids": ["vdc-fixture"]}),
        "directions.reconstruct": (directions, "reconstruct_candidate", f"{direction_base}/reconstructions", {
            "project_id": w["other"], "candidate_id": "vdc-fixture", "method": "controlled_trace"}),
    }
    module, attribute, path, body = choices[operation]
    calls = []

    def synthetic(*_args, **_kwargs):
        calls.append(operation)
        return {"operation": operation, "qc_projection_version": fabric_service.QC_PROJECTION_VERSION,
                "scope": "synthetic historical receipt"}

    monkeypatch.setattr(module, attribute, synthetic)
    key = {"Idempotency-Key": f"scope-replay-{uuid4().hex}"}
    first = client.post(path, headers=key, json=body)
    assert first.status_code in (200, 201), first.text
    replay = client.post(path, headers=key, json=body)
    assert replay.status_code == first.status_code and replay.json() == first.json()
    assert calls == [operation]

    all_projects = {w["owner"], w["other"], scope_project}
    for revoked in all_projects:
        as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"], projects=",".join(sorted(all_projects - {revoked})))
        refused = client.post(path, headers=key, json=body)
        assert refused.status_code == 403, (operation, revoked, refused.status_code, refused.text)
    as_user(monkeypatch, "alice", role="viewer", tenant=w["tenant"], projects=",".join(sorted(all_projects)))
    assert client.post(path, headers=key, json=body).status_code == 403
    assert calls == [operation]  # no replay or denied request reran a producer


@pytest.mark.parametrize("operation", ("genome.submit", "genome.revert", "branch.fork", "branch.merge", "branch.submit"))
def test_version_and_branch_receipts_require_current_authority(monkeypatch, tmp_path, operation):
    w = make_world(monkeypatch, tmp_path)
    approved = _approve(w, _draft(w, "brand", w["brand"], FULL_DOC))
    branch_path = f"/vnexus/brands/{w['brand']}/branches"

    def fork(name, changes):
        response = client.post(branch_path, headers=headers(), json={"base_version_id": approved["version_id"],
                                                                      "name": name, "changes": {"set": changes}})
        assert response.status_code == 201, response.text
        return response.json()["branch"]

    if operation == "genome.submit":
        draft = _draft(w, "brand", w["brand"], FULL_DOC)
        path, body = f"/vnexus/versions/{draft['version_id']}/submit", None
    elif operation == "genome.revert":
        path, body = f"/vnexus/versions/{approved['version_id']}/revert", None
    elif operation == "branch.fork":
        path, body = branch_path, {"base_version_id": approved["version_id"], "name": "fixture",
                                   "changes": {"set": {"verbal.voice.tone": ["calm"]}}}
    else:
        first_branch = fork("first", {"verbal.voice.tone": ["calm"]})
        if operation == "branch.merge":
            second_branch = fork("second", {"experience.navigation.style": "top-bar"})
            path, body = f"/vnexus/branches/{first_branch['branch_id']}/merge", {
                "other_branch_id": second_branch["branch_id"], "name": "merged"}
        else:
            path, body = f"/vnexus/branches/{first_branch['branch_id']}/submit", None

    key = {"Idempotency-Key": f"version-replay-{uuid4().hex}"}
    first = client.post(path, headers=key, json=body)
    assert first.status_code in (200, 201), first.text
    # A replay is a receipt; it must not settle a pending branch or genome.
    monkeypatch.setattr(creative_service, "settle", lambda *_args: pytest.fail("replay settled a branch"))
    replay = client.post(path, headers=key, json=body)
    assert replay.status_code == first.status_code and replay.json() == first.json()
    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"], projects=w["other"])
    assert client.post(path, headers=key, json=body).status_code == 403
    as_user(monkeypatch, "alice", role="viewer", tenant=w["tenant"], projects=w["owner"])
    assert client.post(path, headers=key, json=body).status_code == 403
