"""ACE v12 agency journey (T53–T56 and the acceptance path), against the real routes.

A client is created; a project is linked; human-authored strategy and identity
inputs are stored; an approver canonises the brand; a plain-English brief is
previewed and launched as real local work; the artifact is independently
verified, reviewed and revised; and only the approved, re-verified version is
exported in a deterministic delivery manifest. Nothing is published, sent or
spent. All names and copy are fictional.
"""

from __future__ import annotations

import pytest

from services.langgraph.tests._ace12_support import OWNER, OWNER2, REQUESTER, REVIEWER, act_as, make_world
from services.langgraph.tests._project_os_support import as_user, client, headers

PALETTE = {"primary": "#5b1a22", "secondary": "#665d52", "surface": "#ece6da", "text": "#121212"}


@pytest.fixture
def journey(monkeypatch, tmp_path):
    w = make_world(monkeypatch, tmp_path)
    act_as(w, REQUESTER)
    c = client.post("/agency-os/clients", json={"display_name": "Halden & Fen (fictional)", "notes": "stoneware studio"}).json()
    w["client"] = c["client"]["client_id"]
    assert client.post(f"/agency-os/clients/{w['client']}/projects", json={"project_id": w["project"]}).status_code == 201
    for kind, text in (("positioning_statement", "Small-batch stoneware for first homes (fictional)."),
                       ("brand_platform", "Made slowly, used daily (fictional)."),
                       ("brand_core", "Voice: plain, warm. Colour story: oxblood on oat (fictional).")):
        r = client.post(f"/projects/{w['project']}/artifacts", json={"artifact_key": kind, "artifact_type": kind,
                                                                     "content_text": text}, headers=headers())
        assert r.status_code == 201, r.text
    act_as(w, REVIEWER)
    r = client.post(f"/projects/{w['project']}/memory", json={
        "scope": "M1_BRAND_CANON", "authority": "BRAND_CANON", "subject_key": "brand.identity",
        "body": {"brand_name": "Halden & Fen", "palette": PALETTE}, "source_refs": ["art:brand_core:v1"]})
    assert r.status_code == 201, r.text
    act_as(w, REQUESTER)
    return w


def _launch(w, brief: str) -> dict:
    r = client.post("/agency-os/missions", json={"brief": brief, "project_id": w["project"]}, headers=headers())
    assert r.status_code == 201, r.text
    return r.json()["mission"]


def test_acceptance_journey_brief_to_verified_export(journey, monkeypatch):
    w = journey
    brief = "Create an SVG logo mark for the spring collection."
    prev = client.post("/agency-os/missions/preview", json={"brief": brief, "project_id": w["project"]}).json()
    assert prev["preview"] and prev["outcome"] == "READY_TO_LAUNCH", prev.get("reasons")
    assert prev["nodes"] and prev["deliverable"]["artifact_type"] == "media_asset"
    assert prev["brand_context"]["admissible"] and prev["cost"]["amount_minor"] == 0

    m = _launch(w, brief)
    assert m["status"] == "AWAITING_APPROVAL" and m["verification"]["status"] == "PASSED"
    artifact_id = m["verification"]["artifact_id"]
    approval_id = m["approval"]["approval_id"]

    vault = {d["artifact_id"]: d for d in client.get(f"/agency-os/projects/{w['project']}/deliverables").json()["deliverables"]}
    assert vault[artifact_id]["release"]["allowed"] is False and "APPROVAL_PENDING" in vault[artifact_id]["release"]["reasons"]
    out = client.post(f"/agency-os/projects/{w['project']}/deliverables/export", json={"artifact_ids": [artifact_id]}).json()["manifest"]
    assert out["items"] == [] and out["excluded"][0]["artifact_id"] == artifact_id

    att = client.get("/agency-os/attention").json()["items"]
    assert any(i["ref"] == approval_id and i["category"] == "APPROVAL" for i in att)

    # The requester cannot approve; a reviewer can.
    assert client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=headers()).status_code == 403
    act_as(w, REVIEWER)
    assert client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=headers()).status_code == 200
    act_as(w, REQUESTER)

    first = client.post(f"/agency-os/projects/{w['project']}/deliverables/export", json={"artifact_ids": [artifact_id]}).json()["manifest"]
    assert [i["artifact_id"] for i in first["items"]] == [artifact_id]
    item = first["items"][0]
    assert item["verification"]["status"] == "PASSED" and item["approval"]["reviewer"] == REVIEWER
    assert first["signature"]["status"] == "UNSIGNED" and first["delivered_externally"] is False
    second = client.post(f"/agency-os/projects/{w['project']}/deliverables/export", json={"artifact_ids": [artifact_id]}).json()["manifest"]
    assert second["manifest_hash"] == first["manifest_hash"]  # idempotent export
    check = client.post("/agency-os/deliverables/verify-manifest", json={"manifest": first}).json()
    assert check["hash_matches"] is True
    tampered = {**first, "items": [{**item, "sha256": "0" * 64}]}
    assert client.post("/agency-os/deliverables/verify-manifest", json={"manifest": tampered}).json()["hash_matches"] is False

    stages = {s["stage"]: s for s in client.get(f"/agency-os/projects/{w['project']}/lifecycle").json()["stages"]}
    assert stages["INTAKE"]["status"] == "DONE" and stages["STRATEGY"]["status"] == "DONE"
    assert stages["IDENTITY"]["status"] == "DONE" and stages["PRODUCTION"]["status"] == "DONE"
    assert stages["REVIEW"]["status"] == "DONE" and stages["DELIVERY"]["status"] == "DONE"
    assert stages["DISTRIBUTION"]["status"] == "LIVE_GATED" and stages["MEASUREMENT"]["status"] == "NOT_MEASURED"

    missions = client.get(f"/agency-os/projects/{w['project']}/missions").json()["missions"]
    assert missions and missions[0]["mission_id"] == m["mission_id"]


