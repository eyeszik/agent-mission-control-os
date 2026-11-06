"""UCPO Python/TypeScript parity: enums equal, and a fixture recorded from the real backend parses with the Zod twins.

Regenerate with AMC_REGENERATE_FIXTURES=1. packages/shared/tests/ucpo.test.ts parses the same
fixture, so backend shape == fixture shape == what the frontend accepts.
"""

from __future__ import annotations

import json
import os
import re
import typing
from pathlib import Path

from services.langgraph.agency.ucpo import contracts
from services.langgraph.agency.ucpo.release import seal_proof
from services.langgraph.agency.ucpo.semantic import evaluate
from services.langgraph.tests._project_os_support import as_user, client, export_root, headers, new_project  # noqa: F401
from services.langgraph.tests.test_ucpo_pipeline import line, rendered_from_source
from services.langgraph.tests.test_vnexus_contracts import _shape_matches, structure

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages" / "shared" / "tests" / "fixtures" / "ucpo.json"
SCHEMA_TS = ROOT / "packages" / "shared" / "src" / "schemas" / "ucpo.ts"
SAMPLE = json.loads((ROOT / "sample_ucpo_website.json").read_text())


def _ts_enum(name: str) -> list[str]:
    match = re.search(rf"export const {name} = z\.enum\(\[(.*?)\]\)", SCHEMA_TS.read_text(encoding="utf-8"), re.DOTALL)
    assert match, name
    return re.findall(r"'([^']+)'", match.group(1))


def test_enums_match_the_python_contracts():
    assert _ts_enum("UcpoSectionKindSchema") == list(typing.get_args(contracts.SectionKind))
    assert _ts_enum("UcpoRequirementKindSchema") == list(typing.get_args(contracts.RequirementKind))
    assert _ts_enum("UcpoStageSchema") == list(typing.get_args(contracts.Stage))
    assert _ts_enum("UcpoRequirementStatusSchema") == list(typing.get_args(contracts.RequirementStatus))
    assert _ts_enum("UcpoCheckResultValueSchema") == list(typing.get_args(contracts.CheckResult.model_fields["result"].annotation))
    assert _ts_enum("UcpoBuildStatusSchema") == list(typing.get_args(contracts.BuildResult.model_fields["status"].annotation))


def capture(monkeypatch) -> dict:
    as_user(monkeypatch, "alice")
    project = new_project("UCPO fixture")["project_id"]
    compiled = client.post(f"/ucpo/projects/{project}/sites", json={"site_id": "halden", "brief": SAMPLE}, headers=headers())
    assert compiled.status_code == 201, compiled.text
    view = client.get(f"/ucpo/projects/{project}/sites/halden").json()
    b, pkg, genome, arch, ir, files, manifest = line()
    verification = rendered_from_source(pkg, ir, files)
    report, _ = evaluate(pkg, arch=arch, ir=ir, files=files, manifest=manifest, verification=verification)
    build = contracts.BuildResult(status="PASSED", source_tree_hash=manifest.tree_hash, isolation={"available": True},
                                  steps=({"name": "next_build", "command": "next build --webpack", "exit_status": 0,
                                          "duration_s": 7.4, "log_tail": ""},), dependency_manifest=manifest.dependencies,
                                  output_hash="b" * 64, output_files=45, output_bytes=1)
    proof = seal_proof(project_ref="prj-fixture", site_id="halden", revisions={"source": manifest.tree_hash},
                       artifact_refs={"source": "artifact:prj-fixture:foundry-ucpo-halden-source@v1"}, build=build,
                       qa=verification, coverage=report)
    return {
        "brief": b.model_dump(mode="json"),
        "requirements": pkg.model_dump(mode="json"),
        "coverage": report.model_dump(mode="json"),
        "browser_verification": verification.model_dump(mode="json"),
        "release_proof": proof.model_dump(mode="json"),
        "compile_response": compiled.json(),
        "site_view": view,
        "site_list": client.get(f"/ucpo/projects/{project}/sites").json(),
        "trace": client.get(f"/ucpo/projects/{project}/sites/halden/trace/req.index.s1.cta").json(),
    }


def test_recorded_fixture_matches_live_responses(monkeypatch, export_root):  # noqa: F811
    live = capture(monkeypatch)
    text = json.dumps(live)
    assert "/tmp/" not in text and "/home/" not in text and "/root/" not in text
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(live) == set(recorded)
    assert _shape_matches(structure(live), structure(recorded)) == []
