"""Agency operating framework: catalog seed, task engine, stage gates, authority boundaries."""

from __future__ import annotations

import copy
import json

import pytest

from services.langgraph.agency.operating_framework.bindings import (
    MODULE_BINDINGS,
    coverage_report,
    verify_bindings,
)
from services.langgraph.agency.operating_framework.catalog import (
    CATALOG_FILE,
    PINNED_CATALOG_SHA256,
    SCHEMA_FILE,
    CatalogInvalid,
    load_catalog,
    parse_catalog,
)
from services.langgraph.tests.framework_support import (
    AUTHOR,
    REVIEWER,
    VERIFIER,
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
    move,
    ok,
    revise,
    set_refs,
    task,
    verify,
    version,
)

SCHEMA = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
RAW = CATALOG_FILE.read_bytes()


# ------------------------------------------------------------------------------ catalog


def test_catalog_has_24_modules_and_295_unique_tasks_matching_the_published_counts():
    catalog = load_catalog()
    summary = catalog.summary()
    assert (summary["module_count"], summary["task_count"]) == (24, 295)
    assert len({t.task_id for t in catalog.tasks}) == 295
    assert summary["user_supplied_task_count"] == 35 and summary["newly_authored_task_count"] == 260
    assert summary["per_discipline"] == {"Discover": 48, "Strategize": 58, "Design": 29, "Build": 79, "Activate": 59, "Optimize": 22}
    assert summary["per_stage_gate"] == {"01_DISCOVERY": 48, "02_STRATEGY": 58, "03_PRODUCTION": 108,
                                         "04_ACTIVATION": 59, "05_GROWTH": 22}
    assert sum(summary["per_stage_gate"].values()) == 295
    assert [summary["per_module"][m.module_id] for m in catalog.modules] == [
        10, 10, 15, 13, 12, 12, 12, 15, 10, 15, 15, 14, 12, 12, 13, 11, 11, 12, 11, 13, 11, 12, 12, 12]
    assert catalog.sha256 == PINNED_CATALOG_SHA256
    assert {t.module_id for t in catalog.tasks if t.definition_source == "user_supplied"} == {"AGM-01", "AGM-02", "AGM-03"}


def test_catalog_matches_the_kit_schema_with_an_independent_validator_when_available():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(json.loads(RAW), SCHEMA)


def _mutated(change) -> bytes:
    data = json.loads(RAW)
    change(data)
    return json.dumps(data).encode()


@pytest.mark.parametrize("change, fragment", [
    (lambda d: d["tasks"][1].update(task_id=d["tasks"][0]["task_id"]), "duplicate task id"),
    (lambda d: d["modules"][1]["depends_on_modules"].append("AGM-02"), "depends on itself"),
    (lambda d: d["modules"][0]["depends_on_modules"].append("AGM-24"), "cycle"),
    (lambda d: d["tasks"].pop(), "fewer than 295 items"),
    (lambda d: d["tasks"][0].update(status="COMPLETE"), "must equal"),
    (lambda d: d["tasks"][0].update(evidence_refs=["x"]), "more than 0 items"),
    (lambda d: d["tasks"][0].update(extra="x"), "unexpected properties"),
    (lambda d: d["modules"][0].update(module_id="AGM-99"), "does not match"),
])
def test_invalid_catalogs_are_refused_before_anything_is_imported(change, fragment):
    with pytest.raises(CatalogInvalid) as exc:
        parse_catalog(_mutated(change), SCHEMA, expected_sha256=None)
    assert any(fragment in p for p in exc.value.problems), exc.value.problems


def test_a_catalog_with_a_different_hash_is_a_different_version_not_a_silent_upgrade():
    with pytest.raises(CatalogInvalid, match="not the pinned"):
        parse_catalog(RAW + b" ", SCHEMA)


