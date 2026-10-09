"""Adaptive proof modules that the existing infrastructure did not already provide.

* ``EvidenceRecord`` / ``evidence_valid``: EVIDENCE_DOMINATOR_CACHE. Evidence is
  reusable only while its subject hash and every dependency version it was
  computed against are unchanged.
* ``invalidated_by``: CAUSAL_INVALIDATION. A change invalidates exactly the
  evidence whose inputs include the changed key, and nothing else.
* ``minimal_proof_set``: PROOF_MINIMIZER. The smallest set of valid evidence
  covering every mandatory release predicate (exact search for small inputs,
  greedy above the bound, and it says which it used).
* ``capability_registry``: CAPABILITY_IMMUNE_REGISTRY. Adapter versions,
  observed failure fingerprints from durable state, and a circuit state.

Proof debt and the contradiction engine live in :mod:`.genome`; negative
knowledge in :mod:`.ticks`; the visual genome in ``agency.visual.contracts``.
Novelty within constraints reuses the creative runtime's bounded Pareto search
(``agency.creative``) rather than adding a second search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable, Mapping, Optional

EXACT_SEARCH_LIMIT = 16


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    verifier: str
    subject_hash: str
    satisfies: frozenset[str]
    dependency_versions: Mapping[str, str] = field(default_factory=dict)
    state: str = "PASSED"  # only PASSED evidence can satisfy anything; NOT_RUN never does


def evidence_valid(record: EvidenceRecord, *, current_subject_hash: str, current_versions: Mapping[str, str]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if record.state != "PASSED":
        reasons.append(f"STATE_{record.state}")
    if record.subject_hash != current_subject_hash:
        reasons.append("SUBJECT_HASH_CHANGED")
    for dep, version in sorted(record.dependency_versions.items()):
        now = current_versions.get(dep)
        if now is None:
            reasons.append(f"DEPENDENCY_MISSING:{dep}")
        elif now != version:
            reasons.append(f"DEPENDENCY_CHANGED:{dep}")
    return not reasons, reasons


def invalidated_by(records: Iterable[EvidenceRecord], changed: Iterable[str], *, subject_key: str = "subject") -> list[str]:
    """Evidence ids whose inputs include a changed key. Unrelated evidence survives."""
    changed = set(changed)
    out = []
    for r in records:
        inputs = set(r.dependency_versions) | {subject_key}
        if inputs & changed:
            out.append(r.evidence_id)
    return sorted(out)


def minimal_proof_set(predicates: Iterable[str], records: Iterable[EvidenceRecord]) -> dict:
    required = frozenset(predicates)
    usable = sorted((r for r in records if r.state == "PASSED" and r.satisfies & required), key=lambda r: r.evidence_id)
    covered = frozenset().union(*(r.satisfies for r in usable)) & required if usable else frozenset()
    missing = sorted(required - covered)
    if missing:
        return {"complete": False, "evidence": [], "missing": missing, "method": "none"}
    if len(usable) <= EXACT_SEARCH_LIMIT:
        for size in range(1, len(usable) + 1):
            for combo in combinations(usable, size):
                if required <= frozenset().union(*(r.satisfies for r in combo)):
                    return {"complete": True, "evidence": [r.evidence_id for r in combo], "missing": [], "method": "exact"}
    chosen, left = [], set(required)
    while left:
        best = max(usable, key=lambda r: (len(r.satisfies & left), r.evidence_id))
        chosen.append(best.evidence_id)
        left -= best.satisfies
    return {"complete": True, "evidence": chosen, "missing": [], "method": "greedy (not guaranteed minimal)"}


def circuit_state(failures: Mapping[str, Mapping], *, threshold: int = 2) -> str:
    """OPEN when one fingerprint repeats under an unchanged environment; static limit, no measured baseline."""
    if any(int(v.get("count", 0)) >= threshold for v in failures.values()):
        return "OPEN"
    return "HALF_OPEN" if failures else "CLOSED"


def capability_registry(capabilities: Mapping, jobs: Iterable[Mapping]) -> dict:
    """Join probed adapter versions with failure fingerprints persisted on durable jobs."""
    per_kind: dict[str, dict] = {}
    for job in jobs:
        bucket = per_kind.setdefault(job["kind"], {})
        for fp, info in (job.get("failure_fingerprints") or {}).items():
            agg = bucket.setdefault(fp, {"count": 0, "env": info.get("env")})
            agg["count"] += int(info.get("count", 0))
    return {
        "adapters": {getattr(route, "value", str(route)): {"status": cap.status.value, "version": cap.version,
                                                         "blockers": list(cap.blockers)}
                     for route, cap in sorted(capabilities.items(), key=lambda kv: getattr(kv[0], "value", str(kv[0])))},
        "job_kinds": {kind: {"failures": fps, "circuit": circuit_state(fps)} for kind, fps in sorted(per_kind.items())},
        "baseline": "BASELINE_UNKNOWN: circuit uses a static repeat threshold, not a latency percentile",
    }


def proof_graph(*, requirement: str, execution: Optional[dict], artifact: Optional[dict], readback: Optional[dict],
                verification: Optional[dict], approval: Optional[dict], release: Optional[dict]) -> list[dict]:
    """Requirement -> Execution -> Artifact -> Readback -> Verification -> Approval -> Release, with the first gap named."""
    chain = [("requirement", {"id": requirement}), ("execution", execution), ("artifact", artifact), ("readback", readback),
             ("verification", verification), ("approval", approval), ("release", release)]
    out, broken = [], False
    for name, node in chain:
        present = node is not None and not broken
        out.append({"node": name, "present": present, "ref": node if present else None})
        broken = broken or node is None
    return out


__all__ = ["EvidenceRecord", "capability_registry", "circuit_state", "evidence_valid", "invalidated_by",
           "minimal_proof_set", "proof_graph"]
