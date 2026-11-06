"""The connected slice (spec 15.4): one fictional B2C engagement through the native subsystems.

Discovery evidence -> positioning decision -> VNEXUS approved genome -> identity
assets (VNEXUS/Foundry production on local Chromium, else a deterministic SVG
mark and the identity step reported NOT_RUN) -> website artifact -> the five
assurance records -> a review candidate that stays unapproved. Everything is
fictional and labelled synthetic; nothing is published, sent or spent.
"""

from __future__ import annotations

import pytest

from services.langgraph.agency.assets import render_logo_svg
from services.langgraph.agency.operating_framework.catalog import load_catalog
from services.langgraph.agency.visual.browser import probe_browser
from services.langgraph.tests._vnexus_support import (
    FULL_DOC,
    _approve,
    _draft,
    make_world,
)
from services.langgraph.tests.framework_support import (
    apply,
    artifact,
    client,
    complete_task,
    decide,
    decision,
    evidence,
    instantiate,
    key,
    ok,
    task,
    use_tenant,
)

BROWSER = probe_browser().get("available", False)


def _scope(plan_id: str, required: set[str], gates: set[str]) -> None:
    catalog = load_catalog()
    apply(plan_id, [(t.task_id, "REQUIRED" if t.task_id in required else "NOT_APPLICABLE", "scoped for the connected slice")
                    for t in catalog.tasks if t.stage_gate in gates])


def _approve_gate(monkeypatch, plan_id: str, gate: str) -> None:
    requested = ok(client.post(f"/agency-framework/plans/{plan_id}/gates/{gate}/request-approval", headers=key()))
    ok(decide(monkeypatch, requested["approval"]["approval_id"]))


@pytest.fixture
def world(monkeypatch, tmp_path):
    w = make_world(monkeypatch, tmp_path)
    use_tenant(monkeypatch, w["tenant"])
    return w


