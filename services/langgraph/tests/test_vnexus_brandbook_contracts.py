"""Brand book Python/TypeScript parity: a fixture recorded from the real /vnexus brand book routes parses with the Zod twins.

Regenerate with AMC_REGENERATE_FIXTURES=1 (needs local Chromium: the build is a real render).
packages/shared/tests/vnexusBrandbook.test.ts parses the same fixture.
"""

from __future__ import annotations

import json
import os
import re
import typing
from pathlib import Path
from uuid import uuid4

import pytest

from services.langgraph.agency.vnexus.brandbook import service as bookservice
from services.langgraph.agency.vnexus.brandbook.assets import AssetKind
from services.langgraph.agency.vnexus.brandbook.fields import EvidenceClass, FieldStatus
from services.langgraph.agency.vnexus.brandbook.manifest import Mode, PageSpec
from services.langgraph.agency.vnexus.genome import document_from_flat
from services.langgraph.agency.visual.browser import probe_browser
from services.langgraph.tests._project_os_support import client, headers
from services.langgraph.tests._vnexus_support import FULL_DOC, _approve, _draft, make_world
from services.langgraph.tests.test_vnexus_brandbook import DECIDED
from services.langgraph.tests.test_vnexus_contracts import _shape_matches, structure

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages" / "shared" / "tests" / "fixtures" / "vnexus-brandbook.json"
SCHEMA_TS = ROOT / "packages" / "shared" / "src" / "schemas" / "vnexusBrandbook.ts"


def _ts_enum(name: str) -> list[str]:
    match = re.search(rf"export const {name} = z\.enum\(\[(.*?)\]\)", SCHEMA_TS.read_text(encoding="utf-8"), re.DOTALL)
    assert match, name
    return re.findall(r"'([^']+)'", match.group(1))


def test_enums_match_the_python_contracts():
    assert _ts_enum("BrandBookModeSchema") == [m.value for m in Mode]
    assert _ts_enum("BrandBookFieldStatusSchema") == [s.value for s in FieldStatus]
    assert _ts_enum("BrandBookEvidenceClassSchema") == [e.value for e in EvidenceClass]
    assert _ts_enum("BrandBookAssetKindSchema") == [k.value for k in AssetKind]
    assert _ts_enum("BrandBookGapBehaviorSchema") == list(typing.get_args(PageSpec.model_fields["gap_behavior"].annotation))


def capture(monkeypatch, tmp_path) -> dict:
    bookservice.clear_cache()
    w = make_world(monkeypatch, tmp_path)
    doc = document_from_flat({**FULL_DOC.flatten(), **DECIDED}, constraints=list(FULL_DOC.constraints))
    _approve(w, _draft(w, "brand", w["brand"], doc))
    target = {"scope": "brand", "scope_ref": w["brand"], "project_id": w["owner"]}
    put = client.put(f"/vnexus/brands/{w['brand']}/brandbook/intake", json={"intake": {"evidence": [
        {"source_id": "studio-visit", "locator": "studio visit notes (fictional)", "evidence_class": "USER_REPORTED",
         "observations": ["matte glazes"], "privacy": "contains_pii_redacted"}], "proposals": {}}}, headers=headers())
    assert put.status_code == 200, put.text
    build = client.post(f"/vnexus/brands/{w['brand']}/brandbook/builds", json={**target, "mode": "PREVIEW"},
                        headers={"Idempotency-Key": str(uuid4())})
    assert build.status_code == 201, build.text
    compiled = client.post(f"/vnexus/brands/{w['brand']}/brandbook/compile", json={**target, "mode": "PROMPTS_ONLY"}, headers=headers())
    return {
        "template": client.get("/vnexus/brandbook/template").json(),
        "intake": client.get(f"/vnexus/brands/{w['brand']}/brandbook/intake").json(),
        "intake_saved": put.json(),
        "gaps": client.get(f"/vnexus/brands/{w['brand']}/brandbook/gaps", params=target).json(),
        "compile": compiled.json(),
        "build": build.json(),
        "current": client.get(f"/vnexus/brands/{w['brand']}/brandbook/builds/current", params={**target, "mode": "PREVIEW"}).json(),
    }


@pytest.mark.skipif(not probe_browser().get("available", False), reason="NOT_RUN: local Chromium unavailable")
def test_recorded_fixture_matches_live_responses(monkeypatch, tmp_path):
    live = capture(monkeypatch, tmp_path)
    text = json.dumps(live)
    assert "/tmp/" not in text and "/home/" not in text and "/root/" not in text
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.write_text(json.dumps(live, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(live) == set(recorded)
    # Telemetry timings vary per run and per stage; compare everything else structurally.
    for doc in (live, recorded):
        doc["build"].pop("telemetry", None)
    assert _shape_matches(structure(live), structure(recorded)) == []
