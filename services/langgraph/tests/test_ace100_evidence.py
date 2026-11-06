"""ACE v100 exact-SHA evidence collection and the fail-closed release status."""

from __future__ import annotations

import json

import pytest

from services.langgraph.agency.ace_evidence import (
    CHECK_GATES,
    NOT_PROVEN_BY_CI,
    CollectedGates,
    OperationalEvidence,
    gate_results_from_check_runs,
    production_status,
)
from services.langgraph.agency.ace_release import REQUIRED_GATES, GateResult, PromotionDecision, ReleaseStage

SHA = "a" * 40
OTHER = "b" * 40


def _runs(sha=SHA, conclusion="success", **override):
    return [{"id": i, "name": name, "head_sha": sha, "status": "completed", "conclusion": override.get(name, conclusion),
             "completed_at": "2026-10-15T00:00:00Z", "html_url": f"https://ci.example/{i}"}
            for i, name in enumerate(CHECK_GATES)]


def _gates(collected):
    return {g.gate: g.status for g in collected.gates}


def test_green_exact_sha_ci_is_merged_but_never_production_verified():
    collected = gate_results_from_check_runs(_runs(), sha=SHA)
    gates = _gates(collected)
    assert all(gates[g] == "UNVERIFIED" for g in NOT_PROVEN_BY_CI)
    assert all(gates[g] == "PASS" for g in REQUIRED_GATES - NOT_PROVEN_BY_CI)
    status = production_status(collected=collected, merged_into_default=True)
    assert {k: status[k] for k in ("production_integration", "live_effects", "release_authorization", "overall_status",
                                   "release_permitted")} == {
        "production_integration": "UNVERIFIED", "live_effects": "NOT_VERIFIED", "release_authorization": "NOT_VERIFIED",
        "overall_status": "MERGED_NOT_PRODUCTION_VERIFIED", "release_permitted": False}
    assert any("telemetry" in g for g in status["unresolved_gaps"])
    assert production_status(collected=collected, merged_into_default=False)["overall_status"] == "CI_GREEN_NOT_MERGED"


def test_ci_evidence_from_another_sha_is_rejected_not_counted():
    runs = _runs()
    runs[0]["head_sha"] = OTHER  # the backend job ran on a different commit
    collected = gate_results_from_check_runs(runs, sha=SHA)
    assert [p.problem for p in collected.problems] == ["SHA_MISMATCH"]
    assert _gates(collected)["backend_sqlite"] == "UNVERIFIED"
    status = production_status(collected=collected, merged_into_default=True)
    assert status["overall_status"] == "CI_UNVERIFIED" and status["release_permitted"] is False


def test_failed_job_fails_every_gate_it_proves():
    collected = gate_results_from_check_runs(_runs(**{"Frontend (contracts + typecheck + test + build)": "failure"}), sha=SHA)
    gates = _gates(collected)
    assert gates["frontend_build"] == gates["schema_parity"] == gates["dependency_consistency"] == "FAIL"
    assert production_status(collected=collected, merged_into_default=True)["overall_status"] == "CI_FAILING"


def test_the_latest_attempt_of_a_rerun_decides():
    runs = _runs()
    retry = dict(runs[0], id=99, conclusion="failure", completed_at="2026-10-15T01:00:00Z")
    assert _gates(gate_results_from_check_runs(runs + [retry], sha=SHA))["backend_sqlite"] == "FAIL"
    first_failed = dict(runs[0], id=98, conclusion="failure", completed_at="2026-10-14T23:00:00Z")
    assert _gates(gate_results_from_check_runs(runs + [first_failed], sha=SHA))["backend_sqlite"] == "PASS"


def test_unfinished_or_missing_runs_are_unverified():
    runs = _runs()
    runs[1]["status"], runs[1]["conclusion"] = "in_progress", None
    collected = gate_results_from_check_runs(runs[:-1], sha=SHA)  # dependency audit missing entirely
    gates = _gates(collected)
    assert gates["backend_postgresql"] == "UNVERIFIED" and gates["dependency_audit"] == "UNVERIFIED"
    assert "NOT_COMPLETED" in [p.problem for p in collected.problems]


@pytest.mark.parametrize("bad", ["", "abc", "A" * 40, "g" * 40])
def test_a_full_lowercase_sha_is_required(bad):
    with pytest.raises(ValueError):
        gate_results_from_check_runs(_runs(), sha=bad)


def _all_pass(sha=SHA):
    return CollectedGates(commit_sha=sha, problems=(), gates=tuple(
        GateResult(gate=g, status="PASS", source_commit=sha, evidence_ref="test") for g in sorted(REQUIRED_GATES)))


def _decision(sha=SHA, authorized=True):
    return PromotionDecision(authorized=authorized, stage=ReleaseStage.CANARY, commit_sha=sha, reasons=(),
                             evidence_sha256="0" * 64)


FULL = OperationalEvidence(telemetry_ingestion_verified=True, provider_effects_reconciled=True, rollback_drill_verified=True,
                           canary_verified_action_classes=("R3",), approved_action_classes=("R3",), audit_chain_intact=True)


def test_only_complete_evidence_and_matching_approval_permit_release():
    ok = production_status(collected=_all_pass(), merged_into_default=True, operational=FULL, promotion=_decision())
    assert ok["release_permitted"] is True and ok["overall_status"] == "PRODUCTION_VERIFIED" and ok["unresolved_gaps"] == []

    def permitted(**kw):
        args = {"collected": _all_pass(), "merged_into_default": True, "operational": FULL, "promotion": _decision()}
        args.update(kw)
        return production_status(**args)["release_permitted"]

    assert not permitted(promotion=_decision(sha=OTHER))  # approval for another artifact
    assert not permitted(promotion=_decision(authorized=False))
    assert not permitted(promotion=None)
    assert not permitted(live_effects_enabled=True)  # live switched on before approval
    for missing in ("telemetry_ingestion_verified", "provider_effects_reconciled", "rollback_drill_verified"):
        assert not permitted(operational=FULL.model_copy(update={missing: False}))
    assert not permitted(operational=FULL.model_copy(update={"audit_chain_intact": None}))
    assert not permitted(operational=FULL.model_copy(update={"approved_action_classes": ("R3", "R4")}))  # R4 never canaried


def test_collector_script_writes_unsigned_fail_closed_evidence(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "collect_release_evidence", Path(__file__).resolve().parents[3] / "scripts" / "collect_release_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runs = tmp_path / "runs.json"
    runs.write_text(json.dumps({"total_count": 5, "check_runs": _runs()}))
    out = tmp_path / "evidence.json"
    assert module.main(["--sha", SHA, "--check-runs", str(runs), "--merged", "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["signed"] is False and report["commit_sha"] == SHA
    assert report["status"]["release_permitted"] is False
    assert report["status"]["overall_status"] == "MERGED_NOT_PRODUCTION_VERIFIED"
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert module.main(["--sha", SHA]) == 2  # no input and no token: refuse rather than guess
