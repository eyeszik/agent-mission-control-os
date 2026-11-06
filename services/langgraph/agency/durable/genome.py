"""MissionGenome: one versioned, strictly validated description of a mission before any write.

``compile_genome`` applies the admission rules:

* project not bound to exactly one accessible project -> PROJECT_AMBIGUOUS (stop before writes)
* a critical unknown                                  -> HUMAN_INPUT_REQUIRED
* a non-critical gap                                  -> recorded as an explicit ASSUMED value
* mutually exclusive constraints                      -> CONFLICT_BLOCKED (contradiction engine)
* a source past its freshness window                  -> REFRESH_REQUIRED
* a required capability not verified available        -> CAPABILITY_BLOCKED
* every acceptance predicate names a registered, evidence-producing verifier

It also carries the proof-debt ledger: the predicates still unmet, ordered by
severity and by how many other predicates depend on them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.execution.canonical import canonical_hash

GENOME_SCHEMA_VERSION = "amc-mission-genome/v1"
GenomeStatus = Literal["READY", "PROJECT_AMBIGUOUS", "HUMAN_INPUT_REQUIRED", "CONFLICT_BLOCKED", "REFRESH_REQUIRED",
                       "CAPABILITY_BLOCKED"]

# Every predicate must name one of these; each produces evidence by running, not by assertion.
VERIFIER_REGISTRY: dict[str, str] = {
    "media.readback": "agency.visual.verify.verify_media (independent byte reopen, Q0-Q4)",
    "svg.safety": "agency.execution_fabric.verifiers.svg_safety",
    "svg.palette": "agency.execution_fabric.verifiers.palette_conformance",
    "artifact.readback": "agency.intake.runner.verify_artifact",
    "release.gate": "agency.intake.release.artifact_release_verdict",
    "human.review": "approvals table + /approvals/{id}/decide (separation of duties)",
    "tests.pytest": "pytest exit code recorded in the verification seal",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Constraint(_Strict):
    key: str
    op: Literal["eq", "ne", "min", "max", "in", "not_in", "requires", "forbids"]
    value: Any
    source: str = "brief"


class SourceEvidence(_Strict):
    ref: str
    sha256: Optional[str] = None
    retrieved_at: str
    fresh_until: Optional[str] = None


class Unknown(_Strict):
    key: str
    critical: bool
    default: Any = None


class Predicate(_Strict):
    predicate_id: str
    description: str
    verifier: str
    severity: Literal["critical", "major", "minor"] = "critical"
    depends_on: tuple[str, ...] = ()


class MissionGenome(_Strict):
    schema_version: Literal["amc-mission-genome/v1"] = GENOME_SCHEMA_VERSION
    mission_id: str
    tenant_id: str
    project_id: Optional[str]
    objective: str
    audience: str
    deliverables: tuple[dict, ...]
    acceptance_predicates: tuple[Predicate, ...]
    source_evidence: tuple[SourceEvidence, ...]
    assumptions: tuple[dict, ...]
    unknowns: tuple[Unknown, ...]
    constraints: tuple[Constraint, ...]
    capability_bindings: dict[str, str]
    execution_mode: Literal["REAL_EXECUTION", "SIMULATION"]
    budgets: dict[str, Any]
    dependency_graph: dict[str, tuple[str, ...]]
    governance_policy: dict[str, str]
    review_policy: dict[str, tuple[str, ...]]
    build_ref: Optional[str]
    runtime_ref: dict[str, Any]
    provenance: dict[str, Any]
    status: GenomeStatus
    blockers: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    @property
    def genome_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def find_conflicts(constraints: tuple[Constraint, ...]) -> list[str]:
    """Contradiction engine: mutually exclusive constraints on the same key, found before dispatch."""
    by_key: dict[str, list[Constraint]] = {}
    for c in constraints:
        by_key.setdefault(c.key, []).append(c)
    conflicts: list[str] = []
    for key, cs in sorted(by_key.items()):
        eqs = {repr(c.value) for c in cs if c.op == "eq"}
        if len(eqs) > 1:
            conflicts.append(f"{key}: equals more than one value {sorted(eqs)}")
        mins = [c.value for c in cs if c.op == "min"]
        maxs = [c.value for c in cs if c.op == "max"]
        if mins and maxs and max(mins) > min(maxs):
            conflicts.append(f"{key}: min {max(mins)} exceeds max {min(maxs)}")
        for c in cs:
            if c.op == "eq":
                if mins and c.value < max(mins):
                    conflicts.append(f"{key}: {c.value} below min {max(mins)}")
                if maxs and c.value > min(maxs):
                    conflicts.append(f"{key}: {c.value} above max {min(maxs)}")
                if any(n.op == "ne" and n.value == c.value for n in cs):
                    conflicts.append(f"{key}: must equal and must not equal {c.value!r}")
                if any(n.op == "not_in" and c.value in n.value for n in cs):
                    conflicts.append(f"{key}: {c.value!r} is excluded")
                if any(n.op == "in" and c.value not in n.value for n in cs):
                    conflicts.append(f"{key}: {c.value!r} is outside the allowed set")
        required = {repr(c.value) for c in cs if c.op == "requires"}
        forbidden = {repr(c.value) for c in cs if c.op == "forbids"}
        for both in sorted(required & forbidden):
            conflicts.append(f"{key}: both requires and forbids {both}")
    return conflicts


def proof_debt(predicates: tuple[Predicate, ...], evidence: Mapping[str, str]) -> list[dict]:
    """Unmet predicates, most consequential first (severity, then how many others wait on them)."""
    dependents = {p.predicate_id: 0 for p in predicates}
    for p in predicates:
        for d in p.depends_on:
            if d in dependents:
                dependents[d] += 1
    rank = {"critical": 0, "major": 1, "minor": 2}
    unmet = [p for p in predicates if evidence.get(p.predicate_id) != "VERIFIED"]
    unmet.sort(key=lambda p: (rank[p.severity], -dependents[p.predicate_id], p.predicate_id))
    return [{"predicate_id": p.predicate_id, "severity": p.severity, "blocks": dependents[p.predicate_id],
             "verifier": p.verifier, "state": evidence.get(p.predicate_id, "PENDING")} for p in unmet]


def compile_genome(*, mission_id: str, tenant_id: str, project_resolution: Mapping[str, Any], objective: str, audience: str,
                   deliverables: tuple[dict, ...], predicates: tuple[Predicate, ...], constraints: tuple[Constraint, ...] = (),
                   sources: tuple[SourceEvidence, ...] = (), unknowns: tuple[Unknown, ...] = (),
                   capabilities: Mapping[str, str] = {}, execution_mode: str = "REAL_EXECUTION",
                   budgets: Optional[dict] = None, build_ref: Optional[str] = None, now: Optional[datetime] = None) -> MissionGenome:
    import platform
    import sys

    moment = now or datetime.now(timezone.utc)
    blockers: list[str] = []
    status: GenomeStatus = "READY"
    project_id = project_resolution.get("project_id") if project_resolution.get("status") == "BOUND" else None
    if project_id is None:
        status, blockers = "PROJECT_AMBIGUOUS", [f"PROJECT_{project_resolution.get('status', 'UNRESOLVED')}"]
    unknown_verifiers = [p.predicate_id for p in predicates if p.verifier not in VERIFIER_REGISTRY]
    if unknown_verifiers:
        raise ValueError(f"predicates name no registered verifier: {unknown_verifiers}")
    assumptions = tuple({"key": u.key, "value": u.default, "type": "ASSUMED"} for u in unknowns if not u.critical)
    critical = [u.key for u in unknowns if u.critical]
    conflicts = find_conflicts(constraints)
    stale = [s.ref for s in sources if s.fresh_until and datetime.fromisoformat(s.fresh_until) < moment]
    bindings = {}
    for d in deliverables:
        cap = d.get("capability")
        if cap:
            bindings[d["id"]] = capabilities.get(cap, "NOT_PROBED")
    missing_caps = sorted(f"{k}:{v}" for k, v in bindings.items() if v != "VERIFIED_AVAILABLE")
    if status == "READY":
        if critical:
            status, blockers = "HUMAN_INPUT_REQUIRED", [f"CRITICAL_UNKNOWN:{k}" for k in critical]
        elif conflicts:
            status, blockers = "CONFLICT_BLOCKED", ["CONSTRAINT_CONFLICT"]
        elif stale:
            status, blockers = "REFRESH_REQUIRED", [f"STALE_SOURCE:{r}" for r in stale]
        elif missing_caps:
            status, blockers = "CAPABILITY_BLOCKED", [f"CAPABILITY:{m}" for m in missing_caps]
    return MissionGenome(
        mission_id=mission_id, tenant_id=tenant_id, project_id=project_id, objective=objective, audience=audience,
        deliverables=deliverables, acceptance_predicates=predicates, source_evidence=sources, assumptions=assumptions,
        unknowns=unknowns, constraints=constraints, capability_bindings=bindings, execution_mode=execution_mode,
        budgets=budgets or {"max_attempts": 3, "render_timeout_s": 1800},
        dependency_graph={p.predicate_id: p.depends_on for p in predicates},
        governance_policy={"render": "G2", "approve": "G2+human", "publish": "G3:blocked", "spend": "G4:blocked"},
        review_policy={"TECHNICAL": ("media.readback",), "VISUAL": ("human.review",), "BRAND": ("human.review",),
                       "RIGHTS": ("media.readback",), "HUMAN": ("human.review",)},
        build_ref=build_ref, runtime_ref={"python": sys.version.split()[0], "platform": platform.platform()},
        provenance={"compiled_at": moment.isoformat(), "compiler": GENOME_SCHEMA_VERSION},
        status=status, blockers=tuple(blockers), conflicts=tuple(conflicts),
    )


__all__ = ["Constraint", "GENOME_SCHEMA_VERSION", "MissionGenome", "Predicate", "SourceEvidence", "Unknown",
           "VERIFIER_REGISTRY", "compile_genome", "find_conflicts", "proof_debt"]