def test_every_module_binds_to_an_n3_role_that_may_produce_its_artifact_type():
    assert verify_bindings(load_catalog()) == []
    report = coverage_report()
    assert sum(len(v) for v in report.values()) == 24
    assert set(report["NO_N3_ROLE"]) == {"AGM-11", "AGM-16", "AGM-17", "AGM-22", "AGM-23"}
    effects = {m: b.external_effect for m, b in MODULE_BINDINGS.items() if b.external_effect != "none"}
    assert effects == {"AGM-13": "publish", "AGM-14": "spend", "AGM-15": "send", "AGM-16": "outreach",
                       "AGM-17": "publish", "AGM-20": "publish"}
    assert all(MODULE_BINDINGS[m].capability in ("DRY_RUN_ONLY", "PLANNING_ONLY", "HUMAN_ONLY") for m in effects)


# ------------------------------------------------------------------------------ instantiation


def test_new_plan_has_295_unassessed_tasks_zero_verified_and_progress_not_measured(afw):
    project_id = create_project()
    view = instantiate(project_id, "B2C_PHYSICAL_PRODUCT")
    assert view["created"] is True and view["catalog"]["pinned"] is True
    overall = view["progress"]["overall"]
    assert overall["defined"] == 295 and overall["unassessed"] == 295
    assert overall["verified"] == 0 and overall["approved"] == 0
    assert overall["required_verified_ratio"] == "NOT_MEASURED"
    assert [g["status"] for g in view["gates"]] == ["NOT_ASSESSED"] * 5
    assert view["readiness"]["release_eligible"] is False and view["readiness"]["externally_executed"] is False
    tasks = ok(client.get(f"/agency-framework/plans/{view['plan']['plan_id']}/tasks"))["items"]
    assert len(tasks) == 295 and {t["state"] for t in tasks} == {"BACKLOG"}


def test_reinstantiation_is_idempotent_and_never_overwrites_work(afw):
    project_id = create_project()
    first = instantiate(project_id)
    plan_id = first["plan"]["plan_id"]
    apply(plan_id, [("AGM-01-001", "REQUIRED", "core discovery")])
    again = instantiate(project_id)
    assert again["created"] is False and again["plan"]["plan_id"] == plan_id
    assert task(plan_id, "AGM-01-001")["instance"]["applicability"] == "REQUIRED"
    assert again["progress"]["overall"]["defined"] == 295


def test_plan_requires_an_existing_project_in_scope(afw, monkeypatch):
    response = client.post("/agency-framework/plans", json={"project_id": "proj-does-not-exist"}, headers=key())
    assert response.status_code == 404 and response.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    project_id = create_project()
    as_user(monkeypatch, AUTHOR, projects="some-other-project")
    response = client.post("/agency-framework/plans", json={"project_id": project_id}, headers=key())
    assert response.status_code == 403


# ------------------------------------------------------------------------------ applicability + progress


def test_applicability_drives_progress_and_zero_denominator_is_not_measured(afw):
    plan_id = instantiate(create_project())["plan"]["plan_id"]
    result = apply(plan_id, [("AGM-14-001", "NOT_APPLICABLE", "no paid media in scope"),
                             ("AGM-01-001", "REQUIRED", "core"), ("AGM-01-002", "CONDITIONAL", "if equity exists")])
    assert {a["task_id"] for a in result["applied"]} == {"AGM-14-001", "AGM-01-001", "AGM-01-002"}
    assert task(plan_id, "AGM-14-001")["instance"]["state"] == "NOT_APPLICABLE"
    view = ok(client.get(f"/agency-framework/plans/{plan_id}"))
    discovery = view["progress"]["stage_gates"]["01_DISCOVERY"]
    assert (discovery["required"], discovery["conditional"], discovery["required_verified_ratio"]) == (1, 1, 0.0)
    assert view["progress"]["modules"]["AGM-14"]["not_applicable"] == 1
    assert view["progress"]["stage_gates"]["05_GROWTH"]["required_verified_ratio"] == "NOT_MEASURED"


def test_a_task_cannot_start_before_its_applicability_is_decided(afw):
    plan_id = instantiate(create_project())["plan"]["plan_id"]
    response = move(plan_id, "AGM-01-001", "READY")
    assert response.status_code == 409 and response.json()["error"]["code"] == "APPLICABILITY_UNDECIDED"


