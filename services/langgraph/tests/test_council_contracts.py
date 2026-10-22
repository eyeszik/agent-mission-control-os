"""Mission council API <-> Zod parity.

Real responses are recorded in packages/shared/tests/fixtures/mission-council.json
(regenerate with AMC_REGENERATE_FIXTURES=1). Each run checks that today's responses
still have the recorded structure and that every enum in
packages/shared/src/schemas/missionCouncil.ts equals its Python vocabulary;
packages/shared/tests/missionCouncil.test.ts parses the same fixture with the Zod
schemas, so backend shape == fixture shape == what the frontend accepts.
"""

from __future__ import annotations

import json
import os
import re
import typing
from pathlib import Path

from services.langgraph.agency.council import contracts
from services.langgraph.tests.council_support import (
    client,
    council,  # noqa: F401 - fixture
    create_idea,
    decide,
    dispatch,
    key,
)
from services.langgraph.tests.test_vnexus_contracts import _shape_matches, structure

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages" / "shared" / "tests" / "fixtures" / "mission-council.json"
SCHEMA_TS = ROOT / "packages" / "shared" / "src" / "schemas" / "missionCouncil.ts"


def _ts_enum(name: str) -> list[str]:
    match = re.search(rf"export const {name} = z\.enum\(\[(.*?)\]\)", SCHEMA_TS.read_text(encoding="utf-8"), re.DOTALL)
    assert match, name
    return re.findall(r"'([^']+)'", match.group(1))


def test_enums_match_their_python_vocabularies():
    assert _ts_enum("CouncilEngineSchema") == list(contracts.ENGINES)
    assert _ts_enum("MissionStatusSchema") == list(typing.get_args(contracts.MissionStatus))
    assert _ts_enum("MissionPhaseSchema") == list(typing.get_args(contracts.Phase))
    assert _ts_enum("CouncilSeatSchema") == list(typing.get_args(contracts.Seat))
    assert _ts_enum("RiskSeveritySchema") == list(typing.get_args(contracts.Severity))
    assert _ts_enum("ModelModeSchema") == list(typing.get_args(contracts.ModelMode))
    assert _ts_enum("SensitivitySchema") == list(typing.get_args(contracts.Sensitivity))
    assert _ts_enum("CouncilEventTypeSchema") == list(contracts.COUNCIL_EVENT_TYPES)


def test_every_emitted_event_type_is_in_the_vocabulary():
    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "services/langgraph/agency/council").rglob("*.py"))
    emitted = set(re.findall(r'emit\((?:row, |ctx, )?"([A-Z_]+)"', source))
    assert emitted and emitted <= set(contracts.COUNCIL_EVENT_TYPES), sorted(emitted - set(contracts.COUNCIL_EVENT_TYPES))


def capture(monkeypatch, project_id: str) -> dict:
    idea = create_idea(project_id)
    gated = client.get(f"/missions/{dispatch(idea['idea_id']).json()['mission_id']}").json()
    decide(monkeypatch, gated["approval"]["approval_id"], "approve")
    client.post(f"/missions/{gated['mission_id']}/resume", headers=key())
    completed = client.get(f"/missions/{gated['mission_id']}").json()
    paused = client.get(f"/missions/{dispatch(idea['idea_id']).json()['mission_id']}").json()
    blueprint = client.post(f"/missions/ideas/{idea['idea_id']}/blueprints", headers=key()).json()
    promoted = client.post(f"/missions/blueprints/{blueprint['blueprint_id']}/promote", headers=key()).json()
    return {
        "engines": client.get("/missions/engines").json(),
        "tools": client.get("/missions/tools").json(),
        "idea": idea,
        "idea_page": client.get("/missions/ideas", params={"project_id": project_id}).json(),
        "idea_detail": client.get(f"/missions/ideas/{idea['idea_id']}").json(),
        "mission_paused": paused,
        "mission_completed": completed,
        "mission_page": client.get("/missions", params={"project_id": project_id}).json(),
        "timeline": client.get(f"/missions/{completed['mission_id']}/timeline").json(),
        "checkpoints": client.get(f"/missions/{completed['mission_id']}/checkpoints").json(),
        "tool_audits": client.get(f"/missions/{completed['mission_id']}/tool-audits").json(),
        "blueprint": promoted,
    }


def test_recorded_fixture_matches_live_responses(monkeypatch, council):
    live = capture(monkeypatch, council["project_id"])
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(live) == set(recorded)
    # Engine availability and the tool allowlist depend on installed extras; their item shape is what matters.
    problems = _shape_matches(structure(live), structure(recorded))
    assert problems == [], problems
    assert {e["event_type"] for e in live["timeline"]["events"]} <= set(contracts.COUNCIL_EVENT_TYPES)
