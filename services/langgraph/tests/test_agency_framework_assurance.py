"""Meaning, Mutation, Probe, Renewal and Review records: persistence, integrity and non-authority."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from services.langgraph.agency.operating_framework.assurance import (
    confusion_matrix,
    graph_snapshot,
)
from services.langgraph.tests.framework_support import (
    AUTHOR,
    afw,  # noqa: F401 - fixture
    apply,
    artifact,
    as_user,
    client,
    complete_task,
    create_project,
    decide,
    decision,
    evidence,
    instantiate,
    key,
    ok,
    revise,
)

ROOT = Path(__file__).resolve().parents[3]
SITE = ("<html lang=\"en\"><body><h1>Lumen Tea (fictional)</h1><p>Every blend is certified organic and ships "
        "from our own warehouse in Lyon. Ships in 2 days. Packed by hand.</p><img src=\"cup.png\" alt=\"A cup of green tea\"></body></html>")


def record(plan_id: str, kind: str, body: dict, status: int = 201) -> dict:
    return ok(client.post(f"/agency-framework/plans/{plan_id}/assurance/{kind}", json=body, headers=key()), status)


def setup_project(monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id, "B2C_PHYSICAL_PRODUCT")["plan"]["plan_id"]
    genome = artifact(project_id, "brand-genome", "brand_core", "Voice: warm, exact. Promise: honest sourcing.")
    site_id = artifact(project_id, "landing-page", "app_build_spec", SITE, depends_on=[genome.removeprefix("artifact:").rsplit("@v", 1)[0]])
    source = evidence(monkeypatch, project_id, "Supplier certificate (fictional). Every blend in the range carries an "
                                               "EU organic certificate issued in 2026.")
    return project_id, plan_id, genome, site_id, source


def test_meaning_detects_omitted_qualifiers_and_present_exclusions_and_ignores_the_semantic_score(afw, monkeypatch):
    _, plan_id, _, site, source = setup_project(monkeypatch)
    covered = record(plan_id, "meaning", {
        "task_ids": ["AGM-10-001"], "interpreted_obligation": "The landing page states certification and origin.",
        "qualifiers": ["certified organic", "Lyon"], "exclusions": ["free shipping"], "output_refs": [site],
        "evidence_refs": [source]})
    assert covered["record"]["status"] == "COVERED"
    partial = record(plan_id, "meaning", {
        "task_ids": ["AGM-10-001"], "interpreted_obligation": "The page also names the tasting notes.",
        "qualifiers": ["tasting notes"], "output_refs": [site], "advisory_semantic_score": 1.0})
    body = partial["record"]["body"]
    assert partial["record"]["status"] == "PARTIAL" and body["qualifiers"] == [{"qualifier": "tasting notes", "found": False}]
    assert body["advisory"]["semantic_score"] == 1.0 and body["review_status"] == "NEEDS_HUMAN"
    contradicted = record(plan_id, "meaning", {
        "task_ids": ["AGM-10-001"], "interpreted_obligation": "No delivery-time promises on the page.",
        "exclusions": ["ships in 2 days"], "output_refs": [site]})
    assert contradicted["record"]["status"] == "CONTRADICTED"
    unknown = record(plan_id, "meaning", {"task_ids": ["AGM-10-001"], "interpreted_obligation": "Pricing page exists."})
    assert unknown["record"]["status"] == "UNKNOWN"
    assert unknown["record"]["body"]["output_locations"] == [{"ref": None, "status": "NOT_AVAILABLE"}]
    # A score never opens or decides an approval.
    assert not [a for a in client.get("/approvals").json() if a.get("project_id") == partial["record"]["project_id"]]


def test_mutation_fixtures_report_detections_misses_and_a_confusion_matrix(afw, monkeypatch):
    project_id, plan_id, _genome, site, source = setup_project(monkeypatch)
    apply(plan_id, [("AGM-01-001", "REQUIRED", "brief")])
    complete_task(monkeypatch, plan_id, "AGM-01-001", evidence=[source])
    other_project = create_project()
    foreign = artifact(other_project, "secret", "brand_core", "Another client's brand core.")
    fixtures = [
        ("CLAIM_CHANGE", {"find": "certified organic", "replace": "naturally grown"}, ["CLAIM_CHANGED"]),
        ("SEMANTIC_PRESERVING", {"find": "Every blend is", "replace": "Every  blend  is"}, []),
        ("LOCALE_CHANGE", {"find": "lang=\"en\"", "replace": "lang=\"fr\""}, ["LOCALE_CHANGED"]),
        ("ACCESSIBILITY_REGRESSION", {"find": " alt=\"A cup of green tea\"", "replace": ""}, ["A11Y_ALT_MISSING"]),
        ("STALE_VERSION", {}, ["ARTIFACT_STALE"]),
        ("CROSS_TENANT_REF", {"foreign_artifact_id": foreign.removeprefix("artifact:").rsplit("@v", 1)[0]}, ["REF_NOT_FOUND"]),
        ("MISSING_EVIDENCE", {"task_ids": ["AGM-01-001"]}, ["REFS_REQUIRED"]),
        ("ALTERED_APPROVAL_HASH", {"task_ids": ["AGM-01-001"]}, ["APPROVAL_SUBJECT_MISMATCH"]),
        # Formerly a labelled blind spot (under six words); short claims are now detected by their signals.
        ("CLAIM_CHANGE", {"find": "Ships in 2 days.", "replace": "Ships in 9 days."}, ["CLAIM_CHANGED"]),
        # Still a miss, measured not hidden: "Packed by hand." is a claim with no word the lexicon knows.
        ("CLAIM_CHANGE", {"find": "Packed by hand.", "replace": "Packed by machine."}, ["CLAIM_CHANGED"]),
    ]
    states = []
    for cls, extra, expected in fixtures:
        out = record(plan_id, "mutation", {"base_ref": site, "mutation_class": cls, "expected_findings": expected,
                                           "test_fixture_ref": f"fixture:mutation:{cls.lower()}", **extra})
        states.append((cls, out["record"]["status"], out["record"]["body"]["observed_findings"]))
    assert [s[1] for s in states] == ["DETECTED"] * 9 + ["MISSED"], states
    assert states[1][2] == []  # whitespace-only change: no false positive
    # The canonical page was never touched by any mutation.
    head = ok(client.get(f"/projects/{project_id}/artifacts"))
    page = next(a for a in head["artifacts"] if a["artifact_key"] == "landing-page")
    assert page["version"] == 1
    raw = [r for r in _raw_records(plan_id) if r["kind"] == "mutation"]
    matrix = confusion_matrix(raw)
    assert matrix["CLAIM_CHANGED"]["TP"] == 2 and matrix["CLAIM_CHANGED"]["FN"] == 1
    assert matrix["CLAIM_CHANGED"]["recall"] == round(2 / 3, 4) and matrix["CLAIM_CHANGED"]["precision"] == 1.0
    assert matrix["LOCALE_CHANGED"]["recall"] == 1.0


def test_an_invalid_mutation_spec_is_reported_not_counted(afw, monkeypatch):
    _, plan_id, _, site, _ = setup_project(monkeypatch)
    out = record(plan_id, "mutation", {"base_ref": site, "mutation_class": "CLAIM_CHANGE", "find": "not in the page",
                                       "replace": "x", "expected_findings": ["CLAIM_CHANGED"], "test_fixture_ref": "fixture:bad"})
    assert out["record"]["status"] == "INVALID_TEST" and out["record"]["body"]["invalid_reason"]
    assert confusion_matrix([out["record"]])["CLAIM_CHANGED"]["recall"] == "NOT_MEASURED"


def test_probe_runs_in_a_sandbox_and_never_changes_the_canonical_graph(afw, monkeypatch):
    project_id, plan_id, genome, site, _ = setup_project(monkeypatch)
    genome_id = genome.removeprefix("artifact:").rsplit("@v", 1)[0]
    site_id = site.removeprefix("artifact:").rsplit("@v", 1)[0]
    deck = artifact(project_id, "pitch-deck", "campaign_package", "Deck copy (fictional) using the brand promise.")
    deck_id = deck.removeprefix("artifact:").rsplit("@v", 1)[0]
    before = graph_snapshot(project_id)
    matched = record(plan_id, "probe", {"changed_artifact_id": genome_id, "change_description": "warmer voice (sandbox)",
                                        "declared_effects": [site_id]})
    assert matched["record"]["status"] == "MATCHED"
    body = matched["record"]["body"]
    assert body["write_set_refs"] == [] and body["isolation"]["canonical_unchanged"] is True
    undeclared = record(plan_id, "probe", {"changed_artifact_id": genome_id, "change_description": "new promise",
                                           "declared_effects": []})
    assert undeclared["record"]["status"] == "UNDECLARED_EFFECTS" and undeclared["record"]["body"]["unexpected_effects"] == [site_id]
    missing = record(plan_id, "probe", {"changed_artifact_id": genome_id, "change_description": "promise reword",
                                        "declared_effects": [site_id, deck_id]})
    assert missing["record"]["status"] == "MISSING_EDGES_PROPOSED"
    assert missing["record"]["body"]["graph_amendment_proposals"][0]["status"] == "PROPOSED"
    after = graph_snapshot(project_id)
    # Only the five new record artifacts were added; no edge, head or status of an existing artifact moved.
    existing_before = {n["artifact_id"]: n for n in before["nodes"]}
    assert all(existing_before[a] == n for a, n in ((n["artifact_id"], n) for n in after["nodes"]) if a in existing_before)
    assert after["edges"] == before["edges"]
    response = client.post(f"/agency-framework/plans/{plan_id}/assurance/probe", headers=key(),
                           json={"changed_artifact_id": "art-not-here", "change_description": "x" * 5})
    assert response.status_code == 422


def test_renewal_retains_the_decision_and_alternatives_and_never_replaces_it(afw, monkeypatch):
    from services.langgraph.persistence.agency_kernel import get_decision

    project_id, plan_id, _, _, source = setup_project(monkeypatch)
    decided = decision(plan_id, "Primary positioning?", ["Origin-led", "Price-led", "Ritual-led"], "Origin-led", [source])
    before = get_decision(decided.removeprefix("decision:"))
    contrary = evidence(monkeypatch, project_id, "New survey (fictional). Most buyers in the panel chose tea for the daily "
                                                 "ritual rather than for its origin or certification.")
    proposal = artifact(project_id, "positioning-proposal", "positioning_statement", "Proposal: ritual-led positioning.")
    out = record(plan_id, "renewal", {
        "trigger_kind": "NEW_CONTRADICTION", "trigger_evidence_refs": [contrary], "affected_decision_ref": decided,
        "proposed_alternatives": ["Ritual-led"], "rationale": "Survey contradicts the origin-led premise.",
        "impact_scope": ["AGM-06", "AGM-07"], "proposal_ref": proposal, "request_review": True})
    body = out["record"]["body"]
    assert out["record"]["status"] == "UNDER_REVIEW" and body["decision_unchanged"] is True
    assert body["retained_alternatives"] == ["Origin-led", "Price-led", "Ritual-led"]
    assert body["retained_decision"]["selected_option"] == "Origin-led"
    # Approving the proposal does not change the decision; only native governance can.
    ok(decide(monkeypatch, body["review_request_ref"]))
    assert get_decision(decided.removeprefix("decision:")) == before


def test_review_binds_exact_subjects_reads_full_bytes_and_cannot_approve_by_itself(afw, monkeypatch):
    project_id, plan_id, genome, site, _ = setup_project(monkeypatch)
    out = record(plan_id, "review", {"candidate_refs": [genome, site], "summary": "Two candidates.", "request_decision": True})
    body = out["record"]["body"]
    assert out["record"]["status"] == "NEEDS_HUMAN"
    assert body["access_check_receipt"]["full_candidate_access"] is True
    assert all(s["bytes_read"] > 0 for s in body["access_check_receipt"]["subjects"])
    assert body["decision_ref"] and len(body["decision_subject_hash"]) == 64
    # The record itself approved nothing.
    approval = next(a for a in client.get("/approvals").json() if a["approval_id"] == body["decision_ref"])
    assert approval["status"] == "pending"
    # A candidate that moved on is no longer current; a new review must bind the new version.
    revise(project_id, site, SITE.replace("Lyon", "Marseille"))
    reread = ok(client.get(f"/agency-framework/plans/{plan_id}/assurance/{out['record']['record_id']}"))
    assert reread["subject_now"]["subject_current"] is False
    stale = record(plan_id, "review", {"candidate_refs": [genome, site], "request_decision": True}, status=409)
    assert stale["error"]["code"] == "REVIEW_NOT_READY"
    # Revalidation makes the pending review decision undecidable.
    out2 = ok(client.post(f"/agency-framework/plans/{plan_id}/revalidate", headers=key()))
    assert out2["staled_review_approvals"] == [body["decision_ref"]]
    assert decide(monkeypatch, body["decision_ref"]).status_code == 409


def test_records_are_append_only_and_tampering_is_detected(afw, monkeypatch):
    project_id, plan_id, _, site, _ = setup_project(monkeypatch)
    first = record(plan_id, "meaning", {"task_ids": ["AGM-10-002"], "interpreted_obligation": "Page names origin.",
                                        "qualifiers": ["Lyon"], "output_refs": [site]})
    rid = first["record"]["record_id"]
    assert first["integrity"]["status"] == "VERIFIED"
    second = record(plan_id, "meaning", {"task_ids": ["AGM-10-002"], "interpreted_obligation": "Page names origin city.",
                                         "qualifiers": ["Lyon"], "output_refs": [site], "supersedes_ref": rid})
    again = record(plan_id, "meaning", {"task_ids": ["AGM-10-002"], "interpreted_obligation": "Another correction.",
                                        "qualifiers": ["Lyon"], "output_refs": [site], "supersedes_ref": rid}, status=409)
    assert again["error"]["code"] == "STALE_SUPERSEDE"
    listing = ok(client.get(f"/agency-framework/plans/{plan_id}/assurance", params={"kind": "meaning"}))["items"]
    heads = {i["record_id"]: i["is_head"] for i in listing}
    assert heads == {rid: False, second["record"]["record_id"]: True}
    assert ok(client.get(f"/agency-framework/plans/{plan_id}/assurance/{rid}"))["superseded_by"] == [second["record"]["record_id"]]
    # Revising the record's artifact through the generic artifact route is detected on read.
    ok(client.post(f"/projects/{project_id}/artifacts/{first['artifact_id']}/revisions",
                   json={"expected_version": 1, "content_text": json.dumps({**first["record"], "status": "COVERED"})}))
    tampered = ok(client.get(f"/agency-framework/plans/{plan_id}/assurance/{rid}"))
    assert tampered["integrity"]["status"] == "INTEGRITY_FAILED"


def test_records_reject_foreign_or_missing_refs_and_are_invisible_to_other_tenants(afw, monkeypatch):
    _project_id, plan_id, _, site, _ = setup_project(monkeypatch)
    other = create_project()
    foreign = evidence(monkeypatch, other, "Another client's survey (fictional). Their customers prefer subscription "
                                           "boxes delivered every month.")
    response = client.post(f"/agency-framework/plans/{plan_id}/assurance/meaning", headers=key(), json={
        "task_ids": ["AGM-10-001"], "interpreted_obligation": "x" * 5, "evidence_refs": [foreign]})
    assert response.status_code == 422 and response.json()["error"]["details"]["checks"][0]["status"] == "REF_NOT_FOUND"
    response = client.post(f"/agency-framework/plans/{plan_id}/assurance/meaning", headers=key(), json={
        "task_ids": ["AGM-99-001"], "interpreted_obligation": "x" * 5})
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_RECORD"
    response = client.post(f"/agency-framework/plans/{plan_id}/assurance/opinion", headers=key(), json={})
    assert response.status_code == 404
    out = record(plan_id, "meaning", {"task_ids": ["AGM-10-001"], "interpreted_obligation": "Origin stated.",
                                      "qualifiers": ["Lyon"], "output_refs": [site]})
    as_user(monkeypatch, "intruder", "admin", tenant="tenant-other")
    assert client.get(f"/agency-framework/plans/{plan_id}/assurance/{out['record']['record_id']}").status_code == 404
    response = client.post(f"/agency-framework/plans/{plan_id}/assurance/meaning", headers=key(), json={
        "task_ids": ["AGM-10-001"], "interpreted_obligation": "x" * 5})
    assert response.status_code == 404
    as_user(monkeypatch, AUTHOR)


def test_all_five_records_persist_and_read_back_in_a_fresh_process(afw, monkeypatch):
    project_id, plan_id, genome, site, source = setup_project(monkeypatch)
    genome_id = genome.removeprefix("artifact:").rsplit("@v", 1)[0]
    decided = decision(plan_id, "Primary channel?", ["Wholesale", "Direct"], "Wholesale", [source])
    ids = [
        record(plan_id, "meaning", {"task_ids": ["AGM-10-001"], "interpreted_obligation": "Origin stated.",
                                    "qualifiers": ["Lyon"], "output_refs": [site]})["record"]["record_id"],
        record(plan_id, "mutation", {"base_ref": site, "mutation_class": "LOCALE_CHANGE", "find": "lang=\"en\"",
                                     "replace": "lang=\"de\"", "expected_findings": ["LOCALE_CHANGED"],
                                     "test_fixture_ref": "fixture:locale"})["record"]["record_id"],
        record(plan_id, "probe", {"changed_artifact_id": genome_id, "change_description": "sandbox voice change",
                                  "declared_effects": [site.removeprefix("artifact:").rsplit("@v", 1)[0]]})["record"]["record_id"],
        record(plan_id, "renewal", {"trigger_kind": "CLIENT_REQUEST", "trigger_evidence_refs": [source],
                                    "affected_decision_ref": decided, "proposed_alternatives": ["Direct"],
                                    "rationale": "Client wants to test direct sales."})["record"]["record_id"],
        record(plan_id, "review", {"candidate_refs": [site]})["record"]["record_id"],
    ]
    script = (
        "import json, sys\n"
        "from services.langgraph.agency.operating_framework.assurance import read_record\n"
        "from services.langgraph.security.auth import Principal\n"
        "p = Principal(user_id='fresh-reader', tenant_id='tenant-events-test', role='viewer', allowed_project_ids=frozenset({sys.argv[2]}))\n"
        "out = [read_record(p, sys.argv[1], rid) for rid in sys.argv[3:]]\n"
        "print(json.dumps([[o['record']['kind'], o['integrity']['status'], o['record']['record_hash']] for o in out]))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run([sys.executable, "-c", script, plan_id, project_id, *ids], capture_output=True, text=True, check=False,
                            cwd=ROOT, env=env, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    rows = json.loads(result.stdout.strip().splitlines()[-1])
    assert [r[0] for r in rows] == ["meaning", "mutation", "probe", "renewal", "review"]
    assert {r[1] for r in rows} == {"VERIFIED"}
    in_process = [ok(client.get(f"/agency-framework/plans/{plan_id}/assurance/{rid}"))["record"]["record_hash"] for rid in ids]
    assert [r[2] for r in rows] == in_process


def _raw_records(plan_id: str) -> list[dict]:
    from services.langgraph.agency.operating_framework.assurance import list_records_raw
    from services.langgraph.persistence.operating_framework import get_plan

    return list_records_raw(get_plan(plan_id))