# ------------------------------------------------------------------------------ the guarded lifecycle


def test_checkbox_states_cannot_be_reached_by_a_direct_transition(afw):
    plan_id = instantiate(create_project())["plan"]["plan_id"]
    apply(plan_id, [("AGM-01-001", "REQUIRED", "core")])
    for target in ("VERIFIED", "APPROVED", "INVALIDATED"):
        response = move(plan_id, "AGM-01-001", target)
        assert response.status_code == 409 and response.json()["error"]["code"] == "TRANSITION_NOT_MANUAL", target


def test_review_needs_refs_of_the_right_kind_and_refs_must_exist_in_the_project(afw, monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    apply(plan_id, [("AGM-01-001", "REQUIRED", "core"), ("AGM-05-001", "REQUIRED", "offer")])
    ok(move(plan_id, "AGM-01-001", "READY"))
    ok(move(plan_id, "AGM-01-001", "ACTIVE"))
    response = move(plan_id, "AGM-01-001", "IN_REVIEW")
    assert response.status_code == 422 and response.json()["error"]["code"] == "REFS_REQUIRED"
    response = set_refs(plan_id, "AGM-01-001", evidence=["knowledge:kn-does-not-exist"])
    assert response.status_code == 422 and response.json()["error"]["code"] == "REF_REJECTED"
    other = create_project()
    foreign = evidence(monkeypatch, other, "Another project's interview notes. Customers value speed.")
    response = set_refs(plan_id, "AGM-01-001", evidence=[foreign])
    assert response.status_code == 422
    assert response.json()["error"]["details"]["checks"][0]["status"] == "REF_NOT_FOUND"
    response = set_refs(plan_id, "AGM-01-001", evidence=["not-a-ref"])
    assert response.status_code == 422


def test_full_task_lifecycle_needs_a_second_verifier_and_a_third_party_approval(afw, monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    apply(plan_id, [("AGM-01-001", "REQUIRED", "core")])
    source = evidence(monkeypatch, project_id, "Stakeholder interview (fictional). The owner wants wholesale growth in 2027.")
    ok(move(plan_id, "AGM-01-001", "READY"))
    ok(move(plan_id, "AGM-01-001", "ACTIVE"))
    ok(set_refs(plan_id, "AGM-01-001", evidence=[source]))
    ok(move(plan_id, "AGM-01-001", "IN_REVIEW"))
    # The author cannot verify their own work.
    response = verify(monkeypatch, plan_id, "AGM-01-001", user=AUTHOR, role="admin")
    assert response.status_code == 403 and response.json()["error"]["code"] == "SELF_VERIFICATION"
    # An operator cannot verify at all.
    response = verify(monkeypatch, plan_id, "AGM-01-001", user="someone-else", role="operator")
    assert response.status_code == 403 and response.json()["error"]["code"] == "VERIFIER_ROLE_REQUIRED"
    verified = ok(verify(monkeypatch, plan_id, "AGM-01-001"))
    assert verified["state"] == "VERIFIED" and verified["verification"]["result"] == "PASSED"
    assert verified["verification"]["origins"] == ["SYNTHETIC"]
    requested = ok(client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-01-001/request-approval",
                               json={"expected_version": version(plan_id, "AGM-01-001")}, headers=key()))
    approval_id = requested["approval_ref"]
    settle = lambda: client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-01-001/settle",
                                 json={"expected_version": version(plan_id, "AGM-01-001")}, headers=key())
    response = settle()
    assert response.status_code == 409 and response.json()["error"]["code"] == "APPROVAL_PENDING"
    # The person who requested the approval cannot decide it (separation of duties).
    response = decide(monkeypatch, approval_id, user=AUTHOR, role="admin")
    assert response.status_code == 403
    ok(decide(monkeypatch, approval_id))
    approved = ok(settle())
    assert approved["state"] == "APPROVED"
    view = ok(client.get(f"/agency-framework/plans/{plan_id}"))
    assert view["progress"]["overall"]["approved"] == 1
    assert view["readiness"]["release_eligible"] is False
    kinds = [e["payload"].get("kind") for e in ok(client.get(f"/agency-framework/plans/{plan_id}/audit"))["events"]]
    for expected in ("agency_framework.applicability", "agency_framework.refs", "agency_framework.verified",
                     "agency_framework.approval_requested", "agency_framework.approved"):
        assert expected in kinds