def test_connected_slice_from_discovery_to_an_unapproved_review_candidate(world, monkeypatch):
    project_id = world["owner"]
    plan = instantiate(project_id, "B2C_PHYSICAL_PRODUCT", "Fictional stoneware brand: positioning, identity, site")
    plan_id = plan["plan"]["plan_id"]
    required = {"AGM-01-001", "AGM-06-001", "AGM-08-001", "AGM-10-001"}
    _scope(plan_id, required, {"01_DISCOVERY", "02_STRATEGY", "03_PRODUCTION"})

    # 01 Discovery: reviewed (synthetic) evidence, verified by a second person, approved by a third.
    brief = evidence(monkeypatch, project_id, "Discovery interview (fictional). The founder sells small-batch stoneware "
                                              "to people furnishing a first home and wants a calmer, slower brand.")
    complete_task(monkeypatch, plan_id, "AGM-01-001", evidence=[brief])
    _approve_gate(monkeypatch, plan_id, "01_DISCOVERY")

    # 02 Strategy: a positioning decision with alternatives, and the VNEXUS genome approved by its own review.
    positioning = decision(plan_id, "Positioning territory?", ["Made slowly, used daily", "Designer luxury", "Lowest price"],
                           "Made slowly, used daily", [brief])
    genome = _approve(world, _draft(world, "brand", world["brand"], FULL_DOC))
    use_tenant(monkeypatch, world["tenant"])
    assert genome["status"] == "APPROVED"
    complete_task(monkeypatch, plan_id, "AGM-06-001", decisions=[positioning, f"genome:{genome['version_id']}"])
    _approve_gate(monkeypatch, plan_id, "02_STRATEGY")

    # 03 Production: identity from the approved genome, then the website.
    identity_route = "NOT_RUN: local Chromium unavailable"
    if BROWSER:
        world["mp"] = monkeypatch
        produced = client.post(f"/vnexus/brands/{world['brand']}/production/identity", headers=key(), json={
            "scope": "brand", "scope_ref": world["brand"], "project_id": project_id, "deliverables": ["logo_mark"],
            "copy_text": {"headline": "Made slowly, used daily"}})
        assert produced.status_code == 200, produced.text
        outputs = [o for o in produced.json()["outputs"] if o["state"] == "QC_PASSED" and o["artifact_id"]]
        assert outputs, produced.json()
        heads = {a["artifact_id"]: a for a in ok(client.get(f"/projects/{project_id}/artifacts"))["artifacts"]}
        identity_refs = [f"artifact:{o['artifact_id']}@v{heads[o['artifact_id']]['version']}" for o in outputs]
        identity_route = "VNEXUS identity production (local render, QC_PASSED)"
    else:
        doc = FULL_DOC.flatten()
        identity_refs = [artifact(project_id, "identity-mark", "design_system_spec", render_logo_svg(
            brand_name="Halden Fen", primary=doc["visual.color.ink"], secondary=doc["visual.color.accent"],
            surface=doc["visual.color.paper"], tagline="made slowly, used daily"))]
    complete_task(monkeypatch, plan_id, "AGM-08-001", artifacts=identity_refs)
    positioning_doc = artifact(project_id, "positioning-statement", "positioning_statement",
                               "Positioning (fictional): Made slowly, used daily. Small-batch stoneware for a first home.")
    site = artifact(project_id, "landing-page", "app_build_spec",
                    "<html lang=\"en\"><h1>Halden &amp; Fen (fictional)</h1><p>Every piece is thrown by hand in small "
                    "batches and made slowly, used daily.</p><img src=\"bowl.png\" alt=\"A matte stoneware bowl\"></html>",
                    depends_on=[positioning_doc.removeprefix("artifact:").rsplit("@v", 1)[0]])
    complete_task(monkeypatch, plan_id, "AGM-10-001", artifacts=[site])

    # The five assurance records, each linked to catalog task ids and real refs.
    meaning = ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/meaning", headers=key(), json={
        "task_ids": ["AGM-10-001"], "interpreted_obligation": "The page carries the approved promise and no price claim.",
        "qualifiers": ["made slowly, used daily", "small batches"], "exclusions": ["cheapest"], "output_refs": [site],
        "evidence_refs": [brief]}), 201)
    mutation = ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/mutation", headers=key(), json={
        "task_ids": ["AGM-10-001"], "base_ref": site, "mutation_class": "CLAIM_CHANGE",
        "find": "thrown by hand in small batches", "replace": "mass produced overseas",
        "expected_findings": ["CLAIM_CHANGED"], "test_fixture_ref": "fixture:slice:changed-positioning-claim"}), 201)
    missing = ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/mutation", headers=key(), json={
        "task_ids": ["AGM-01-001"], "base_ref": site, "mutation_class": "MISSING_EVIDENCE",
        "expected_findings": ["REFS_REQUIRED"], "test_fixture_ref": "fixture:slice:missing-evidence"}), 201)
    probe = ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/probe", headers=key(), json={
        "task_ids": ["AGM-06-001"], "changed_artifact_id": positioning_doc.removeprefix("artifact:").rsplit("@v", 1)[0],
        "change_description": "sandbox-only revision of the positioning statement",
        "declared_effects": [site.removeprefix("artifact:").rsplit("@v", 1)[0]]}), 201)
    contrary = evidence(monkeypatch, project_id, "New panel (fictional). Most first-home buyers in the panel said price "
                                                 "mattered more to them than how slowly a piece was made.")
    renewal = ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/renewal", headers=key(), json={
        "task_ids": ["AGM-06-001"], "trigger_kind": "NEW_CONTRADICTION", "trigger_evidence_refs": [contrary],
        "affected_decision_ref": positioning, "proposed_alternatives": ["Lowest price"],
        "rationale": "A newer (fictional) panel contradicts the slow-craft premise."}), 201)
    review = ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/review", headers=key(), json={
        "task_ids": ["AGM-08-001", "AGM-10-001"], "candidate_refs": [*identity_refs, site],
        "summary": "Identity and landing page for the fictional brand.", "request_decision": True}), 201)

    assert meaning["record"]["status"] == "COVERED"
    assert mutation["record"]["status"] == "DETECTED" and missing["record"]["status"] == "DETECTED"
    assert probe["record"]["status"] == "MATCHED" and probe["record"]["body"]["isolation"]["canonical_unchanged"]
    assert renewal["record"]["body"]["decision_unchanged"] and renewal["record"]["body"]["retained_alternatives"] == [
        "Made slowly, used daily", "Designer luxury", "Lowest price"]
    assert review["record"]["status"] == "NEEDS_HUMAN"
    assert review["record"]["body"]["access_check_receipt"]["full_candidate_access"] is True

    # The candidate stays unapproved until the existing approval route decides it.
    pending = next(a for a in client.get("/approvals").json() if a["approval_id"] == review["record"]["body"]["decision_ref"])
    assert pending["status"] == "pending"
    view = ok(client.get(f"/agency-framework/plans/{plan_id}"))
    assert [g["status"] for g in view["gates"][:2]] == ["PASSED", "PASSED"]
    assert view["gates"][2]["status"] == "NEEDS_HUMAN"  # production is verified and approved task by task, gate still human
    assert view["progress"]["overall"]["approved"] == 4
    assert view["readiness"]["release_eligible"] is False and view["readiness"]["externally_executed"] is False
    assert task(plan_id, "AGM-06-001")["ref_checks"][1]["status"] == "OK"  # the genome ref resolves as approved
    # A newer genome version supersedes the one the positioning task cites: its proof no longer holds.
    as_genome_owner = _approve(world, _draft(world, "brand", world["brand"], FULL_DOC.model_copy(update={})))
    use_tenant(monkeypatch, world["tenant"])
    refs = {c["ref"]: c["status"] for c in task(plan_id, "AGM-06-001")["ref_checks"]}
    assert as_genome_owner["version_id"] != genome["version_id"]
    assert refs[f"genome:{genome['version_id']}"] == "GENOME_SUPERSEDED"
    out = ok(client.post(f"/agency-framework/plans/{plan_id}/revalidate", headers=key()))
    assert "AGM-06-001" in [i["task_id"] for i in out["invalidated"]]
    assert ok(client.get(f"/agency-framework/plans/{plan_id}"))["gates"][1]["status"] == "BLOCKED"
    print({"identity_route": identity_route, "plan_id": plan_id})


