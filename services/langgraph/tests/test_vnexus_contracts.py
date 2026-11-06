"""VNEXUS API <-> Zod parity.

Real responses from the API are recorded in packages/shared/tests/fixtures/vnexus.json
(regenerate with AMC_REGENERATE_FIXTURES=1). Every run checks that today's
responses still have the recorded structure; packages/shared/tests/vnexus.test.ts
parses the same fixture with the strict Zod schemas. Together: backend shape
== fixture shape == what the frontend accepts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from services.langgraph.agency.vnexus.genome import document_from_flat
from services.langgraph.tests._project_os_support import as_user, client, headers
from services.langgraph.tests._vnexus_support import FULL_DOC, _approve, _draft, make_world

FIXTURE = Path(__file__).resolve().parents[3] / "packages" / "shared" / "tests" / "fixtures" / "vnexus.json"


@pytest.fixture
def world(monkeypatch, tmp_path):
    return make_world(monkeypatch, tmp_path)


def structure(value: Any) -> Any:
    """Keys and nesting only: values (ids, hashes, timestamps) vary run to run."""
    if isinstance(value, dict):
        return {k: structure(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [structure(value[0])] if value else []
    return type(value).__name__ if value is not None else "null"


# Maps keyed by generated ids: compare their value shape, not their keys.
ID_KEYED_MAPS = ("$.graph.snapshot.nodes", "$.twin.graph.nodes")


def _shape_matches(live: Any, recorded: Any, path: str = "$") -> list[str]:
    problems: list[str] = []
    if path in ID_KEYED_MAPS and isinstance(live, dict) and isinstance(recorded, dict):
        kinds = {type(v).__name__ for v in live.values()} | {type(v).__name__ for v in recorded.values()}
        return [] if len(kinds) <= 1 else [f"{path}: mixed value types {sorted(kinds)}"]
    if isinstance(live, dict) and isinstance(recorded, dict):
        if set(live) != set(recorded):
            problems.append(f"{path}: keys {sorted(set(live) ^ set(recorded))} differ")
        for k in set(live) & set(recorded):
            problems += _shape_matches(live[k], recorded[k], f"{path}.{k}")
    elif isinstance(live, list) and isinstance(recorded, list) and live and recorded:
        problems += _shape_matches(live[0], recorded[0], f"{path}[0]")
    return problems


def capture(w) -> dict[str, Any]:
    brand = client.get(f"/vnexus/brands/{w['brand']}").json()["brand"]
    draft = _draft(w, "brand", w["brand"], FULL_DOC)
    readiness = client.get(f"/vnexus/versions/{draft['version_id']}/readiness").json()["readiness"]
    version = _approve(w, draft)
    resolve = client.get(f"/vnexus/brands/{w['brand']}/resolve", params={"scope": "brand", "scope_ref": w["brand"]}).json()
    branch = client.post(f"/vnexus/brands/{w['brand']}/branches", json={"base_version_id": version["version_id"], "name": "blue",
                         "changes": {"set": {"visual.color.accent": "#1d4ed8"}}}, headers=headers()).json()["branch"]
    client.post(f"/vnexus/branches/{branch['branch_id']}/feedback", json={"text": "worth a look", "decision": "revise"})
    branch_full = client.get(f"/vnexus/branches/{branch['branch_id']}").json()["branch"]
    comparison = client.get(f"/vnexus/branches/{branch['branch_id']}/compare").json()["comparison"]
    v2 = _approve(w, _draft(w, "brand", w["brand"], document_from_flat({**FULL_DOC.flatten(), "verbal.voice.register": "warm"},
                                                                         constraints=list(FULL_DOC.constraints))))
    compare = client.get("/vnexus/compare", params={"from": version["version_id"], "to": v2["version_id"]}).json()
    job = client.post(f"/vnexus/projects/{w['owner']}/media-jobs", json={"provider_id": "local.svg", "request": {
        "capability": "VECTOR_SVG", "spec": {"svg": '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 8 8">'
                                                    '<title>t</title><rect width="8" height="8" fill="#14161a"/></svg>'},
        "width": 8, "height": 8}}, headers=headers()).json()["job"]
    job_full = client.get(f"/vnexus/media-jobs/{job['job_id']}").json()["job"]
    providers = client.get("/vnexus/fabric/providers").json()["providers"]
    art = client.post(f"/vnexus/brands/{w['brand']}/production/art-direction", json={"scope": "brand", "scope_ref": w["brand"],
                      "project_id": w["owner"], "request": {"objective": "Launch", "medium": "POSTER"}}, headers=headers()).json()
    graph = client.get(f"/vnexus/brands/{w['brand']}/graph").json()
    gv = next(n for n in graph["nodes"] if n["kind"] == "GenomeVersion")
    impact = client.post(f"/vnexus/brands/{w['brand']}/graph/impact", json={"node_ids": [gv["node_id"]]}).json()
    scan = client.post(f"/vnexus/brands/{w['brand']}/immune/scan", json={"scope": "brand", "scope_ref": w["brand"]}).json()
    twin = client.get(f"/vnexus/brands/{w['brand']}/twin").json()
    prompts = client.get(f"/vnexus/brands/{w['brand']}/prompts").json()
    audit = client.get(f"/vnexus/brands/{w['brand']}/audit").json()
    return {"brand": brand, "version": version, "readiness": readiness, "resolve": resolve, "compare": compare, "audit": audit,
            "branch": branch_full, "branch_comparison": comparison, "graph": graph, "impact": impact, "providers": providers,
            "media_job": job_full, "immune_scan": scan, "twin": twin, "art_direction_claims": art["brief"]["claims"],
            "prompt_inventory": prompts["inventory"]}


def test_vnexus_responses_match_the_recorded_contract(world):
    w = world
    as_user(w["mp"], "alice", role="editor", tenant=w["tenant"])
    live = capture(w)
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(live, indent=2, sort_keys=True, default=str) + "\n")
    recorded = json.loads(FIXTURE.read_text())
    problems = _shape_matches(json.loads(json.dumps(live, default=str)), recorded)
    assert not problems, "VNEXUS API drifted from the Zod contract fixture:\n" + "\n".join(problems)