def test_rejected_approval_returns_the_task_to_rework_and_is_measured(afw, monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    apply(plan_id, [("AGM-01-001", "REQUIRED", "core")])
    source = evidence(monkeypatch, project_id, "Interview notes (fictional). Margins are thin on retail orders.")
    ok(move(plan_id, "AGM-01-001", "READY"))
    ok(move(plan_id, "AGM-01-001", "ACTIVE"))
    ok(set_refs(plan_id, "AGM-01-001", evidence=[source]))
    ok(move(plan_id, "AGM-01-001", "IN_REVIEW"))
    ok(verify(monkeypatch, plan_id, "AGM-01-001"))
    requested = ok(client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-01-001/request-approval",
                               json={"expected_version": version(plan_id, "AGM-01-001")}, headers=key()))
    ok(decide(monkeypatch, requested["approval_ref"], "reject"))
    out = ok(client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-01-001/settle",
                         json={"expected_version": version(plan_id, "AGM-01-001")}, headers=key()))
    assert out["state"] == "ACTIVE" and "rejected" in out["status_reason"]
    metrics = {m["metric_id"]: m for m in ok(client.get(f"/agency-framework/plans/{plan_id}/metrics"))["metrics"]}
    assert metrics["delivery.approval_rework_rate"]["value"] == 1.0
    assert metrics["sales.cac"]["value"] == "NOT_MEASURED"


def test_stale_version_is_an_explicit_conflict(afw):
    plan_id = instantiate(create_project())["plan"]["plan_id"]
    apply(plan_id, [("AGM-01-001", "REQUIRED", "core")])
    current = version(plan_id, "AGM-01-001")
    ok(move(plan_id, "AGM-01-001", "READY"))
    response = client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-01-001/transition",
                           json={"target": "ACTIVE", "expected_version": current}, headers=key())
    assert response.status_code == 409 and response.json()["error"]["code"] == "STALE_VERSION"


def test_concurrent_writers_on_one_version_have_exactly_one_winner(afw):
    from concurrent.futures import ThreadPoolExecutor

    from services.langgraph.agency.project_os.vocabulary import ActivityType
    from services.langgraph.persistence import operating_framework as store

    plan_id = instantiate(create_project())["plan"]["plan_id"]
    current = version(plan_id, "AGM-01-001")

    def write(n: int):
        try:
            return store.update_task(plan_id, "AGM-01-001", expected_version=current, actor=f"writer-{n}",
                                     changes={"status_reason": f"writer {n}"}, event_type=ActivityType.COMMENT,
                                     event_payload={"kind": "agency_framework.test_write"})
        except store.StaleTaskVersion as exc:
            return exc

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(8)))
    winners = [r for r in results if isinstance(r, dict)]
    assert len(winners) == 1 and sum(isinstance(r, store.StaleTaskVersion) for r in results) == 7
    final = task(plan_id, "AGM-01-001")["instance"]
    assert final["version"] == current + 1 and final["status_reason"] == winners[0]["status_reason"]
    writes = [e for e in store.framework_events(final["project_id"], plan_id) if e["payload"].get("kind") == "agency_framework.test_write"]
    assert len(writes) == 1  # the losers appended nothing


