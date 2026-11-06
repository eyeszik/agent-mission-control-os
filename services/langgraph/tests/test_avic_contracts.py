"""AVIC Python/TypeScript parity: a fixture recorded from the real /avic routes parses with the Zod twins.

Regenerate with AMC_REGENERATE_FIXTURES=1 (needs local Chromium: the fixture is a real render).
packages/shared/tests/avic.test.ts parses the same fixture, so backend shape == fixture shape ==
what the frontend accepts.
"""

from __future__ import annotations

import json
import os
import re
import typing
from pathlib import Path
from uuid import uuid4

from services.langgraph.agency.avic.contracts import CapabilityState, Result
from services.langgraph.tests._project_os_support import as_user, client, export_root, headers, new_project  # noqa: F401
from services.langgraph.tests.test_avic_api import ASSET, BODY, NEEDS_BROWSER
from services.langgraph.tests.test_vnexus_contracts import _shape_matches, structure

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages" / "shared" / "tests" / "fixtures" / "avic.json"
SCHEMA_TS = ROOT / "packages" / "shared" / "src" / "schemas" / "avic.ts"


def _ts_enum(name: str) -> list[str]:
    match = re.search(rf"export const {name} = z\.enum\(\[(.*?)\]\)", SCHEMA_TS.read_text(encoding="utf-8"), re.DOTALL)
    assert match, name
    return re.findall(r"'([^']+)'", match.group(1))


def test_enums_match_the_python_contracts():
    from services.langgraph.agency.avic.capabilities import STATES

    assert _ts_enum("AvicCheckResultSchema") == [r.value for r in Result]
    assert set(_ts_enum("AvicCapabilityStateSchema")) == STATES
    assert set(_ts_enum("AvicProfileStateSchema")) == {s.value for s in CapabilityState}
    from services.langgraph.api.routes.avic import EditRequest

    assert _ts_enum("AvicEditOpSchema") == list(typing.get_args(EditRequest.model_fields["op"].annotation))


def capture(monkeypatch) -> dict:
    as_user(monkeypatch, "alice")
    project = new_project("AVIC fixture")["project_id"]
    base = f"/avic/projects/{project}/assets"
    compiled = client.post(base, json=BODY, headers=headers())
    assert compiled.status_code == 201, compiled.text
    view = client.get(f"{base}/{ASSET}").json()
    edit = {"op": "recolor", "args": {"object_id": "motif-ring-inner", "palette_key": "fog", "field": "stroke"},
            "base_svg_sha256": view["svg_sha256"]}
    edited = client.post(f"{base}/{ASSET}/edits", json=edit, headers=headers())
    conflict = client.post(f"{base}/{ASSET}/edits", json=edit, headers={"Idempotency-Key": str(uuid4())})
    assert conflict.status_code == 409
    approval = client.post(f"{base}/{ASSET}/approval", headers=headers()).json()
    release = client.post(f"{base}/{ASSET}/release", json={"approval_id": approval["approval_id"]}, headers=headers()).json()
    return {
        "capabilities": client.get("/avic/capabilities").json(),
        "asset_list": client.get(base).json(),
        "compile_response": compiled.json(),
        "asset_view": view,
        "edit_response": edited.json(),
        "conflict": conflict.json(),
        "recompile_response": client.post(f"{base}/{ASSET}/recompile", headers=headers()).json(),
        "approval_response": approval,
        "release_response": release,
        "asset_view_after": client.get(f"{base}/{ASSET}").json(),
    }


@NEEDS_BROWSER
def test_recorded_fixture_matches_live_responses(monkeypatch, export_root):  # noqa: F811
    live = capture(monkeypatch)
    text = json.dumps(live)
    assert "/tmp/" not in text and "/home/" not in text and "/root/" not in text
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(live) == set(recorded)
    assert _shape_matches(structure(live), structure(recorded)) == []
