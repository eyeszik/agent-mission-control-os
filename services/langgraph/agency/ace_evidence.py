"""ACE v100 exact-SHA release evidence: check runs in, fail-closed status out.

Pure functions: no network, no deployment, no authority. A script or CI job
fetches the GitHub check runs for one commit and passes them here.

* ``gate_results_from_check_runs`` turns check runs into ``ace_release.GateResult``
  rows for the gates a CI job proves on its own. Every run must report the SHA
  under review; a run for another SHA is rejected, never counted (edge case 10).
  When a check was re-run, its latest attempt decides. Gates that no CI job
  proves on its own (independent fault injection, security review, evidence
  integrity) stay ``UNVERIFIED``.
* ``production_status`` compiles the release decision. Each field leaves its
  default only when the supplied evidence supports the transition. Missing
  evidence never counts as passing.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, Literal, Mapping, Optional

from pydantic import Field

from services.langgraph.agency.ace_controls import StrictModel
from services.langgraph.agency.ace_release import REQUIRED_GATES, GateResult, PromotionDecision

SHA_RE = re.compile(r"^[a-f0-9]{40}$")

# Each CI job in .github/workflows/ci.yml and the release gates its success proves.
# schema_parity needs both the backend contract tests and the frontend Zod tests;
# dependency_consistency needs both the frozen lockfile install and `pip check`.
CHECK_GATES: dict[str, tuple[str, ...]] = {
    "Backend (compile + invariants + pytest)": ("backend_sqlite", "schema_parity", "dependency_consistency"),
    "Backend on PostgreSQL (migrations + pytest)": ("backend_postgresql",),
    "Frontend (contracts + typecheck + test + build)": ("frontend_build", "schema_parity", "dependency_consistency"),
    "Browser E2E (local degraded HITL)": ("browser_e2e",),
    "Dependency audit": ("dependency_audit",),
}
NOT_PROVEN_BY_CI = frozenset({"fault_injection", "security_regression", "evidence_integrity"})


class CheckRunProblem(StrictModel):
    check: str
    problem: Literal["SHA_MISMATCH", "NOT_COMPLETED", "UNMAPPED"]
    detail: str = ""


class CollectedGates(StrictModel):
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    gates: tuple[GateResult, ...]
    problems: tuple[CheckRunProblem, ...]


def _latest(runs: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    return max(runs, key=lambda r: (str(r.get("completed_at") or ""), str(r.get("started_at") or ""), int(r.get("id") or 0)))


def gate_results_from_check_runs(check_runs: Iterable[Mapping[str, Any]], *, sha: str) -> CollectedGates:
    if not SHA_RE.match(sha or ""):
        raise ValueError("sha must be a full 40-character lowercase commit SHA")
    problems: list[CheckRunProblem] = []
    by_name: dict[str, list[Mapping[str, Any]]] = {}
    for run in check_runs:
        name = str(run.get("name") or "")
        if run.get("head_sha") != sha:
            problems.append(CheckRunProblem(check=name, problem="SHA_MISMATCH",
                                            detail=f"run reports {run.get('head_sha')!r}, not the commit under review"))
            continue
        if name not in CHECK_GATES:
            problems.append(CheckRunProblem(check=name, problem="UNMAPPED"))
            continue
        by_name.setdefault(name, []).append(run)

    # A gate passes only if every job that proves it passed on this SHA.
    verdicts: dict[str, list[tuple[str, str]]] = {g: [] for g in REQUIRED_GATES}
    for name, gates in CHECK_GATES.items():
        runs = by_name.get(name)
        if not runs:
            status, ref = "UNVERIFIED", f"no '{name}' check run for {sha}"
        else:
            run = _latest(runs)
            ref = str(run.get("html_url") or run.get("details_url") or name)
            if run.get("status") != "completed":
                problems.append(CheckRunProblem(check=name, problem="NOT_COMPLETED", detail=str(run.get("status"))))
                status = "UNVERIFIED"
            else:
                status = "PASS" if run.get("conclusion") == "success" else "FAIL"
        for gate in gates:
            verdicts[gate].append((status, ref))

    results = []
    for gate in sorted(REQUIRED_GATES):
        if gate in NOT_PROVEN_BY_CI or not verdicts[gate]:
            results.append(GateResult(gate=gate, status="UNVERIFIED", source_commit=sha,
                                      evidence_ref="no independent evidence for this gate; CI success alone does not prove it"))
            continue
        statuses = [s for s, _ in verdicts[gate]]
        status = "FAIL" if "FAIL" in statuses else "UNVERIFIED" if "UNVERIFIED" in statuses else "PASS"
        results.append(GateResult(gate=gate, status=status, source_commit=sha,
                                  evidence_ref=" ; ".join(ref for _, ref in verdicts[gate])[:2048]))
    return CollectedGates(commit_sha=sha, gates=tuple(results), problems=tuple(problems))


class OperationalEvidence(StrictModel):
    """Facts about the target environment. Each defaults to unproven."""

    telemetry_ingestion_verified: bool = False
    provider_effects_reconciled: bool = False
    rollback_drill_verified: bool = False
    canary_verified_action_classes: tuple[str, ...] = ()
    approved_action_classes: tuple[str, ...] = ()
    audit_chain_intact: Optional[bool] = None


def production_status(*, collected: CollectedGates, merged_into_default: bool,
                      operational: OperationalEvidence = OperationalEvidence(),
                      promotion: Optional[PromotionDecision] = None,
                      live_effects_enabled: bool = False, now: Optional[datetime] = None) -> dict[str, Any]:
    """The release decision, computed only from supplied evidence.

    ProductionVerified = all mandatory gates PASS for the exact SHA, provider
    effects reconciled, audit chain intact, telemetry verified in the target,
    rollback verified, and a valid signed human approval (``promotion``)."""
    gates = {g.gate: g.status for g in collected.gates}
    ci_gates = {g for gates_ in CHECK_GATES.values() for g in gates_}
    ci_failed = sorted(g for g in ci_gates if gates.get(g) == "FAIL")
    ci_green = all(gates.get(g) == "PASS" for g in ci_gates) and not any(
        p.problem == "SHA_MISMATCH" for p in collected.problems)
    all_gates = all(gates.get(g) == "PASS" for g in REQUIRED_GATES)

    canary_ok = bool(operational.approved_action_classes) and set(operational.approved_action_classes) <= set(
        operational.canary_verified_action_classes)
    integration_ok = (all_gates and operational.telemetry_ingestion_verified and operational.provider_effects_reconciled
                      and operational.rollback_drill_verified and operational.audit_chain_intact is True)
    authorized = bool(promotion and promotion.authorized and promotion.commit_sha == collected.commit_sha)
    release_permitted = integration_ok and canary_ok and authorized and not live_effects_enabled

    gaps = [f"gate {g}: {gates.get(g, 'UNVERIFIED')}" for g in sorted(REQUIRED_GATES) if gates.get(g) != "PASS"]
    gaps += [f"check run {p.check}: {p.problem}" for p in collected.problems if p.problem != "UNMAPPED"]
    if not operational.telemetry_ingestion_verified:
        gaps.append("telemetry ingestion not verified in the target environment")
    if not operational.provider_effects_reconciled:
        gaps.append("provider effects not reconciled against real provider receipts")
    if not operational.rollback_drill_verified:
        gaps.append("rollback drill not verified")
    if operational.audit_chain_intact is not True:
        gaps.append("audit chain integrity not verified for the release")
    if not canary_ok:
        gaps.append("no verified live canary for every approved action class")
    if not authorized:
        gaps.append("no valid signed human approval for this exact SHA")

    if release_permitted:
        overall = "PRODUCTION_VERIFIED"
    elif ci_failed:
        overall = "CI_FAILING"
    elif not ci_green:
        overall = "CI_UNVERIFIED"
    elif merged_into_default:
        overall = "MERGED_NOT_PRODUCTION_VERIFIED"
    else:
        overall = "CI_GREEN_NOT_MERGED"
    return {
        "production_integration": "VERIFIED" if integration_ok else "UNVERIFIED",
        "live_effects": "VERIFIED" if canary_ok else "NOT_VERIFIED",
        "release_authorization": "VERIFIED" if authorized else "NOT_VERIFIED",
        "overall_status": overall,
        "release_permitted": release_permitted,
        "commit_sha": collected.commit_sha,
        "ci": dict(sorted(gates.items())),
        "unresolved_gaps": gaps,
        **({"evaluated_at": now.isoformat()} if now else {}),
    }


__all__ = ["CHECK_GATES", "CollectedGates", "NOT_PROVEN_BY_CI", "OperationalEvidence", "gate_results_from_check_runs",
           "production_status"]