def test_a_failed_audit_append_rolls_back_the_task_write_and_a_retry_recovers(afw, monkeypatch):
    from services.langgraph.persistence import operating_framework as store

    plan_id = instantiate(create_project())["plan"]["plan_id"]
    apply(plan_id, [("AGM-01-001", "REQUIRED", "core")])
    before = task(plan_id, "AGM-01-001")["instance"]
    real_append = store._append_event

    def crash(*args, **kwargs):
        raise RuntimeError("simulated crash between the row write and its event")

    monkeypatch.setattr(store, "_append_event", crash)
    with pytest.raises(RuntimeError):
        client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-01-001/transition",
                    json={"target": "READY", "expected_version": before["version"]}, headers=key())
    after = task(plan_id, "AGM-01-001")["instance"]
    assert (after["state"], after["version"]) == (before["state"], before["version"])  # no partial commit
    monkeypatch.setattr(store, "_append_event", real_append)
    ok(move(plan_id, "AGM-01-001", "READY"))  # the same expected version still applies after the crash
    assert task(plan_id, "AGM-01-001")["instance"]["state"] == "READY"


def test_injected_authority_fields_are_refused_not_ignored(afw):
    plan_id = instantiate(create_project())["plan"]["plan_id"]
    apply(plan_id, [("AGM-01-001", "REQUIRED", "core")])
    current = version(plan_id, "AGM-01-001")
    base = f"/agency-framework/plans/{plan_id}/tasks/AGM-01-001"
    attempts = [
        (f"{base}/transition", {"target": "READY", "expected_version": current, "verified_by": REVIEWER}),
        (f"{base}/transition", {"target": "READY", "expected_version": current, "approval_ref": "forged"}),
        (f"{base}/verify", {"expected_version": current, "verifier": REVIEWER}),
        (f"{base}/settle", {"expected_version": current, "decision": "approve"}),
    ]
    for path, body in attempts:
        response = client.post(path, json=body, headers=key())
        assert response.status_code == 422, (path, response.text)
    assert task(plan_id, "AGM-01-001")["instance"]["version"] == current
    # The gate route reads no body at all: a claimed status cannot move it past its own evaluation.
    gate = client.post(f"/agency-framework/plans/{plan_id}/gates/01_DISCOVERY/request-approval",
                       json={"status": "PASSED"}, headers=key())
    assert gate.status_code == 409 and gate.json()["error"]["code"] == "GATE_NOT_READY"