def test_t53_signed_manifests_verify_and_detect_tampering(journey, monkeypatch):
    w = journey
    monkeypatch.setenv("AMC_DELIVERY_SIGNING_KEY", "k" * 40)
    m = _launch(w, "Create an SVG logo mark.")
    act_as(w, REVIEWER)
    client.post(f"/approvals/{m['approval']['approval_id']}/decide", json={"decision": "approve"}, headers=headers())
    act_as(w, REQUESTER)
    man = client.post(f"/agency-os/projects/{w['project']}/deliverables/export",
                      json={"artifact_ids": [m["verification"]["artifact_id"]]}).json()["manifest"]
    assert man["signature"]["status"] == "SIGNED"
    assert client.post("/agency-os/deliverables/verify-manifest", json={"manifest": man}).json()["signature_valid"] is True
    forged = {**man, "signature": {**man["signature"], "value": "0" * 64}}
    assert client.post("/agency-os/deliverables/verify-manifest", json={"manifest": forged}).json()["signature_valid"] is False


def test_t54_revision_supersedes_the_old_approval(journey):
    w = journey
    first = _launch(w, "Create an SVG logo mark.")
    artifact_id = first["verification"]["artifact_id"]
    r = client.post(f"/agency-os/projects/{w['project']}/revisions", json={"artifact_id": artifact_id,
                                                                            "note": "Tighten the ring (fictional note)"})
    assert r.status_code == 201 and r.json()["revision"]["version"] == first["verification"]["version"]
    act_as(w, REVIEWER)
    client.post(f"/approvals/{first['approval']['approval_id']}/decide", json={"decision": "reject"}, headers=headers())
    act_as(w, REQUESTER)
    vault = {d["artifact_id"]: d for d in client.get(f"/agency-os/projects/{w['project']}/deliverables").json()["deliverables"]}
    assert vault[artifact_id]["release"]["allowed"] is False
    out = client.post(f"/agency-os/projects/{w['project']}/deliverables/export", json={"artifact_ids": [artifact_id]}).json()["manifest"]
    assert out["items"] == [] and any("REJECTED" in r or "NO_APPROVAL" in r for r in out["excluded"][0]["reasons"])


def test_t55_external_effects_in_a_brief_are_never_dispatched(journey):
    w = journey
    prev = client.post("/agency-os/missions/preview", json={"brief": "Create an SVG logo mark and publish it.",
                                                            "project_id": w["project"]}).json()
    eff = prev["external_effects"]
    assert eff and eff[0]["effect"] == "PUBLISH" and eff[0]["status"] == "LIVE_GATED" and eff[0]["dispatch"].startswith("NOT_DISPATCHED")
    m = _launch(w, "Create an SVG logo mark and publish it.")
    assert m["non_actions"] and m["non_actions"][0]["dispatched"] is False
    assert any(p["predicate_id"] == "P6_PUBLISH_AUTHORIZED" and p["state"] == "NEEDS_HUMAN" for p in m["acceptance_criteria"])


