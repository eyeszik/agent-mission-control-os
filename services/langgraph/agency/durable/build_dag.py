"""Track A: the finite Build DAG G = (V, E) and the three predicates that must never be conflated.

    BuildComplete   := RequiredArtifactsExist AND HashesMatch AND BuildChecksPass AND NoCriticalUnresolvedDependencies
    ReleaseEligible := BuildComplete AND IndependentReviewPassed AND AuthorizationValid AND ApprovalCurrent
                       AND NoSimulationContamination
    RuntimeActive   := SchedulerConfigured AND WorkerOperational AND DurableStateAvailable AND ActivationAuthorized

Node identities are deterministic (hash of name, deps and action). A node's
status is computed from evidence (command exit codes, file hashes), never from
an agent's report that it finished.
"""

from __future__ import annotations

import heapq
from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping

from services.langgraph.agency.execution.canonical import canonical_hash

BUILD_DAG_VERSION = "amc-build-dag/v1"


@dataclass(frozen=True)
class Node:
    name: str
    deps: tuple[str, ...]
    owner: str
    action: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    capabilities: tuple[str, ...]
    authorization: str          # governance level, e.g. G0 read-only, G1 local workspace
    idempotency: str
    timeout_s: int
    retries: int
    resource_budget: str
    acceptance: tuple[str, ...]
    verification: tuple[str, ...]  # evidence ids the seal must find (command ids or files)
    rollback: str
    edge_types: Mapping[str, str] = field(default_factory=dict)  # dep -> artifact/dependency semantics

    @property
    def node_id(self) -> str:
        return canonical_hash({"name": self.name, "deps": list(self.deps), "action": self.action})[:16]


def _n(name, deps, owner, action, outputs, verification, *, timeout_s=1800, caps=(), auth="G1", edges=None, **kw) -> Node:
    return Node(name=name, deps=tuple(deps), owner=owner, action=action, inputs=tuple(f"{d}.outputs" for d in deps),
                outputs=tuple(outputs), capabilities=tuple(caps), authorization=auth,
                idempotency=kw.get("idempotency", "deterministic re-run; outputs content-addressed"), timeout_s=timeout_s,
                retries=min(3, kw.get("retries", 2)), resource_budget=kw.get("budget", f"{timeout_s}s wall, 4 CPU"),
                acceptance=tuple(kw.get("acceptance", (f"{name}.verified",))), verification=tuple(verification),
                rollback=kw.get("rollback", "git revert of the producing commit"),
                edge_types=edges or {d: "artifact" for d in deps})


BUILD_DAG: tuple[Node, ...] = (
    _n("A00_DISCOVER", (), "PrincipalSystemsArchitect", "inspect repository and environment; snapshot baseline",
       ("environment snapshot",), ("cmd:environment_snapshot",), auth="G0", timeout_s=300),
    _n("A01_MAP", ("A00_DISCOVER",), "PrincipalSystemsArchitect", "trace requirements to implementations",
       ("docs/abc-v6-traceability.md",), ("file:docs/abc-v6-traceability.md",), auth="G0", timeout_s=600),
    _n("A02_SPECIFY", ("A01_MAP",), "RuntimeCompiler", "mission genome, contracts, schemas, governance",
       ("agency/durable/genome.py", "runtime/abc/governance-matrix.yaml"), ("cmd:pytest_abc",), timeout_s=900),
    _n("A03_INTEGRATE", ("A02_SPECIFY",), "RuntimeCompiler", "extend control plane: shared release gate, durable runtime",
       ("agency/intake/release.py", "persistence/durable_runs.py"), ("cmd:pytest_abc", "cmd:pytest_intake"), timeout_s=900),
    _n("A04_VISUAL", ("A03_INTEGRATE",), "CreativeEngineEngineer", "local image and scene generation (Blender Cycles)",
       ("agency/visual",), ("cmd:pytest_abc",), caps=("R1_BLENDER_CYCLES",), timeout_s=1800),
    _n("A05_PRODUCE", ("A03_INTEGRATE", "A04_VISUAL"), "CreativeEngineEngineer", "connect SVG, video and render routes",
       ("runtime/abc/samples",), ("file:runtime/abc/samples/provenance.json",), caps=("R1_BLENDER_CYCLES", "R5_LOCAL_VIDEO"),
       timeout_s=3600),
    _n("A06_VERIFY", ("A04_VISUAL", "A05_PRODUCE"), "SecurityReviewer", "independent artifact readback verification",
       ("agency/visual/verify.py",), ("cmd:pytest_abc",), timeout_s=900),
    _n("A07_OPERATE", ("A03_INTEGRATE", "A06_VERIFY"), "RuntimeCompiler", "durable scheduling and reconciliation",
       ("agency/durable/ticks.py", "supabase/migrations/20261009_amc_durable_runtime_v1.sql"), ("cmd:pytest_abc",), timeout_s=900),
    _n("A08_OBSERVE", ("A07_OPERATE",), "RuntimeCompiler", "tick telemetry and transition log",
       ("durable_ticks", "durable_transitions"), ("cmd:pytest_abc",), timeout_s=600),
    _n("A09_TEST", ("A06_VERIFY", "A07_OPERATE", "A08_OBSERVE"), "SecurityReviewer", "unit, integration, fault and regression",
       ("test results",), ("cmd:pytest_full", "cmd:ruff", "cmd:compileall"), timeout_s=1800),
    _n("A10_PACKAGE", ("A09_TEST",), "PrincipalSystemsArchitect", "manifests, docs, runbook, evidence",
       ("runtime/abc/*.yaml", "docs/abc-v6-runbook.md"), ("cmd:abc_manifests_check", "cmd:gates"), timeout_s=600),
    _n("A11_SEAL", ("A10_PACKAGE",), "SecurityReviewer", "seal BuildState=DELIVERABLE_EXISTS only if predicates pass",
       ("runtime/abc/verification-seal.json",), ("self:seal_composed",), timeout_s=300,
       rollback="discard the seal; it is regenerated from command results"),
)