def test_unreviewed_or_stale_evidence_fails_verification_and_the_failure_is_recorded(afw, monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    apply(plan_id, [("AGM-01-001", "REQUIRED", "core"), ("AGM-01-002", "REQUIRED", "core")])
    unreviewed = evidence(monkeypatch, project_id, "Draft notes (fictional). Several customers said that delivery delays were the main reason they stopped ordering.", promote=False)
    old = evidence(monkeypatch, project_id, "Old social audit (fictional). Followers engaged with short video posts far more often than with static images.", domain="social",
                   fetched_at="2024-01-01T00:00:00+00:00")
    for task_id, ref in (("AGM-01-001", unreviewed), ("AGM-01-002", old)):
        ok(move(plan_id, task_id, "READY"))
        ok(move(plan_id, task_id, "ACTIVE"))
        ok(set_refs(plan_id, task_id, evidence=[ref]))
        ok(move(plan_id, task_id, "IN_REVIEW"))
        response = verify(monkeypatch, plan_id, task_id)
        assert response.status_code == 422 and response.json()["error"]["code"] == "VERIFICATION_FAILED"
        detail = task(plan_id, task_id)["instance"]
        assert detail["state"] == "IN_REVIEW" and detail["verification"]["result"] == "FAILED"
    assert task(plan_id, "AGM-01-001")["instance"]["verification"]["checks"][0]["status"] == "EVIDENCE_NOT_REVIEWED"
    assert task(plan_id, "AGM-01-002")["instance"]["verification"]["checks"][0]["status"] == "EVIDENCE_STALE"


def test_a_changed_artifact_invalidates_verified_work_and_stales_its_approval(afw, monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    apply(plan_id, [("AGM-08-001", "REQUIRED", "identity")])
    ref = artifact(project_id, "identity-system", "design_system_spec", "Primary mark, clear space 1x, palette roles.")
    ok(move(plan_id, "AGM-08-001", "READY"))
    ok(move(plan_id, "AGM-08-001", "ACTIVE"))
    ok(set_refs(plan_id, "AGM-08-001", artifacts=[ref]))
    ok(move(plan_id, "AGM-08-001", "IN_REVIEW"))
    ok(verify(monkeypatch, plan_id, "AGM-08-001"))
    requested = ok(client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-08-001/request-approval",
                               json={"expected_version": version(plan_id, "AGM-08-001")}, headers=key()))
    revise(project_id, ref, "Primary mark, clear space 2x, palette roles.")
    out = ok(client.post(f"/agency-framework/plans/{plan_id}/revalidate", headers=key()))
    assert [i["task_id"] for i in out["invalidated"]] == ["AGM-08-001"]
    assert task(plan_id, "AGM-08-001")["instance"]["state"] == "INVALIDATED"
    approval = client.get("/approvals").json()
    assert all(a["approval_id"] != requested["approval_ref"] for a in approval)  # no longer pending
    response = decide(monkeypatch, requested["approval_ref"])
    assert response.status_code == 409  # stale approvals cannot be decided


def test_approval_on_changed_proof_is_refused_at_settle(afw, monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    apply(plan_id, [("AGM-08-002", "REQUIRED", "identity")])
    ref = artifact(project_id, "logo-spec", "design_system_spec", "Logo lockups: horizontal and stacked.")
    ok(move(plan_id, "AGM-08-002", "READY"))
    ok(move(plan_id, "AGM-08-002", "ACTIVE"))
    ok(set_refs(plan_id, "AGM-08-002", artifacts=[ref]))
    ok(move(plan_id, "AGM-08-002", "IN_REVIEW"))
    ok(verify(monkeypatch, plan_id, "AGM-08-002"))
    requested = ok(client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-08-002/request-approval",
                               json={"expected_version": version(plan_id, "AGM-08-002")}, headers=key()))
    ok(decide(monkeypatch, requested["approval_ref"]))
    revise(project_id, ref, "Logo lockups: horizontal only.")
    response = client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-08-002/settle",
                           json={"expected_version": version(plan_id, "AGM-08-002")}, headers=key())
    assert response.status_code == 409 and response.json()["error"]["code"] == "APPROVAL_SUBJECT_STALE"
    assert task(plan_id, "AGM-08-002")["instance"]["state"] == "INVALIDATED"


def test_decisions_need_alternatives_and_a_selected_option_among_them(afw):
    plan_id = instantiate(create_project())["plan"]["plan_id"]
    response = client.post(f"/agency-framework/plans/{plan_id}/decisions", json={
        "question": "Lead offer?", "alternatives": ["A", "B"], "selected_option": "C"}, headers=key())
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_DECISION"
    ref = decision(plan_id, "Lead offer?", ["Bundle", "Single SKU"], "Bundle")
    assert ref.startswith("decision:")


# ------------------------------------------------------------------------------ stage gates


def _scope_gate_to(plan_id: str, gate_tasks: list[str], gate_modules: list[str]) -> None:
    catalog = load_catalog()
    decisions = []
    for t in catalog.tasks:
        if t.module_id in gate_modules:
            decisions.append((t.task_id, "REQUIRED" if t.task_id in gate_tasks else "NOT_APPLICABLE", "scoped for test"))
    apply(plan_id, decisions)