def test_unapproved_or_foreign_genomes_are_not_decisions(world, monkeypatch):
    project_id = world["owner"]
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    draft = _draft(world, "brand", world["brand"], FULL_DOC)
    use_tenant(monkeypatch, world["tenant"])
    apply(plan_id, [("AGM-06-001", "REQUIRED", "positioning")])
    from services.langgraph.tests.framework_support import move, set_refs, verify

    ok(move(plan_id, "AGM-06-001", "READY"))
    ok(move(plan_id, "AGM-06-001", "ACTIVE"))
    ok(set_refs(plan_id, "AGM-06-001", decisions=[f"genome:{draft['version_id']}"]))
    ok(move(plan_id, "AGM-06-001", "IN_REVIEW"))
    response = verify(monkeypatch, plan_id, "AGM-06-001")
    assert response.status_code == 422
    assert task(plan_id, "AGM-06-001")["instance"]["verification"]["checks"][0]["status"] == "GENOME_NOT_APPROVED"
    # A genome in another project of the same tenant does not resolve here.
    other_plan = instantiate(world["other"])["plan"]["plan_id"]
    apply(other_plan, [("AGM-06-001", "REQUIRED", "positioning")])
    ok(move(other_plan, "AGM-06-001", "READY"))
    ok(move(other_plan, "AGM-06-001", "ACTIVE"))
    response = set_refs(other_plan, "AGM-06-001", decisions=[f"genome:{draft['version_id']}"])
    assert response.status_code == 422 and response.json()["error"]["details"]["checks"][0]["status"] == "REF_NOT_FOUND"
