"""Pure rules: progress roll-ups and stage-gate evaluation from task instances.

No I/O. ``evaluate_gate`` says what the tasks alone allow; the service overlays
the gate's approval (an existing ``approvals`` row bound to ``evaluation_hash``)
and the predecessor gates. Progress counts required, verified work against
required work; with no required tasks the percentage is ``NOT_MEASURED``, never
100%. Catalog totals are reported next to it so scoping down stays visible.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from services.langgraph.agency.execution.canonical import canonical_hash

from .catalog import DISCIPLINES, STAGE_GATES, Catalog
from .contracts import Applicability, EvidenceOrigin, GateStatus, TaskState

NOT_MEASURED = "NOT_MEASURED"
_IN_PROGRESS = {TaskState.READY.value, TaskState.ACTIVE.value, TaskState.IN_REVIEW.value}
_DONE = {TaskState.VERIFIED.value, TaskState.APPROVED.value}
_STOPPED = {TaskState.BLOCKED.value, TaskState.INVALIDATED.value}


def counts(tasks: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    c = {"defined": 0, "unassessed": 0, "required": 0, "conditional": 0, "not_applicable": 0, "applicable": 0,
         "backlog": 0, "in_progress": 0, "in_review": 0, "verified": 0, "approved": 0, "blocked": 0,
         "required_verified": 0}
    for t in tasks:
        c["defined"] += 1
        app, state = t["applicability"], t["state"]
        if app == Applicability.UNASSESSED.value:
            c["unassessed"] += 1
        elif app == Applicability.REQUIRED.value:
            c["required"] += 1
        elif app == Applicability.CONDITIONAL.value:
            c["conditional"] += 1
        else:
            c["not_applicable"] += 1
        if app in (Applicability.REQUIRED.value, Applicability.CONDITIONAL.value):
            c["applicable"] += 1
        if state == TaskState.BACKLOG.value:
            c["backlog"] += 1
        elif state in _IN_PROGRESS:
            c["in_progress"] += 1
        if state == TaskState.IN_REVIEW.value:
            c["in_review"] += 1
        if state in _DONE:
            c["verified"] += 1
            if app == Applicability.REQUIRED.value:
                c["required_verified"] += 1
        if state == TaskState.APPROVED.value:
            c["approved"] += 1
        if state in _STOPPED:
            c["blocked"] += 1
    c["required_verified_ratio"] = (round(c["required_verified"] / c["required"], 4) if c["required"] else NOT_MEASURED)
    return c


def progress(catalog: Catalog, tasks: list[Mapping[str, Any]]) -> dict[str, Any]:
    defs = {t.task_id: t for t in catalog.tasks}
    by_module: dict[str, list] = {m.module_id: [] for m in catalog.modules}
    by_gate: dict[str, list] = {g: [] for g in STAGE_GATES}
    by_discipline: dict[str, list] = {d: [] for d in DISCIPLINES}
    for t in tasks:
        d = defs[t["task_id"]]
        by_module[d.module_id].append(t)
        by_gate[d.stage_gate].append(t)
        by_discipline[d.phase].append(t)
    return {
        "overall": counts(tasks),
        "catalog_totals": catalog.summary()["per_stage_gate"] | {"total": len(catalog.tasks)},
        "modules": {k: counts(v) for k, v in by_module.items()},
        "stage_gates": {k: counts(v) for k, v in by_gate.items()},
        "disciplines": {k: counts(v) for k, v in by_discipline.items()},
    }


def task_proof_hash(plan: Mapping[str, Any], task: Mapping[str, Any], checks: list[Mapping[str, Any]]) -> str:
    """What an approval of a task binds to: the plan, the catalog pin, the task and
    each ref with the exact content hash it resolved to at verification."""
    return canonical_hash({
        "plan_id": plan["plan_id"], "catalog_sha256": plan["catalog_sha256"], "task_id": task["task_id"],
        "applicability": task["applicability"],
        "refs": sorted(({"ref": c["ref"], "content_hash": c.get("content_hash")} for c in checks), key=lambda r: r["ref"]),
    })


def evaluate_gate(plan: Mapping[str, Any], gate: str, tasks: list[Mapping[str, Any]]) -> dict[str, Any]:
    in_gate = sorted((t for t in tasks if t["stage_gate"] == gate), key=lambda t: t["task_id"])
    unassessed = [t["task_id"] for t in in_gate if t["applicability"] == Applicability.UNASSESSED.value]
    required = [t for t in in_gate if t["applicability"] == Applicability.REQUIRED.value]
    unmet = []
    origins: set[str] = set()
    for t in required:
        verification = t.get("verification") or {}
        if t["state"] not in _DONE:
            unmet.append({"task_id": t["task_id"], "state": t["state"], "reason": t.get("status_reason") or "not verified"})
        origins.update(c.get("origin") for c in verification.get("checks", []) if c.get("origin"))
    proof = [{"task_id": t["task_id"], "state": t["state"],
              "proof_hash": (t.get("verification") or {}).get("proof_hash")} for t in required]
    evaluation_hash = canonical_hash({"plan_id": plan["plan_id"], "catalog_sha256": plan["catalog_sha256"],
                                      "stage_gate": gate, "required": proof})
    if unassessed:
        status = GateStatus.NOT_ASSESSED.value
    elif unmet:
        status = GateStatus.BLOCKED.value
    else:
        status = GateStatus.NEEDS_HUMAN.value
    synthetic_only = bool(origins) and origins <= {EvidenceOrigin.SYNTHETIC.value, EvidenceOrigin.INTERNAL_RECORD.value} \
        and EvidenceOrigin.SYNTHETIC.value in origins
    return {
        "stage_gate": gate,
        "status": status,
        "evaluation_hash": evaluation_hash,
        "required_count": len(required),
        "unassessed": unassessed,
        "unmet": unmet,
        "evidence_origins": sorted(origins),
        "synthetic_only": synthetic_only,
        "no_required_tasks": not required and not unassessed,
    }


def overlay_gate_approval(evaluation: dict[str, Any], approvals: list[Mapping[str, Any]],
                          predecessor_passed: bool) -> dict[str, Any]:
    """Combine the task evaluation with the gate's approval rows and the gate order."""
    out = dict(evaluation)
    current = [a for a in approvals if a.get("subject_hash") == evaluation["evaluation_hash"]]
    approved = [a for a in current if a.get("status") == "resolved" and a.get("decision") == "approve"]
    pending = [a for a in current if a.get("status") == "pending"]
    older_approved = [a for a in approvals if a.get("status") == "resolved" and a.get("decision") == "approve"
                      and a.get("subject_hash") != evaluation["evaluation_hash"]]
    chosen = approved or pending
    out["approval_id"] = chosen[0].get("approval_id") if chosen else None
    reasons: list[str] = []
    if evaluation["status"] == GateStatus.NEEDS_HUMAN.value:
        if approved:
            out["status"] = GateStatus.PASSED.value
        elif pending:
            out["status"] = GateStatus.APPROVAL_PENDING.value
        elif older_approved:
            out["status"] = GateStatus.STALE.value
            reasons.append("an earlier gate approval no longer matches the current evidence")
    if out["status"] == GateStatus.PASSED.value and not predecessor_passed:
        out["status"] = GateStatus.BLOCKED.value
        reasons.append("PREDECESSOR_GATE_NOT_PASSED")
    out["reasons"] = reasons
    return out


def predecessor(gate: str) -> str | None:
    index = STAGE_GATES.index(gate)
    return STAGE_GATES[index - 1] if index else None


__all__ = ["NOT_MEASURED", "counts", "evaluate_gate", "overlay_gate_approval", "predecessor", "progress",
           "task_proof_hash"]
