"""Creative directions Python/TypeScript parity: a fixture recorded from the real /vnexus direction routes parses with
the Zod twins in packages/shared/src/schemas/vnexusDirections.ts.

Regenerate with AMC_REGENERATE_FIXTURES=1 (needs local Chromium: the reconstruction is measured by a real render).
packages/shared/tests/vnexusDirections.test.ts parses the same fixture.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from services.langgraph.agency.vnexus.directions.providers import Health, Task
from services.langgraph.agency.vnexus.directions.records import (AssetRole, EvidenceClass, Gate, GateStatus, ProvenanceClass,
                                                                  ReviewMode, Severity, Verdict)
from services.langgraph.agency.visual.browser import probe_browser
from services.langgraph.tests._project_os_support import as_user, client, headers
from services.langgraph.tests._vnexus_support import FULL_DOC, _approve, _draft, make_world
from services.langgraph.tests.test_vnexus_contracts import _shape_matches, structure
from services.langgraph.tests.test_vnexus_directions import ACCENT, PAPER, b64, disc_png

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages" / "shared" / "tests" / "fixtures" / "vnexus-directions.json"
SCHEMA_TS = ROOT / "packages" / "shared" / "src" / "schemas" / "vnexusDirections.ts"


def _ts_enum(name: str) -> list[str]:
    match = re.search(rf"export const {name} = z\.enum\(\[(.*?)\]\)", SCHEMA_TS.read_text(encoding="utf-8"), re.DOTALL)
    assert match, name
    return re.findall(r"'([^']+)'", match.group(1))


def test_enums_match_the_python_contracts():
    assert _ts_enum("DirectionAssetRoleSchema") == [r.value for r in AssetRole]
    assert _ts_enum("DirectionEvidenceClassSchema") == [e.value for e in EvidenceClass]
    assert _ts_enum("DirectionProvenanceSchema") == [p.value for p in ProvenanceClass]
    assert _ts_enum("DirectionSeveritySchema") == [s.value for s in Severity]
    assert _ts_enum("DirectionReviewModeSchema") == [m.value for m in ReviewMode]
    assert _ts_enum("DirectionVerdictSchema") == [v.value for v in Verdict]
    assert _ts_enum("DirectionGateSchema") == [g.value for g in Gate]
    assert _ts_enum("DirectionGateStatusSchema") == [s.value for s in GateStatus]
    assert _ts_enum("DirectionRouteHealthSchema") == [h.value for h in Health]
    assert _ts_enum("DirectionRouteTaskSchema") == [t.value for t in Task]


def capture(monkeypatch, tmp_path) -> dict:
    from services.langgraph.agency.vnexus.directions.review import LENSES

    w = make_world(monkeypatch, tmp_path)
    _approve(w, _draft(w, "brand", w["brand"], FULL_DOC))
    created = client.post(f"/vnexus/brands/{w['brand']}/directions/intents", headers=headers(), json={
        "scope": "brand", "scope_ref": w["brand"], "project_id": w["owner"],
        "brief": {"asset_role": "LOGO_MARK", "objective": "A mark for a small stoneware studio (fictional)", "exact_text": "@none",
                  "applications": ["favicon 32px"]}}).json()
    base = f"/vnexus/brands/{w['brand']}/directions/intents/{created['intent']['intent_id']}"
    p = {"project_id": w["owner"]}
    blocked = client.post(base + "/generate", json={**p, "route_id": "cloudflare.workers_ai.text_to_image"}, headers=headers()).json()
    generated = client.post(base + "/generate", json={**p, "route_id": "local.foundry_compose"}, headers=headers()).json()
    imported = []
    for slot, data in ((1, disc_png(size=128, ring=(0.18, 0.24, PAPER))), (2, disc_png(size=128, fg=ACCENT, radius=0.25))):
        imported.append(client.post(base + "/candidates", json={**p, "slot": slot, "mime": "image/png", "data_base64": b64(data),
                                                                 "reported": {"rights_basis": "operator-owned (fictional)"}},
                                    headers=headers()).json())
    a, b = (x["candidate"]["candidate_id"] for x in imported)
    probe = client.post(base + "/reviews", json={**p, "mode": "COMPARE", "candidate_ids": [a, b]}, headers=headers()).json()["session"]
    lab = {cid: label for label, cid in probe["labels"].items()}

    def board(cid, value):
        rows = [{"candidate": lab[cid], "seat": "13", "criterion": "safety_privacy_rights", "evidence_class": "OBSERVED",
                 "observation": "no third-party marks or personal data", "gate": "SAFETY_PRIVACY_RIGHTS", "gate_status": "PASS"},
                {"candidate": lab[cid], "seat": "09", "criterion": "intended_vs_apparent", "evidence_class": "INFERRED",
                 "observation": "reads calm rather than playful", "trait": "calm", "cue": "single closed form"}]
        rows += [{"candidate": lab[cid], "seat": s, "criterion": c, "evidence_class": "INFERRED", "observation": c, "score": value}
                 for s in ("01", "02", "03", "05", "10") for c in LENSES[s]["criteria"]]
        return rows
    compare = client.post(base + "/reviews", json={**p, "mode": "COMPARE", "candidate_ids": [a, b],
                                                   "findings": board(a, 8) + board(b, 6)}, headers=headers()).json()
    selection = client.post(base + "/selection", json={**p, "candidate_id": a, "session_id": compare["session"]["session_id"]},
                            headers=headers()).json()
    as_user(monkeypatch, "bob", role="reviewer", tenant=w["tenant"])
    assert client.post(f"/approvals/{selection['approval_id']}/decide", json={"decision": "approve"}, headers=headers()).status_code == 200
    as_user(monkeypatch, "alice", role="editor", tenant=w["tenant"])
    rec = client.post(base + "/reconstructions", json={**p, "candidate_id": a, "method": "controlled_trace"}, headers=headers()).json()
    vec = rec["candidate"]["candidate_id"]
    release = client.post(base + "/reviews", json={**p, "mode": "RELEASE", "candidate_ids": [vec], "findings": [
        {"candidate": vec, "seat": "13", "criterion": "safety_privacy_rights", "evidence_class": "OBSERVED", "observation": "traced locally",
         "gate": "SAFETY_PRIVACY_RIGHTS", "gate_status": "PASS"},
        {"candidate": vec, "seat": "12", "criterion": "channel_fit", "evidence_class": "OBSERVED", "observation": "fits a tab", "score": 7}]},
        headers=headers()).json()
    freeze = client.post(base + "/freeze", json={**p, "master_candidate_id": vec, "session_id": release["session"]["session_id"]},
                         headers=headers()).json()
    return {"routes": client.get("/vnexus/directions/routes").json(), "intent": created, "blocked": blocked, "generated": generated,
            "imported": imported[0], "handoff": client.get(base + "/handoff", params=p).json(), "compare": compare,
            "selection": selection, "reconstruction": rec, "release": release, "freeze": freeze,
            "state": client.get(base, params=p).json(),
            "intents": client.get(f"/vnexus/brands/{w['brand']}/directions/intents", params=p).json()}


@pytest.mark.skipif(not probe_browser().get("available", False), reason="NOT_RUN: local Chromium unavailable")
def test_recorded_fixture_matches_live_responses(monkeypatch, tmp_path):
    live = capture(monkeypatch, tmp_path)
    text = json.dumps(live)
    assert "/tmp/" not in text and "/home/" not in text and "/root/" not in text
    assert live["compare"]["session"]["recommendation"]["verdict"] == "RECOMMENDED_DIRECTION"
    assert live["freeze"]["status"] == "PENDING_GENOME_REVIEW"
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.write_text(json.dumps(live, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(live) == set(recorded)
    for doc in (live, recorded):
        doc["state"].pop("events", None)
        for key in ("compare", "release"):
            doc[key]["session"].pop("measurements", None)
            # Keyed by generated candidate ids: compare the value shape, not the keys.
            doc[key]["session"]["candidates"] = sorted(doc[key]["session"]["candidates"].values())
    assert _shape_matches(structure(live), structure(recorded)) == []
