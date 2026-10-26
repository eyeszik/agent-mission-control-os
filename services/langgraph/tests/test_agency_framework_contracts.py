"""Agency framework API <-> Zod parity.

Real responses are recorded in packages/shared/tests/fixtures/agency-framework.json
(regenerate with AMC_REGENERATE_FIXTURES=1). Each run checks that today's responses
still have the recorded structure and that every enum in
packages/shared/src/schemas/agencyFramework.ts equals its Python vocabulary;
packages/shared/tests/agencyFramework.test.ts parses the same fixture with the
Zod schemas, so backend shape == fixture shape == what the frontend accepts.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from services.langgraph.agency.operating_framework import bindings, contracts
from services.langgraph.agency.operating_framework.assurance import KINDS
from services.langgraph.agency.operating_framework.catalog import (
    DISCIPLINES,
    OUTPUT_CLASSES,
    STAGE_GATES,
)
from services.langgraph.app.main import app
from services.langgraph.tests.framework_support import (
    AUTHOR,
    afw,  # noqa: F401 - fixture
    apply,
    artifact,
    as_user,
    client,
    complete_task,
    create_project,
    decision,
    evidence,
    instantiate,
    key,
    ok,
)
from services.langgraph.tests.test_unified_delivery import (  # noqa: F401 - fixture
    ABSENT_PHRASE,
    _contract,
    provider_success,
)
from services.langgraph.tests.test_vnexus_contracts import _shape_matches, structure

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages" / "shared" / "tests" / "fixtures" / "agency-framework.json"
SCHEMA_TS = ROOT / "packages" / "shared" / "src" / "schemas" / "agencyFramework.ts"


def _ts_enum(name: str) -> list[str]:
    match = re.search(rf"export const {name} = z\.enum\(\[(.*?)\]\)", SCHEMA_TS.read_text(encoding="utf-8"), re.DOTALL)
    assert match, name
    return re.findall(r"'([^']+)'", match.group(1))


def test_enums_match_their_python_vocabularies():
    assert _ts_enum("AfTaskStateSchema") == [s.value for s in contracts.TaskState]
    assert _ts_enum("AfApplicabilitySchema") == [s.value for s in contracts.Applicability]
    assert _ts_enum("AfGateStatusSchema") == [s.value for s in contracts.GateStatus]
    assert _ts_enum("AfEvidenceOriginSchema") == [s.value for s in contracts.EvidenceOrigin]
    assert _ts_enum("AfArchetypeSchema") == [s.value for s in contracts.Archetype]
    assert _ts_enum("AfStageGateSchema") == list(STAGE_GATES)
    assert _ts_enum("AfDisciplineSchema") == list(DISCIPLINES)
    assert _ts_enum("AfOutputClassSchema") == list(OUTPUT_CLASSES)
    assert _ts_enum("AfCoverageSchema") == list(bindings.COVERAGE)
    assert _ts_enum("AfCapabilitySchema") == list(bindings.CAPABILITY)
    assert _ts_enum("AfExternalEffectSchema") == list(bindings.EXTERNAL_EFFECTS)
    assert _ts_enum("AfAssuranceKindSchema") == list(KINDS)


def capture(monkeypatch) -> dict:
    project_id = create_project()
    view = instantiate(project_id, "SAAS_SUBSCRIPTION", "Fictional SaaS onboarding engagement")
    plan_id = view["plan"]["plan_id"]
    applicability = apply(plan_id, [("AGM-01-001", "REQUIRED", "core"), ("AGM-05-001", "REQUIRED", "offer"),
                                    ("AGM-14-001", "NOT_APPLICABLE", "no paid media")])
    source = evidence(monkeypatch, project_id, "Kickoff notes (fictional). The client wants to cut trial-to-paid time "
                                               "from thirty days to fourteen days this year.")
    complete_task(monkeypatch, plan_id, "AGM-01-001", evidence=[source])
    choice = decision(plan_id, "Lead offer?", ["Annual plan discount", "Usage-based starter"], "Usage-based starter", [source])
    page = artifact(project_id, "pricing-page", "app_build_spec", "<html lang=\"en\"><p>Start free, pay as you grow "
                                                                   "with transparent monthly usage pricing.</p></html>")
    ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/meaning", headers=key(), json={
        "task_ids": ["AGM-05-001"], "interpreted_obligation": "Pricing page states usage-based pricing.",
        "qualifiers": ["usage"], "output_refs": [page]}), 201)
    review = ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/review", headers=key(),
                            json={"candidate_refs": [page]}), 201)
    ok(client.post(f"/agency-framework/plans/{plan_id}/measurements", headers=key(), json={
        "metric_input": "conversions", "value": 12, "unit": "count", "window": "2026-09",
        "source_ref": "synthetic://fixture/analytics"}), 201)
    ok(client.post(f"/agency-framework/plans/{plan_id}/measurements", headers=key(), json={
        "metric_input": "eligible_sessions", "value": 400, "unit": "count", "window": "2026-09",
        "source_ref": "synthetic://fixture/analytics"}), 201)
    tasks = ok(client.get(f"/agency-framework/plans/{plan_id}/tasks", params={"module_id": "AGM-01"}))
    # A review bound to a sealed delivery release candidate (a real enforce-mode run in this project).
    monkeypatch.setenv("AMC_CONTRACT_MODE", "enforce")
    run = ok(client.post("/agency/runs", headers=key(), json={
        "project_id": project_id, "brief": {"brand_name": "Northwind", "target_audience": "Urban professionals"},
        "delivery_contract": _contract(ABSENT_PHRASE)}), 201)
    as_user(monkeypatch, "afw-inspector", "reviewer")
    candidate_review = ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/review", headers=key(), json={
        "task_ids": ["AGM-20-001"], "release_candidate_ref": f"release-candidate:{run['run_id']}"}), 201)
    as_user(monkeypatch, AUTHOR)
    return {
        "catalog": ok(client.get("/agency-framework/catalog")),
        "catalog_tasks": {"tasks": ok(client.get("/agency-framework/catalog/tasks"))["tasks"][:3]},
        "metric_definitions": ok(client.get("/agency-framework/metrics/definitions")),
        "plan_view": ok(client.get(f"/agency-framework/plans/{plan_id}")),
        "plan_list": ok(client.get("/agency-framework/plans", params={"project_id": project_id})),
        "task_list": {"items": tasks["items"][:3]},
        "task_detail": ok(client.get(f"/agency-framework/plans/{plan_id}/tasks/AGM-01-001")),
        "applicability": applicability,
        "gates": ok(client.get(f"/agency-framework/plans/{plan_id}/gates")),
        "audit": {"events": ok(client.get(f"/agency-framework/plans/{plan_id}/audit"))["events"][:5]},
        "metrics": ok(client.get(f"/agency-framework/plans/{plan_id}/metrics")),
        "assurance_list": ok(client.get(f"/agency-framework/plans/{plan_id}/assurance")),
        "assurance_record": ok(client.get(f"/agency-framework/plans/{plan_id}/assurance/{review['record']['record_id']}")),
        "release_candidate_review": ok(client.get(
            f"/agency-framework/plans/{plan_id}/assurance/{candidate_review['record']['record_id']}")),
        "decision_ref": choice,
    }


def _scrub(value):
    """Fixture values must not carry local paths."""
    text = json.dumps(value)
    assert "/tmp/" not in text and "/home/" not in text and "/root/" not in text
    return value


def test_recorded_fixture_matches_live_responses(afw, monkeypatch, provider_success):
    live = _scrub(capture(monkeypatch))
    if os.environ.get("AMC_REGENERATE_FIXTURES") == "1" or not FIXTURE.exists():
        FIXTURE.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(live) == set(recorded)
    problems = _shape_matches(structure(live), structure(recorded))
    assert problems == [], problems
    assert live["metrics"]["measured"] >= 2  # conversion rate (synthetic) and approval rework rate (internal)
    rate = next(m for m in live["metrics"]["metrics"] if m["metric_id"] == "acquisition.conversion_rate")
    assert rate["value"] == 0.03 and rate["origin"] == "SYNTHETIC"


def test_every_framework_route_requires_authentication_wiring():
    paths = [p for p in app.openapi()["paths"] if p.startswith("/agency-framework")]
    assert len(paths) == 24
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/agency-framework"):
            continue
        for method, op in ops.items():
            if method in ("post", "put"):
                params = {p["name"] for p in op.get("parameters", [])}
                assert "Idempotency-Key" in params, (method, path)
