"""Three fictional engagement archetypes through the real API (spec section 11).

B2C physical goods (fulfilment, returns, rights, margins), B2B professional
services (multi-stakeholder sale, lead quality, sales cycle) and SaaS
subscriptions (activation, churn, recurring margin). Each proves task import
count, dependencies, inapplicability handling, task work with separation of
duties, a gate approval, KPI definitions computed only from recorded inputs,
persistence, audit and the release boundary. All data is synthetic; no result
here is a client result.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from services.langgraph.agency.operating_framework.catalog import load_catalog
from services.langgraph.tests.framework_support import (
    afw,  # noqa: F401 - fixture
    apply,
    artifact,
    client,
    complete_task,
    create_project,
    decide,
    decision,
    evidence,
    instantiate,
    key,
    ok,
    task,
)

ROOT = Path(__file__).resolve().parents[3]

ARCHETYPES = {
    "B2C_PHYSICAL_PRODUCT": {
        "name": "Lumen Tea Co (fictional)",
        "scope": "DTC loose-leaf tea: fulfilment, returns, packaging rights, margins",
        "not_applicable_modules": {"AGM-16": "no partnership programme in phase one",
                                   "AGM-17": "PR deferred until launch"},
        "conditional_modules": {"AGM-14": "paid media only if contribution margin supports it"},
        "discovery": [("AGM-01-001", "Discovery interview (fictional). The founder ships loose-leaf tea from one warehouse "
                                     "and sees most returns caused by damaged packaging in transit."),
                      ("AGM-01-004", "Margin review (fictional). Gross margin on the starter bundle is lower than on single "
                                     "tins because of the extra packaging and fulfilment cost.")],
        "decision": ("Hero offer?", ["Starter bundle", "Single tin", "Subscription box"], "Single tin"),
        "measurements": {"revenue": 42000, "variable_costs": 25200},
        "measured": {"profitability.contribution_margin": 0.4},
        "not_measured": ["sales.cac", "retention.churn_rate_monthly"],
    },
    "B2B_PROFESSIONAL_SERVICES": {
        "name": "Northwind Advisory (fictional)",
        "scope": "Mid-market finance advisory: multi-stakeholder sale, lead quality, long sales cycle",
        "not_applicable_modules": {"AGM-13": "no organic social programme", "AGM-14": "no paid media budget"},
        "conditional_modules": {"AGM-16": "referral partners if a partner agreement is signed"},
        "discovery": [("AGM-01-001", "Kickoff (fictional). The managing partner says most new engagements come from "
                                     "referrals and typically take four to six months from first call to signature."),
                      ("AGM-01-009", "Stakeholder map (fictional). A typical deal needs sign-off from the finance "
                                     "director, the chief executive and a procurement lead before contract.")],
        "decision": ("Primary acquisition motion?", ["Referral programme", "Content-led inbound", "Outbound"],
                     "Content-led inbound"),
        "measurements": {"qualified_leads": 18},
        "measured": {"acquisition.qualified_leads": 18.0},
        "not_measured": ["acquisition.cost_per_lead", "sales.payback_months"],
    },
    "SAAS_SUBSCRIPTION": {
        "name": "Ledgerly (fictional)",
        "scope": "SMB bookkeeping SaaS: activation, churn, recurring margin",
        "not_applicable_modules": {"AGM-17": "no PR programme"},
        "conditional_modules": {"AGM-14": "paid search only after activation improves"},
        "discovery": [("AGM-01-001", "Kickoff (fictional). The product team believes most trial users never connect "
                                     "a bank account, which is the step that predicts conversion to paid."),
                      ("AGM-01-005", "Analytics review (fictional). The current dashboard tracks signups but has no "
                                     "cohort view of activation or of monthly logo churn.")],
        "decision": ("Activation focus?", ["Bank connection in onboarding", "Invoice template first", "Guided tour"],
                     "Bank connection in onboarding"),
        "measurements": {"churned_customers": 30, "customers_at_start": 1000, "arpa_monthly": 49.0,
                         "gross_margin_ratio": 0.8, "churn_rate_monthly": 0.03},
        "measured": {"retention.churn_rate_monthly": 0.03, "profitability.ltv": 1306.666667},
        "not_measured": ["sales.cac", "brand.awareness_rate"],
    },
}


def _counts():
    from services.langgraph.persistence.database import table, transaction

    with transaction() as db:
        out = {}
        for name in ("action_sandbox_effects", "outbox"):
            try:
                out[name] = db.execute(f"SELECT COUNT(*) AS n FROM {table(name)}").fetchone()["n"]
            except Exception:  # noqa: BLE001 - absent table counts as zero
                out[name] = 0
    return out


@pytest.mark.parametrize("archetype", list(ARCHETYPES))
def test_archetype_engagement_end_to_end(afw, monkeypatch, archetype):
    spec = ARCHETYPES[archetype]
    effects_before = _counts()
    project_id = create_project(name=spec["name"])
    view = instantiate(project_id, archetype, spec["scope"])
    plan_id = view["plan"]["plan_id"]
    assert view["created"] and view["progress"]["overall"]["defined"] == 295
    assert instantiate(project_id, archetype, spec["scope"])["created"] is False  # import is idempotent

    catalog = load_catalog()
    discovery_ids = {t for t, _ in spec["discovery"]}
    decisions = []
    for t in catalog.tasks:
        if t.module_id in spec["not_applicable_modules"]:
            decisions.append((t.task_id, "NOT_APPLICABLE", spec["not_applicable_modules"][t.module_id]))
        elif t.module_id in spec["conditional_modules"]:
            decisions.append((t.task_id, "CONDITIONAL", spec["conditional_modules"][t.module_id]))
        elif t.stage_gate == "01_DISCOVERY":
            decisions.append((t.task_id, "REQUIRED" if t.task_id in discovery_ids else "NOT_APPLICABLE",
                              "discovery scoped to the fictional brief"))
        elif t.task_id == "AGM-05-001":
            decisions.append((t.task_id, "REQUIRED", "offer decision"))
    result = apply(plan_id, decisions)
    assert not result["skipped"]
    view = ok(client.get(f"/agency-framework/plans/{plan_id}"))
    na_modules = len(spec["not_applicable_modules"])
    for mid in spec["not_applicable_modules"]:
        assert view["progress"]["modules"][mid]["not_applicable"] == view["progress"]["modules"][mid]["defined"]
        assert view["progress"]["modules"][mid]["required_verified_ratio"] == "NOT_MEASURED"
    assert na_modules >= 1
    assert view["gates"][0]["status"] == "BLOCKED"  # required discovery work is not verified yet

    # Dependencies are information for the reviewer, not blind serialization.
    detail = task(plan_id, "AGM-05-001")
    assert set(detail["upstream_modules"]) == {"AGM-02", "AGM-03", "AGM-04"}
    assert "AGM-06" in detail["downstream_modules"]

    # Discovery: reviewed (synthetic) evidence, a second person verifies, a third approves.
    for task_id, text in spec["discovery"]:
        source = evidence(monkeypatch, project_id, text, domain="customer")
        assert complete_task(monkeypatch, plan_id, task_id, evidence=[source])["state"] == "APPROVED"
    gate = ok(client.get(f"/agency-framework/plans/{plan_id}/gates"))["gates"][0]
    assert gate["status"] == "NEEDS_HUMAN" and gate["synthetic_only"] is True
    requested = ok(client.post(f"/agency-framework/plans/{plan_id}/gates/01_DISCOVERY/request-approval", headers=key()))
    ok(decide(monkeypatch, requested["approval"]["approval_id"]))

    # Strategy: an offer decision with alternatives and a plan artifact.
    question, alternatives, selected = spec["decision"]
    choice = decision(plan_id, question, alternatives, selected)
    assert complete_task(monkeypatch, plan_id, "AGM-05-001", decisions=[choice])["state"] == "APPROVED"

    # KPIs: computed only from recorded inputs; synthetic inputs are labelled; the rest NOT_MEASURED.
    for name, value in spec["measurements"].items():
        ok(client.post(f"/agency-framework/plans/{plan_id}/measurements", headers=key(), json={
            "metric_input": name, "value": value, "unit": "count", "window": "2026-09",
            "source_ref": f"synthetic://fixture/{archetype.lower()}/{name}"}), 201)
    metrics = {m["metric_id"]: m for m in ok(client.get(f"/agency-framework/plans/{plan_id}/metrics"))["metrics"]}
    for metric_id, expected in spec["measured"].items():
        assert metrics[metric_id]["value"] == pytest.approx(expected, rel=1e-4), metric_id
        assert metrics[metric_id]["origin"] == "SYNTHETIC"
    for metric_id in spec["not_measured"]:
        assert metrics[metric_id]["value"] == "NOT_MEASURED", metric_id

    # Activation channels stay planning-only: a channel plan can be approved, nothing is dispatched.
    if "AGM-14" in spec["conditional_modules"]:
        media = artifact(project_id, "media-plan", "media_plan", "Media plan (fictional): test paid search at a capped "
                                                                 "budget only after the margin gate is met.")
        assert complete_task(monkeypatch, plan_id, "AGM-14-001", artifacts=[media])["state"] == "APPROVED"
        assert task(plan_id, "AGM-14-001")["binding"]["external_effect"] == "spend"
        assert task(plan_id, "AGM-14-001")["binding"]["capability"] == "PLANNING_ONLY"

    final = ok(client.get(f"/agency-framework/plans/{plan_id}"))
    assert final["gates"][0]["status"] == "PASSED"
    assert final["readiness"]["release_eligible"] is False and final["readiness"]["externally_executed"] is False
    assert final["readiness"]["synthetic_evidence_present"] is True
    assert _counts() == effects_before  # no sandbox effect, no outbox delivery

    events = ok(client.get(f"/agency-framework/plans/{plan_id}/audit", params={"limit": 1000}))["events"]
    kinds = {e["payload"].get("kind") for e in events}
    assert {"agency_framework.plan_instantiated", "agency_framework.applicability", "agency_framework.verified",
            "agency_framework.approved"} <= kinds
    assert all(e["actor"] for e in events)

    # Persistence: a fresh process reads the same plan state from the database.
    script = (
        "import json, sys\n"
        "from services.langgraph.agency.operating_framework.service import plan_view\n"
        "from services.langgraph.security.auth import Principal\n"
        "p = Principal(user_id='fresh', tenant_id='tenant-events-test', role='viewer', allowed_project_ids=frozenset({sys.argv[2]}))\n"
        "v = plan_view(p, sys.argv[1])\n"
        "print(json.dumps({'approved': v['progress']['overall']['approved'], 'gates': [g['status'] for g in v['gates']]}))\n"
    )
    out = subprocess.run([sys.executable, "-c", script, plan_id, project_id], capture_output=True, text=True, check=False, cwd=ROOT,
                         env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    fresh = json.loads(out.stdout.strip().splitlines()[-1])
    assert fresh == {"approved": final["progress"]["overall"]["approved"], "gates": [g["status"] for g in final["gates"]]}
