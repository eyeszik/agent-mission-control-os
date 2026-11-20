"""Ordered SOP contracts: the canonical registry, its schema and its structural checks.

``data/sop_registry.v1.json`` is the single source. This module validates it
with Pydantic, and ``packages/shared/src/schemas/sop.ts`` validates the
recorded fixture of the same bytes with Zod. Structural checks are pure; the
checks against live code (topology, N3 roles, RoleOS skills, enforcing
symbols, test ids) live in :func:`verify_against_code` so a renamed symbol
fails a test instead of leaving a stale claim. The registry describes and
guards behaviour; it never grants authority.
"""

from __future__ import annotations

import ast
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[4]
REGISTRY_FILE = Path(__file__).resolve().parent / "data" / "sop_registry.v1.json"
SCHEMA_VERSION = "amc-sop-registry/v1"
FailureDisposition = Literal["FALLBACK_DEGRADED", "BLOCKED"]
StepKind = Literal["production", "measurement", "gate", "recovery"]


class GateBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    governance_level: Literal["G0", "G1", "G2"]
    gates: list[str] = Field(min_length=1)


class SopStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sop_id: str = Field(pattern=r"^SOP-[A-Z]+(-[A-Z]+)?-\d{2}$")
    stage_name: str = Field(min_length=1)
    kind: StepKind
    owner_role: str = Field(min_length=1)
    roleos_skill: Optional[str] = None
    entry_preconditions: list[str] = Field(min_length=1)
    requires_state: list[str]
    input_schema: dict[str, str] = Field(min_length=1)
    output_schema: dict[str, str] = Field(min_length=1)
    exit_postconditions: list[str] = Field(min_length=1)
    idempotency_key_formula: str = Field(min_length=1)
    gate_binding: GateBinding
    retry_and_lease_bounds: dict[str, object]
    failure_disposition: FailureDisposition
    enforced_by: list[str] = Field(min_length=1)
    tests: list[str] = Field(min_length=1)


class ProcedureStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sequence_index: int = Field(ge=1)
    sop_id: str


class SopProcedure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    procedure_id: str
    kind: Literal["pipeline", "recovery"]
    workflow_version: Optional[str] = None
    steps: list[ProcedureStep] = Field(min_length=1)


class SopRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["amc-sop-registry/v1"]
    description: str
    owner_principals: list[str]
    steps: list[SopStep] = Field(min_length=1)
    procedures: list[SopProcedure] = Field(min_length=1)

    @model_validator(mode="after")
    def _structure(self) -> "SopRegistry":
        problems = structural_problems(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def step(self, sop_id: str) -> SopStep:
        return next(step for step in self.steps if step.sop_id == sop_id)

    def ordered(self, procedure_id: str) -> list[SopStep]:
        procedure = next(p for p in self.procedures if p.procedure_id == procedure_id)
        return [self.step(entry.sop_id) for entry in sorted(procedure.steps, key=lambda e: e.sequence_index)]

    def pipeline_step(self, stage_name: str) -> Optional[SopStep]:
        return next((s for s in self.steps if s.stage_name == stage_name and s.kind != "recovery"), None)


def _sequence_problems(procedure: SopProcedure, known: set[str]) -> list[str]:
    indices = [entry.sequence_index for entry in procedure.steps]
    problems = []
    if indices != list(range(1, len(indices) + 1)):
        problems.append(f"{procedure.procedure_id}: sequence_index must be contiguous from 1, got {indices}")
    ids = [entry.sop_id for entry in procedure.steps]
    if len(set(ids)) != len(ids):
        problems.append(f"{procedure.procedure_id}: a step repeats, so the procedure is cyclic")
    problems += [f"{procedure.procedure_id}: unknown sop_id {i}" for i in ids if i not in known]
    return problems


def _dataflow_problems(registry: SopRegistry, procedure: SopProcedure) -> list[str]:
    """Every required state key is produced by an earlier step of the same pipeline."""
    produced: set[str] = set()
    problems = []
    for entry in sorted(procedure.steps, key=lambda e: e.sequence_index):
        step = registry.step(entry.sop_id)
        missing = [key for key in step.requires_state if key not in produced]
        problems += [f"{procedure.procedure_id}: {step.sop_id} requires {key} before any step produces it" for key in missing]
        produced |= set(step.output_schema)
    return problems


def structural_problems(registry: SopRegistry) -> list[str]:
    ids = [step.sop_id for step in registry.steps]
    problems = [f"duplicate sop_id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    if problems:
        return problems
    referenced = {entry.sop_id for p in registry.procedures for entry in p.steps}
    problems += [f"orphan step {i}: in no procedure" for i in ids if i not in referenced]
    for procedure in registry.procedures:
        sequence = _sequence_problems(procedure, set(ids))
        problems += sequence
        if not sequence and procedure.kind == "pipeline":
            problems += _dataflow_problems(registry, procedure)
    return problems


@lru_cache(maxsize=1)
def load_registry() -> SopRegistry:
    return SopRegistry.model_validate(json.loads(REGISTRY_FILE.read_text(encoding="utf-8")))


def _defines(path: Path, symbol: str) -> bool:
    """True when ``symbol`` is defined, assigned or imported at any level of ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            return True
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == symbol for t in targets):
                return True
        if isinstance(node, ast.ImportFrom) and any((a.asname or a.name) == symbol for a in node.names):
            return True
    return False


def reference_problems(registry: SopRegistry, root: Path = ROOT) -> list[str]:
    """Every ``path::symbol`` enforcer and ``path::test`` id resolves in the tree."""
    problems = []
    for step in registry.steps:
        for ref in [*step.enforced_by, *step.tests]:
            rel, _, symbol = ref.partition("::")
            path = root / rel
            if not path.is_file() or not symbol or not _defines(path, symbol):
                problems.append(f"{step.sop_id}: unresolved reference {ref}")
    return problems


def _pipeline_problems(registry: SopRegistry) -> list[str]:
    from services.langgraph.agency.delivery.workflow import _NODES, topology
    problems = []
    pipelines = {p.workflow_version: p for p in registry.procedures if p.kind == "pipeline"}
    for version in _NODES:
        if version not in pipelines:
            problems.append(f"workflow {version} has no SOP procedure")
            continue
        stages = [step.stage_name for step in registry.ordered(pipelines[version].procedure_id)]
        if stages != topology(version)["node_ids"]:
            problems.append(f"{version}: SOP order {stages} != graph topology {topology(version)['node_ids']}")
    problems += [f"procedure for unknown workflow {v}" for v in pipelines if v not in _NODES]
    return problems


def _role_problems(registry: SopRegistry) -> list[str]:
    from services.langgraph.agency.kernel import ROLE_REGISTRY, assert_role_may_produce
    from services.langgraph.agency.role_os.amc_profile import AGENCY_STAGE_BINDINGS
    from services.langgraph.graph.agency.nodes import LIVE_STAGE_ARTIFACTS, LIVE_STAGE_ROLE_BINDINGS
    skills = {b.stage_id: b.role_skill_name for b in AGENCY_STAGE_BINDINGS}
    problems = []
    for step in registry.steps:
        if step.owner_role not in ROLE_REGISTRY and step.owner_role not in registry.owner_principals:
            problems.append(f"{step.sop_id}: owner_role {step.owner_role} is neither an N3 role nor a declared principal")
        if step.kind == "recovery" or step.stage_name not in LIVE_STAGE_ROLE_BINDINGS:
            continue
        if step.owner_role != LIVE_STAGE_ROLE_BINDINGS[step.stage_name]:
            problems.append(f"{step.sop_id}: owner_role differs from LIVE_STAGE_ROLE_BINDINGS")
        if step.roleos_skill != skills.get(step.stage_name):
            problems.append(f"{step.sop_id}: roleos_skill differs from AGENCY_STAGE_BINDINGS")
        if step.stage_name in LIVE_STAGE_ARTIFACTS:
            assert_role_may_produce(step.owner_role, LIVE_STAGE_ARTIFACTS[step.stage_name])
    return problems


def verify_against_code(registry: Optional[SopRegistry] = None) -> list[str]:
    """Bind the registry to the running code; an empty list means it agrees."""
    registry = registry or load_registry()
    return [*_pipeline_problems(registry), *_role_problems(registry), *reference_problems(registry)]
