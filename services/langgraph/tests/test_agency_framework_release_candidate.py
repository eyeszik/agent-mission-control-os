"""A framework Review bound to a sealed delivery release candidate.

The Review reads the candidate delivery sealed for a run, re-checks it at use
time (manifest hash, approval subject, artifact heads, dependency snapshot, the
stored payload behind every artifact hash) and links the run's own approval.
It never opens a second release approval and never releases anything: release
stays with ``agency/delivery`` (``evaluate_release_predicate`` on resume).
All data is fictional.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from services.langgraph.persistence.approvals import get_approvals_for_run
from services.langgraph.persistence.runs import get_run_record, update_run_status
from services.langgraph.security.auth import Principal
from services.langgraph.tests.framework_support import (
    AUTHOR,
    TENANT,
    afw,  # noqa: F401 - fixture
    as_user,
    client,
    create_project,
    decide,
    instantiate,
    key,
    ok,
)
from services.langgraph.tests.test_unified_delivery import (  # noqa: F401 - fixture
    ABSENT_PHRASE,
    _contract,
    provider_success,
)

INSPECTOR = "afw-inspector"


def _run(project_id: str, mode: str, monkeypatch) -> dict:
    monkeypatch.setenv("AMC_CONTRACT_MODE", mode)
    body = {"project_id": project_id, "brief": {"brand_name": "Northwind", "target_audience": "Urban professionals"}}
    if mode != "off":
        body["delivery_contract"] = _contract(ABSENT_PHRASE)
    return ok(client.post("/agency/runs", json=body, headers=key()), 201)


def _world(monkeypatch, mode: str = "enforce") -> tuple[str, str, dict]:
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    return project_id, plan_id, _run(project_id, mode, monkeypatch)


def _review(monkeypatch, plan_id: str, run_id: str, *, user: str = INSPECTOR, role: str = "reviewer",
            idem: dict | None = None, **extra):
    as_user(monkeypatch, user, role)
    try:
        return client.post(f"/agency-framework/plans/{plan_id}/assurance/review", headers=idem or key(), json={
            "task_ids": ["AGM-20-001"], "release_candidate_ref": f"release-candidate:{run_id}",
            "summary": "Launch package for the fictional brand.", **extra})
    finally:
        as_user(monkeypatch, AUTHOR)


def _subject_refs(run: dict) -> list[str]:
    return sorted(f"artifact:{r['artifact_id']}@v{r['version_ref'].rsplit(':v', 1)[1]}"
                  for r in run["release_candidate"]["manifest"]["artifact_refs"])


def test_review_binds_the_exact_sealed_candidate_and_reads_it_back(afw, monkeypatch, provider_success):
    _, plan_id, run = _world(monkeypatch)
    sealed = run["release_candidate"]
    approval = get_approvals_for_run(run["run_id"])[0]

    created = ok(_review(monkeypatch, plan_id, run["run_id"]), 201)
    record = created["record"]
    body = record["body"]
    candidate = body["release_candidate"]
    assert record["status"] == "NEEDS_HUMAN" and body["blocking_findings"] == []
    assert candidate["candidate_manifest_hash"] == sealed["candidate_manifest_hash"]
    assert candidate["approval_subject_hash"] == sealed["approval_subject_hash"]
    assert body["candidate_manifest_ref"] == f"release-candidate:{run['run_id']}#{sealed['candidate_manifest_hash']}"
    assert sorted(s["ref"] for s in body["candidate_subject_refs"]) == _subject_refs(run)
    # Full-candidate inspection: every artifact hash was recomputed from the payload it was sealed over.
    assert body["access_check_receipt"]["full_candidate_access"] is True
    assert all(a["hash_verified"] and a["bytes_read"] > 0 for a in body["access_check_receipt"]["subjects"])
    assert candidate["freshness"] == {"manifest_hash_verified": True, "approval_subject_verified": True,
                                      "artifacts_current": True, "dependencies_current": True}
    native = candidate["native_approval"]
    assert native["approval_id"] == approval["approval_id"] and native["subject_bound"] is True
    assert native["status"] == "pending"
    assert body["decision_ref"] is None  # the run's approval is the decision; no second one is opened
    assert record["subject_refs"][0] == f"release-candidate:{run['run_id']}"

    read = ok(client.get(f"/agency-framework/plans/{plan_id}/assurance/{record['record_id']}"))
    assert read["integrity"]["status"] == "VERIFIED"
    assert read["record"]["body"]["release_candidate"] == candidate
    assert read["subject_now"]["subject_current"] is True
    assert read["subject_now"]["release_candidate"]["candidate_manifest_hash"] == sealed["candidate_manifest_hash"]

    # Release is still delivery's: the review changed nothing, and the run's own approval releases it.
    assert get_run_record(run["run_id"])["status"] == "needs_approval"
    assert [a["approval_id"] for a in get_approvals_for_run(run["run_id"])] == [approval["approval_id"]]
    ok(decide(monkeypatch, approval["approval_id"]))
    resumed = ok(client.post(f"/agency/runs/{run['run_id']}/resume", headers=key()))
    assert resumed["release_receipt"]["candidate_manifest_hash"] == candidate["candidate_manifest_hash"]


def test_missing_foreign_project_and_foreign_tenant_candidates_are_not_found(afw, monkeypatch, provider_success):
    project_id, plan_id, _ = _world(monkeypatch)
    missing = _review(monkeypatch, plan_id, f"run-{uuid4()}")
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "REF_NOT_FOUND"
    other_project = _run(create_project(), "enforce", monkeypatch)
    foreign = _review(monkeypatch, plan_id, other_project["run_id"])
    assert foreign.status_code == 422 and foreign.json()["error"]["code"] == "REF_NOT_FOUND"
    # A run in another tenant is indistinguishable from a missing one.
    as_user(monkeypatch, AUTHOR, tenant="tenant-other-afw")
    other_tenant_project = create_project()
    other_tenant = _run(other_tenant_project, "enforce", monkeypatch)
    as_user(monkeypatch, AUTHOR, tenant=TENANT)
    response = _review(monkeypatch, plan_id, other_tenant["run_id"])
    assert response.status_code == 422 and response.json()["error"]["code"] == "REF_NOT_FOUND"
    assert "tenant-other-afw" not in response.text and other_tenant_project not in response.text
    assert ok(client.get(f"/agency-framework/plans/{plan_id}/assurance", params={"kind": "review"}))["items"] == []
    _ = project_id


def test_only_an_approver_who_did_not_start_the_run_may_bind_its_candidate(afw, monkeypatch, provider_success):
    _, plan_id, run = _world(monkeypatch)
    operator = _review(monkeypatch, plan_id, run["run_id"], role="operator")
    assert operator.status_code == 403 and operator.json()["error"]["code"] == "REVIEWER_ROLE_REQUIRED"
    initiator = _review(monkeypatch, plan_id, run["run_id"], user=AUTHOR)
    assert initiator.status_code == 403 and initiator.json()["error"]["code"] == "REVIEWER_IS_INITIATOR"
    assert ok(client.get(f"/agency-framework/plans/{plan_id}/assurance", params={"kind": "review"}))["items"] == []


def test_a_candidate_whose_artifacts_moved_is_blocked_and_an_earlier_review_goes_stale(afw, monkeypatch, provider_success):
    _, plan_id, run = _world(monkeypatch)
    earlier = ok(_review(monkeypatch, plan_id, run["run_id"]), 201)["record"]
    key_ = run["artifact_bindings"][0]["artifact_key"]
    ok(client.post(f"/agency/runs/{run['run_id']}/artifacts/rebind", json={"artifact_key": key_, "revision_note": "tighten"}))

    now = ok(client.get(f"/agency-framework/plans/{plan_id}/assurance/{earlier['record_id']}"))
    assert now["subject_now"]["subject_current"] is False
    assert "ARTIFACTS_CHANGED" in now["subject_now"]["release_candidate"]["blocking"]

    later = ok(_review(monkeypatch, plan_id, run["run_id"]), 201)["record"]
    assert later["status"] == "BLOCKED"
    assert "ARTIFACTS_CHANGED" in later["body"]["blocking_findings"]
    assert later["body"]["release_candidate"]["freshness"]["artifacts_current"] is False


def test_a_new_dependency_edge_makes_the_candidate_stale(afw, monkeypatch, provider_success):
    from services.langgraph.persistence.agency_kernel import ensure_artifact_dependency
    from services.langgraph.persistence.delivery import dependency_edges

    _, plan_id, run = _world(monkeypatch)
    workspace = [b["artifact_id"] for b in run["artifact_bindings"]]
    existing = {(e["artifact_id"], e["depends_on_artifact_id"]) for e in dependency_edges(workspace)}
    added = None
    for downstream in workspace:
        for upstream in workspace:
            if downstream == upstream or (downstream, upstream) in existing or (upstream, downstream) in existing:
                continue
            try:
                ensure_artifact_dependency(downstream, upstream)
            except ValueError:
                continue
            added = (downstream, upstream)
            break
        if added:
            break
    assert added, "no new edge could be added between the run's artifacts"
    record = ok(_review(monkeypatch, plan_id, run["run_id"]), 201)["record"]
    assert record["status"] == "BLOCKED" and "DEPENDENCIES_CHANGED" in record["body"]["blocking_findings"]
    assert record["body"]["release_candidate"]["freshness"]["artifacts_current"] is True


def test_a_tampered_seal_or_a_forged_approval_subject_is_blocking(afw, monkeypatch, provider_success):
    from services.langgraph.persistence.database import table, transaction

    _, plan_id, run = _world(monkeypatch)
    approval = get_approvals_for_run(run["run_id"])[0]
    with transaction(write=True) as db:
        db.execute(f"UPDATE {table('approvals')} SET subject_hash = ? WHERE approval_id = ?",
                   ("forged-subject", approval["approval_id"]))
    forged = ok(_review(monkeypatch, plan_id, run["run_id"]), 201)["record"]
    assert forged["status"] == "BLOCKED" and "APPROVAL_SUBJECT_MISMATCH" in forged["body"]["blocking_findings"]

    record = get_run_record(run["run_id"])
    agency = dict(record["result"]["agency"])
    candidate = dict(agency["release_candidate"])
    manifest = dict(candidate["manifest"])
    manifest["contract_result_refs"] = ["tampered"]
    agency["release_candidate"] = {**candidate, "manifest": manifest}
    update_run_status(run["run_id"], record["status"], {**record["result"], "agency": agency})
    tampered = ok(_review(monkeypatch, plan_id, run["run_id"]), 201)["record"]
    assert tampered["status"] == "BLOCKED" and "CANDIDATE_HASH_MISMATCH" in tampered["body"]["blocking_findings"]


def test_an_unsealed_run_and_a_run_without_its_approval_are_reported_honestly(afw, monkeypatch, provider_success):
    project_id, plan_id, legacy = _world(monkeypatch, mode="off")
    unsealed = ok(_review(monkeypatch, plan_id, legacy["run_id"]), 201)["record"]
    assert unsealed["status"] == "BLOCKED"
    assert unsealed["body"]["blocking_findings"] == ["CANDIDATE_NOT_SEALED"]
    assert unsealed["body"]["candidate_subject_refs"] == []

    sealed = _run(project_id, "enforce", monkeypatch)
    monkeypatch.setattr("services.langgraph.agency.operating_framework.candidates.get_approvals_for_run", lambda run_id: [])
    no_approval = ok(_review(monkeypatch, plan_id, sealed["run_id"]), 201)["record"]
    assert no_approval["status"] == "NEEDS_HUMAN"
    assert no_approval["body"]["release_candidate"]["native_approval"] is None
    assert "release approval not opened for this run" in no_approval["body"]["unresolved_findings"]


def test_a_candidate_review_cannot_open_its_own_decision_or_change_the_subjects(afw, monkeypatch, provider_success):
    _, plan_id, run = _world(monkeypatch)
    before = len(get_approvals_for_run(run["run_id"]))
    decision = _review(monkeypatch, plan_id, run["run_id"], request_decision=True)
    assert decision.status_code == 422 and decision.json()["error"]["code"] == "RELEASE_DECISION_OWNED_BY_DELIVERY"
    narrowed = _review(monkeypatch, plan_id, run["run_id"], candidate_refs=_subject_refs(run)[:1])
    assert narrowed.status_code == 422 and narrowed.json()["error"]["code"] == "CANDIDATE_REFS_MISMATCH"
    exact = _review(monkeypatch, plan_id, run["run_id"], candidate_refs=_subject_refs(run))
    assert exact.status_code == 201
    assert len(get_approvals_for_run(run["run_id"])) == before
    assert not [a for a in client.get("/approvals").json() if a.get("subject_type") == "AGENCY_REVIEW_CANDIDATE"
                and a.get("project_id") == run["project_id"]]


def test_a_repeated_request_replays_and_concurrent_supersedes_have_one_winner(afw, monkeypatch, provider_success):
    from services.langgraph.agency.operating_framework import assurance
    from services.langgraph.agency.operating_framework.contracts import FrameworkError

    project_id, plan_id, run = _world(monkeypatch)
    idem = key()
    first = ok(_review(monkeypatch, plan_id, run["run_id"], idem=idem), 201)["record"]
    again = ok(_review(monkeypatch, plan_id, run["run_id"], idem=idem), 201)["record"]
    assert again["record_id"] == first["record_id"]
    assert len(ok(client.get(f"/agency-framework/plans/{plan_id}/assurance", params={"kind": "review"}))["items"]) == 1

    principal = Principal(user_id=INSPECTOR, tenant_id=TENANT, role="reviewer", allowed_project_ids=frozenset({project_id}))
    payload = {"task_ids": ["AGM-20-001"], "release_candidate_ref": f"release-candidate:{run['run_id']}",
               "supersedes_ref": first["record_id"]}

    def supersede(_):
        try:
            return assurance.create_record(principal, plan_id, "review", payload)["record"]["record_id"]
        except FrameworkError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(supersede, range(4)))
    winners = [o for o in outcomes if o.startswith("asr-")]
    assert len(winners) == 1 and outcomes.count("STALE_SUPERSEDE") == 3, outcomes
    records = ok(client.get(f"/agency-framework/plans/{plan_id}/assurance", params={"kind": "review"}))["items"]
    assert sorted(r["record_id"] for r in records) == sorted([first["record_id"], winners[0]])


def test_an_interrupted_write_persists_nothing_and_a_retry_records_once(afw, monkeypatch, provider_success):
    from services.langgraph.persistence import projects

    _, plan_id, run = _world(monkeypatch)
    real = projects.create_project_artifact

    def crash(**kwargs):
        raise RuntimeError("simulated crash before the record is stored")

    monkeypatch.setattr(projects, "create_project_artifact", crash)
    with pytest.raises(RuntimeError):
        _review(monkeypatch, plan_id, run["run_id"])
    assert ok(client.get(f"/agency-framework/plans/{plan_id}/assurance", params={"kind": "review"}))["items"] == []
    monkeypatch.setattr(projects, "create_project_artifact", real)
    ok(_review(monkeypatch, plan_id, run["run_id"]), 201)
    assert len(ok(client.get(f"/agency-framework/plans/{plan_id}/assurance", params={"kind": "review"}))["items"]) == 1