def test_stage_gate_passes_only_through_an_approval_bound_to_its_evaluation_and_in_order(afw, monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    _scope_gate_to(plan_id, ["AGM-01-001", "AGM-02-001"], ["AGM-01", "AGM-02", "AGM-03", "AGM-04"])
    gates = ok(client.get(f"/agency-framework/plans/{plan_id}/gates"))["gates"]
    assert gates[0]["status"] == "BLOCKED" and {u["task_id"] for u in gates[0]["unmet"]} == {"AGM-01-001", "AGM-02-001"}
    response = client.post(f"/agency-framework/plans/{plan_id}/gates/01_DISCOVERY/request-approval", headers=key())
    assert response.status_code == 409 and response.json()["error"]["code"] == "GATE_NOT_READY"
    complete_task(monkeypatch, plan_id, "AGM-01-001",
                  evidence=[evidence(monkeypatch, project_id, "Brief (fictional). The owner wants to win twenty new wholesale accounts across Europe within the next year.")])
    complete_task(monkeypatch, plan_id, "AGM-02-001",
                  evidence=[evidence(monkeypatch, project_id, "Category scope (fictional). The business competes in specialty loose-leaf tea and sells only inside the European Union.")])
    gate = ok(client.get(f"/agency-framework/plans/{plan_id}/gates"))["gates"][0]
    assert gate["status"] == "NEEDS_HUMAN" and gate["synthetic_only"] is True
    # Gate 2 cannot be requested before gate 1 passes.
    response = client.post(f"/agency-framework/plans/{plan_id}/gates/02_STRATEGY/request-approval", headers=key())
    assert response.status_code == 409 and response.json()["error"]["code"] == "PREDECESSOR_GATE_NOT_PASSED"
    requested = ok(client.post(f"/agency-framework/plans/{plan_id}/gates/01_DISCOVERY/request-approval", headers=key()))
    assert ok(client.get(f"/agency-framework/plans/{plan_id}/gates"))["gates"][0]["status"] == "APPROVAL_PENDING"
    ok(decide(monkeypatch, requested["approval"]["approval_id"]))
    assert ok(client.get(f"/agency-framework/plans/{plan_id}/gates"))["gates"][0]["status"] == "PASSED"
    view = ok(client.get(f"/agency-framework/plans/{plan_id}"))
    assert view["readiness"]["release_eligible"] is False and view["readiness"]["synthetic_evidence_present"] is True


def test_gate_approval_goes_stale_when_its_evidence_changes(afw, monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    _scope_gate_to(plan_id, ["AGM-04-001"], ["AGM-01", "AGM-02", "AGM-03", "AGM-04"])
    source = evidence(monkeypatch, project_id, "Competitor list (fictional). Alpha Teas currently leads the category "
                                               "on price while Beta Leaf leads on brand recognition.")
    sheet = artifact(project_id, "competitor-set", "market_analysis", "Competitors (fictional): Alpha Teas, Beta Leaf.")
    complete_task(monkeypatch, plan_id, "AGM-04-001", evidence=[source], artifacts=[sheet])
    requested = ok(client.post(f"/agency-framework/plans/{plan_id}/gates/01_DISCOVERY/request-approval", headers=key()))
    ok(decide(monkeypatch, requested["approval"]["approval_id"]))
    assert ok(client.get(f"/agency-framework/plans/{plan_id}/gates"))["gates"][0]["status"] == "PASSED"
    # APPROVED is terminal for manual moves: nobody can quietly reopen approved work.
    response = move(plan_id, "AGM-04-001", "BLOCKED", "client asked for a wider set")
    assert response.status_code == 409
    # A changed artifact invalidates the approved task, and the gate drops back.
    sheet_v2 = revise(project_id, sheet, "Competitors (fictional): Alpha Teas, Beta Leaf, Gamma Brew.")
    out = ok(client.post(f"/agency-framework/plans/{plan_id}/revalidate", headers=key()))
    assert [i["task_id"] for i in out["invalidated"]] == ["AGM-04-001"]
    assert ok(client.get(f"/agency-framework/plans/{plan_id}/gates"))["gates"][0]["status"] == "BLOCKED"
    # Rework and re-approval: the old gate approval no longer matches the new evaluation.
    ok(move(plan_id, "AGM-04-001", "ACTIVE"))
    ok(set_refs(plan_id, "AGM-04-001", evidence=[source], artifacts=[sheet_v2]))
    ok(move(plan_id, "AGM-04-001", "IN_REVIEW"))
    ok(verify(monkeypatch, plan_id, "AGM-04-001"))
    again = ok(client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-04-001/request-approval",
                           json={"expected_version": version(plan_id, "AGM-04-001")}, headers=key()))
    ok(decide(monkeypatch, again["approval_ref"]))
    ok(client.post(f"/agency-framework/plans/{plan_id}/tasks/AGM-04-001/settle",
                   json={"expected_version": version(plan_id, "AGM-04-001")}, headers=key()))
    gate = ok(client.get(f"/agency-framework/plans/{plan_id}/gates"))["gates"][0]
    assert gate["status"] == "STALE"
    ok(client.post(f"/agency-framework/plans/{plan_id}/gates/01_DISCOVERY/request-approval", headers=key()))
    assert ok(client.get(f"/agency-framework/plans/{plan_id}/gates"))["gates"][0]["status"] == "APPROVAL_PENDING"


# ------------------------------------------------------------------------------ tenancy


def test_plans_are_invisible_to_another_tenant_and_to_projects_out_of_scope(afw, monkeypatch):
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    as_user(monkeypatch, "intruder", "admin", tenant="tenant-other")
    for path in (f"/agency-framework/plans/{plan_id}", f"/agency-framework/plans/{plan_id}/tasks",
                 f"/agency-framework/plans/{plan_id}/tasks/AGM-01-001", f"/agency-framework/plans/{plan_id}/gates",
                 f"/agency-framework/plans/{plan_id}/audit", f"/agency-framework/plans/{plan_id}/metrics",
                 f"/agency-framework/plans/{plan_id}/assurance"):
        response = client.get(path)
        assert response.status_code == 404 and response.json()["error"]["code"] == "PLAN_NOT_FOUND", path
    response = client.post(f"/agency-framework/plans/{plan_id}/applicability",
                           json={"decisions": [{"task_id": "AGM-01-001", "applicability": "REQUIRED", "reason": "x" * 5}]},
                           headers=key())
    assert response.status_code == 404
    as_user(monkeypatch, AUTHOR, projects="some-other-project")
    assert client.get(f"/agency-framework/plans/{plan_id}").status_code == 404


def test_idempotent_writes_replay_and_reject_a_reused_key(afw):
    plan_id = instantiate(create_project())["plan"]["plan_id"]
    headers = key()
    body = {"decisions": [{"task_id": "AGM-01-001", "applicability": "REQUIRED", "reason": "core work"}]}
    first = ok(client.post(f"/agency-framework/plans/{plan_id}/applicability", json=body, headers=headers))
    second = ok(client.post(f"/agency-framework/plans/{plan_id}/applicability", json=body, headers=headers))
    assert first == second and task(plan_id, "AGM-01-001")["instance"]["version"] == 1
    body["decisions"][0]["reason"] = "different"
    response = client.post(f"/agency-framework/plans/{plan_id}/applicability", json=body, headers=headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_no_external_effect_counters_move(afw, monkeypatch):
    from services.langgraph.persistence.database import table, transaction

    def counts():
        with transaction() as db:
            out = {}
            for name in ("action_sandbox_effects", "outbox"):
                try:
                    out[name] = db.execute(f"SELECT COUNT(*) AS n FROM {table(name)}").fetchone()["n"]
                except Exception:  # noqa: BLE001 - absent table counts as zero
                    out[name] = 0
        return out

    before = counts()
    project_id = create_project()
    plan_id = instantiate(project_id)["plan"]["plan_id"]
    apply(plan_id, [("AGM-13-001", "REQUIRED", "social"), ("AGM-14-001", "REQUIRED", "paid"), ("AGM-15-001", "REQUIRED", "crm")])
    plan_ref = artifact(project_id, "social-plan", "campaign_package", "Organic plan (fictional): two posts a week.")
    complete_task(monkeypatch, plan_id, "AGM-13-001", artifacts=[plan_ref])
    assert counts() == before
    assert ok(client.get(f"/agency-framework/plans/{plan_id}"))["readiness"]["externally_executed"] is False
    assert REVIEWER and VERIFIER
    _ = copy