def test_t56_provider_gap_and_missing_brand_are_reported_not_faked(journey, monkeypatch, tmp_path):
    w = journey
    prev = client.post("/agency-os/missions/preview", json={"brief": "Create a product video reel.", "project_id": w["project"]}).json()
    assert prev["outcome"] == "PROVIDER_GAP"
    bare = make_world(monkeypatch, tmp_path)
    prev = client.post("/agency-os/missions/preview", json={"brief": "Create an SVG logo mark.", "project_id": bare["project"]}).json()
    assert prev["outcome"] == "BLOCKED" and any(r.startswith("BRAND_CONTEXT") for r in prev["reasons"])
    assert any(r.startswith("WAITING_ON_PREREQUISITE") for r in prev["reasons"])


def test_offboarding_blocks_new_work_until_open_work_is_closed(journey):
    w = journey
    m = _launch(w, "Create an SVG logo mark.")
    assert client.post(f"/agency-os/clients/{w['client']}/offboarding").status_code == 403  # editor
    as_user(w["mp"], OWNER, role="owner", tenant=w["tenant"])
    assert client.post(f"/agency-os/clients/{w['client']}/offboarding").status_code == 200
    report = client.get(f"/agency-os/clients/{w['client']}/offboarding").json()
    assert not report["can_archive"] and report["pending_approvals"] and "NOT_IMPLEMENTED" in report["retention"]["deletion"]
    assert client.post(f"/agency-os/clients/{w['client']}/archive").status_code == 409
    act_as(w, REQUESTER)
    r = client.post("/agency-os/missions", json={"brief": "Create an SVG logo mark.", "project_id": w["project"]}, headers=headers())
    assert r.status_code == 403
    r = client.post("/actions", json={"capability_id": "sandbox.cms.create_draft", "project_id": w["project"], "environment": "SANDBOX",
                                      "args": {"site": "acme-site", "path": "/x", "title": "t", "body": "b"}}, headers=headers())
    assert r.status_code == 409 and r.json()["error"]["code"] == "CLIENT_NOT_ACTIVE"
    as_user(w["mp"], OWNER2, role="owner", tenant=w["tenant"])
    client.post(f"/approvals/{m['approval']['approval_id']}/decide", json={"decision": "reject"}, headers=headers())
    as_user(w["mp"], OWNER, role="owner", tenant=w["tenant"])
    assert client.post(f"/agency-os/clients/{w['client']}/archive").json()["client"]["status"] == "ARCHIVED"


def test_clients_and_analytics_are_tenant_scoped_and_evidence_only(journey):
    w = journey
    a = client.get("/agency-os/analytics").json()
    reach = next(m for m in a["metrics"] if m["metric"] == "audience_reach")
    assert reach["status"] == "NOT_MEASURED" and reach["value"] is None
    assert all(m.get("source") or m.get("status") == "NOT_MEASURED" for m in a["metrics"])
    as_user(w["mp"], "mallory", role="owner", tenant="tenant-evil-x")
    assert client.get("/agency-os/clients").json()["clients"] == []
    assert client.get(f"/agency-os/clients/{w['client']}").status_code == 404
    assert client.get(f"/agency-os/projects/{w['project']}/lifecycle").status_code == 403


def test_i13_export_rereads_stored_bytes_and_excludes_tampered_ones(journey, monkeypatch):
    # Approved and verified at launch; the bytes at rest change afterwards. Export
    # re-verifies independently of the earlier verdict and refuses the item.
    from services.langgraph.api.routes._project_common import storage_adapter

    w = journey
    m = _launch(w, "Create an SVG logo mark.")
    artifact_id = m["verification"]["artifact_id"]
    act_as(w, REVIEWER)
    client.post(f"/approvals/{m['approval']['approval_id']}/decide", json={"decision": "approve"}, headers=headers())
    act_as(w, REQUESTER)
    export = f"/agency-os/projects/{w['project']}/deliverables/export"
    assert [i["artifact_id"] for i in client.post(export, json={"artifact_ids": [artifact_id]}).json()["manifest"]["items"]] == [artifact_id]
    monkeypatch.setattr(type(storage_adapter()), "get_bytes", lambda self, location: b"<svg>tampered</svg>")
    out = client.post(export, json={"artifact_ids": [artifact_id]}).json()["manifest"]
    assert out["items"] == [] and "CONTENT_HASH_MISMATCH" in out["excluded"][0]["reasons"]
