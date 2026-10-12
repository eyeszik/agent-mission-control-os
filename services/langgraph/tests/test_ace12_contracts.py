"""ACE v12 API <-> Zod parity (T57: contract and version compatibility).

Real responses are recorded in packages/shared/tests/fixtures/ace12.json
(regenerate with AMC_REGENERATE_FIXTURES=1). Every run checks that today's
responses still have the recorded structure, and that every enum in
packages/shared/src/schemas/agencyOs.ts equals its Python vocabulary.
packages/shared/tests/agencyOs.test.ts parses the same fixture with the Zod
schemas: backend shape == fixture shape == what the frontend accepts.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from services.langgraph.agency.actions.adapters import adapters
from services.langgraph.agency.actions.fsm import ActionState
from services.langgraph.agency.actions.vocabulary import AutonomyLevel, Environment, ImplStatus, RiskClass
from services.langgraph.agency.agency_os.service import STAGES
from services.langgraph.tests._ace12_support import CMS, REQUESTER, REVIEWER, act_as, approve_all, make_world, propose
from services.langgraph.tests._project_os_support import client, headers
from services.langgraph.tests.test_vnexus_contracts import _shape_matches, structure

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages" / "shared" / "tests" / "fixtures" / "ace12.json"
SCHEMA_TS = ROOT / "packages" / "shared" / "src" / "schemas" / "agencyOs.ts"
PALETTE = {"primary": "#5b1a22", "secondary": "#665d52", "surface": "#ece6da", "text": "#121212"}


def _ts_enum(name: str) -> list[str]:
    text = SCHEMA_TS.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = z\.enum\(\[(.*?)\]\)", text, re.S)
    assert match, name
    return re.findall(r"'([^']+)'", match.group(1))


def test_t57_enums_match_their_python_vocabularies():
    assert _ts_enum("RiskClassSchema") == [c.value for c in RiskClass]
    assert _ts_enum("ActionEnvironmentSchema") == [e.value for e in Environment]
    assert _ts_enum("ActionStateSchema") == [s.value for s in ActionState]
    assert _ts_enum("ImplStatusSchema") == [s.value for s in ImplStatus]
    assert _ts_enum("AutonomyLevelSchema") == [a.value for a in AutonomyLevel]
    assert _ts_enum("LifecycleStageSchema") == [s for s, _ in STAGES]


def capture(monkeypatch, tmp_path) -> dict[str, Any]:
    w = make_world(monkeypatch, tmp_path)
    act_as(w, REQUESTER)
    catalog = client.get("/actions/catalog").json()
    catalog["entries"] = [e for e in catalog["entries"] if e["id"] in {"sandbox.cms.publish_page", "fabric.brand_logo_svg",
                                                                        "vnexus.hosted_text_to_image"}]
    preview = client.post("/actions/preview", json={"capability_id": "sandbox.cms.publish_page", "project_id": w["project"],
                                                    "environment": "SANDBOX", "args": CMS}).json()
    action = propose(w, "sandbox.cms.publish_page", CMS)["action"]
    approve_all(w, action)
    done = client.post(f"/actions/{action['action_id']}/dispatch").json()["action"]
    evidence = client.get(f"/actions/{action['action_id']}/evidence").json()
    stuck = propose(w, "sandbox.cms.publish_page", {**CMS, "path": "/stuck"})["action"]
    approve_all(w, stuck)
    adapters()["sandbox.cms.publish_page"].fault = "timeout_after_effect"
    try:
        client.post(f"/actions/{stuck['action_id']}/dispatch")
    finally:
        adapters()["sandbox.cms.publish_page"].fault = None
    recovery = client.get("/actions/recovery").json()["items"]

    c = client.post("/agency-os/clients", json={"display_name": "Contract Client (fictional)"}).json()["client"]
    client.post(f"/agency-os/clients/{c['client_id']}/projects", json={"project_id": w["project"]})
    for kind in ("positioning_statement", "brand_platform", "brand_core"):
        client.post(f"/projects/{w['project']}/artifacts", json={"artifact_key": kind, "artifact_type": kind,
                                                                 "content_text": f"{kind} (fictional)"}, headers=headers())
    act_as(w, REVIEWER)
    client.post(f"/projects/{w['project']}/memory", json={"scope": "M1_BRAND_CANON", "authority": "BRAND_CANON",
                                                          "subject_key": "brand.identity",
                                                          "body": {"brand_name": "Contract", "palette": PALETTE},
                                                          "source_refs": ["art:brand_core:v1"]})
    act_as(w, REQUESTER)
    brief = {"brief": "Create an SVG logo mark.", "project_id": w["project"]}
    mission_preview = client.post("/agency-os/missions/preview", json=brief).json()
    mission = client.post("/agency-os/missions", json=brief, headers=headers()).json()["mission"]
    act_as(w, REVIEWER)
    client.post(f"/approvals/{mission['approval']['approval_id']}/decide", json={"decision": "approve"}, headers=headers())
    act_as(w, REQUESTER)
    deliverables = client.get(f"/agency-os/projects/{w['project']}/deliverables").json()["deliverables"]
    manifest = client.post(f"/agency-os/projects/{w['project']}/deliverables/export",
                           json={"artifact_ids": [mission["verification"]["artifact_id"]]}).json()["manifest"]
    stale = propose(w, "sandbox.cms.publish_page", {**CMS, "path": "/pending"})["action"]
    return {
        "catalog": catalog, "action_preview": preview, "action": done, "evidence": evidence, "recovery_item": recovery[0],
        "client": client.get("/agency-os/clients").json()["clients"][0],
        "lifecycle": client.get(f"/agency-os/projects/{w['project']}/lifecycle").json(),
        "attention_item": next(i for i in client.get("/agency-os/attention").json()["items"] if i["ref"] or stale),
        "mission_preview": mission_preview, "mission": mission,
        "deliverable": next(d for d in deliverables if d["artifact_id"] == mission["verification"]["artifact_id"]),
        "manifest": manifest, "analytics": client.get("/agency-os/analytics").json(),
    }


def test_t57_recorded_fixture_matches_live_responses(monkeypatch, tmp_path):
    live = capture(monkeypatch, tmp_path)
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(live) == set(recorded)
    problems = _shape_matches(structure(live), structure(recorded))
    assert problems == [], problems