class DagError(ValueError):
    pass


def by_name(nodes: Iterable[Node] = BUILD_DAG) -> dict[str, Node]:
    return {n.name: n for n in nodes}


def toposort(nodes: Iterable[Node] = BUILD_DAG) -> list[str]:
    """Kahn's algorithm with a name-ordered heap: deterministic, and raises on a cycle or dangling dep."""
    index = by_name(nodes)
    indeg = {name: 0 for name in index}
    children: dict[str, list[str]] = {name: [] for name in index}
    for n in index.values():
        for d in n.deps:
            if d not in index:
                raise DagError(f"{n.name} depends on missing node {d}")
            indeg[n.name] += 1
            children[d].append(n.name)
    ready = [name for name, deg in indeg.items() if deg == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for c in sorted(children[name]):
            indeg[c] -= 1
            if indeg[c] == 0:
                heapq.heappush(ready, c)
    if len(order) != len(index):
        raise DagError(f"cycle among {sorted(set(index) - set(order))}")
    return order


def dependency_closure(name: str, nodes: Iterable[Node] = BUILD_DAG) -> set[str]:
    index = by_name(nodes)
    seen, stack = set(), [name]
    while stack:
        for d in index[stack.pop()].deps:
            if d not in seen:
                seen.add(d)
                stack.append(d)
    return seen


def critical_path(nodes: Iterable[Node] = BUILD_DAG) -> tuple[list[str], int]:
    """Longest path by timeout budget: the chain that bounds total build time."""
    index = by_name(nodes)
    best: dict[str, tuple[int, list[str]]] = {}
    for name in toposort(index.values()):
        n = index[name]
        prev = max((best[d] for d in n.deps), key=lambda t: (t[0], t[1]), default=(0, []))
        best[name] = (prev[0] + n.timeout_s, prev[1] + [name])
    end = max(best.values(), key=lambda t: (t[0], t[1]))
    return end[1], end[0]


def waves(nodes: Iterable[Node] = BUILD_DAG, *, max_parallel: int = 2) -> list[list[str]]:
    """Bounded-parallel execution waves: a node runs only after all of its deps' waves."""
    index = by_name(nodes)
    level: dict[str, int] = {}
    for name in toposort(index.values()):
        level[name] = 1 + max((level[d] for d in index[name].deps), default=-1)
    out: list[list[str]] = []
    for lvl in sorted(set(level.values())):
        members = sorted(n for n, lv in level.items() if lv == lvl)
        for i in range(0, len(members), max_parallel):
            out.append(members[i:i + max_parallel])
    return out


def node_status(node: Node, evidence: Mapping[str, str]) -> str:
    """PASSED only when every verification id has PASSED evidence; NOT_RUN is never PASSED."""
    states = [evidence.get(v, "NOT_RUN") for v in node.verification]
    if all(s == "PASSED" for s in states):
        return "PASSED"
    if any(s == "FAILED" for s in states):
        return "FAILED"
    return "NOT_RUN"


def build_complete(*, artifacts_exist: bool, hashes_match: bool, checks_pass: bool, critical_unresolved: int) -> bool:
    return artifacts_exist and hashes_match and checks_pass and critical_unresolved == 0


def release_eligible(*, build_ok: bool, review_passed: bool, authorization_valid: bool, approval_current: bool,
                     simulation_free: bool) -> bool:
    return build_ok and review_passed and authorization_valid and approval_current and simulation_free


def runtime_active(*, scheduler_configured: bool, worker_operational: bool, durable_state: bool,
                   activation_authorized: bool) -> bool:
    return scheduler_configured and worker_operational and durable_state and activation_authorized


def as_document(nodes: Iterable[Node] = BUILD_DAG) -> dict:
    nodes = tuple(nodes)
    path, budget = critical_path(nodes)
    return {
        "schema_version": BUILD_DAG_VERSION,
        "acyclic": True,
        "topological_order": toposort(nodes),
        "critical_path": {"nodes": path, "budget_s": budget},
        "waves_max_parallel_2": waves(nodes),
        "node_status_source": "runtime/abc/verification-seal.json (computed from command evidence, never self-reported)",
        "nodes": [{"id": n.node_id, **{k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(n).items()}}
                  for n in nodes],
    }


__all__ = ["BUILD_DAG", "BUILD_DAG_VERSION", "DagError", "Node", "as_document", "build_complete", "critical_path",
           "dependency_closure", "node_status", "release_eligible", "runtime_active", "toposort", "waves"]
