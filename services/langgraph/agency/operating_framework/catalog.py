"""The agency operating framework catalog: 24 modules, 295 task definitions.

The catalog is code-owned, immutable seed data (``data/catalog.seed-v1.json``),
pinned by its SHA-256 the same way ``agency/compiled/data/method_catalog.v1.json``
is. It is never a database table and never carries project state: every task in
it is ``NOT_STARTED`` / ``UNASSESSED`` with no evidence, and a project gets its
own task instances (``persistence/operating_framework.py``) that reference these
definitions by ``task_id`` and the pinned catalog hash.

``load_catalog`` refuses a catalog that does not validate against the vendored
JSON Schema (``data/catalog.schema.json``) or that fails the semantic checks the
schema cannot express: unique ids, per-module counts, module references, an
acyclic module graph, task/module consistency and the published totals.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data"
CATALOG_FILE = DATA / "catalog.seed-v1.json"
SCHEMA_FILE = DATA / "catalog.schema.json"

# The SHA-256 of the catalog bytes as supplied (05_CATALOG_VALIDATION_BASELINE.json).
# A different file is a different catalog version, never a silent upgrade.
PINNED_CATALOG_SHA256 = "9a2c30e9e65c2a3a6de70245cc47bbeeea2c695b965c09a143935d8ce3df501a"
CATALOG_VERSION = "amc-agency-operating-framework/seed-v1"

STAGE_GATES = ("01_DISCOVERY", "02_STRATEGY", "03_PRODUCTION", "04_ACTIVATION", "05_GROWTH")
DISCIPLINES = ("Discover", "Strategize", "Design", "Build", "Activate", "Optimize")
OUTPUT_CLASSES = ("evidence", "decision", "artifact", "approval_or_plan", "measurement")


class CatalogInvalid(ValueError):
    """The catalog failed schema or semantic validation; nothing is imported."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems[:10]) + (f" (+{len(problems) - 10} more)" if len(problems) > 10 else ""))
        self.problems = problems


@dataclass(frozen=True)
class ModuleDefinition:
    module_id: str
    title: str
    phase: str
    stage_gate: str
    expected_task_count: int
    depends_on_modules: tuple[str, ...]
    required_deliverable: str
    owner_role: str
    acceptance_policy: str


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    module_id: str
    sequence: int
    title: str
    definition_source: str
    owner_role: str
    phase: str
    stage_gate: str
    depends_on_modules: tuple[str, ...]
    output_class: str
    module_deliverable: str
    acceptance: str


@dataclass(frozen=True)
class Catalog:
    catalog_id: str
    catalog_version: str
    sha256: str
    stage_gates: Mapping[str, str]
    modules: tuple[ModuleDefinition, ...]
    tasks: tuple[TaskDefinition, ...]

    def module(self, module_id: str) -> ModuleDefinition:
        for module in self.modules:
            if module.module_id == module_id:
                return module
        raise KeyError(module_id)

    def task(self, task_id: str) -> TaskDefinition:
        task = self._task_index().get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def _task_index(self) -> dict[str, TaskDefinition]:
        return {t.task_id: t for t in self.tasks}

    def tasks_in(self, module_id: str) -> tuple[TaskDefinition, ...]:
        return tuple(t for t in self.tasks if t.module_id == module_id)

    def summary(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "catalog_version": self.catalog_version,
            "sha256": self.sha256,
            "module_count": len(self.modules),
            "task_count": len(self.tasks),
            "user_supplied_task_count": sum(1 for t in self.tasks if t.definition_source == "user_supplied"),
            "newly_authored_task_count": sum(1 for t in self.tasks if t.definition_source == "newly_authored_expansion"),
            "per_discipline": {p: sum(1 for t in self.tasks if t.phase == p) for p in DISCIPLINES},
            "per_stage_gate": {g: sum(1 for t in self.tasks if t.stage_gate == g) for g in STAGE_GATES},
            "per_module": {m.module_id: len(self.tasks_in(m.module_id)) for m in self.modules},
        }


# ---------------------------------------------------------------------------
# A JSON Schema (2020-12) validator for exactly the keywords the vendored schema
# uses. jsonschema is not a base dependency; an unknown keyword is an error, so
# a future schema can never be "validated" by silently skipping a rule.
# ---------------------------------------------------------------------------

_SUPPORTED = {
    "$schema", "$id", "title", "type", "required", "properties", "additionalProperties", "const", "enum",
    "pattern", "minLength", "minimum", "minItems", "maxItems", "uniqueItems", "items", "minProperties",
}
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "null": type(None)}


def validate_against_schema(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    unknown = set(schema) - _SUPPORTED
    if unknown:
        return [f"{path}: unsupported schema keyword(s) {sorted(unknown)}"]
    problems: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        py_type = _TYPES[expected]
        ok = isinstance(value, py_type) and not (expected == "integer" and isinstance(value, bool))
        if not ok:
            return [f"{path}: expected {expected}"]
    if "const" in schema and value != schema["const"]:
        problems.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            problems.append(f"{path}: shorter than {schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            problems.append(f"{path}: does not match {schema['pattern']}")
    if isinstance(value, int) and not isinstance(value, bool) and "minimum" in schema and value < schema["minimum"]:
        problems.append(f"{path}: below minimum {schema['minimum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            problems.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            problems.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            problems.append(f"{path}: items are not unique")
        if "items" in schema:
            for i, item in enumerate(value):
                problems.extend(validate_against_schema(item, schema["items"], f"{path}[{i}]"))
    if isinstance(value, dict):
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            problems.append(f"{path}: fewer than {schema['minProperties']} properties")
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{path}: missing required {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                problems.append(f"{path}: unexpected properties {extra}")
        for key, sub in properties.items():
            if key in value:
                problems.extend(validate_against_schema(value[key], sub, f"{path}.{key}"))
    return problems


def _module_cycle(modules: Mapping[str, tuple[str, ...]]) -> list[str]:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        state[node] = 1
        stack.append(node)
        for dep in modules.get(node, ()):
            if state.get(dep) == 1:
                return stack[stack.index(dep):] + [dep]
            if state.get(dep) is None and dep in modules:
                cycle = visit(dep)
                if cycle:
                    return cycle
        stack.pop()
        state[node] = 2
        return []

    for node in sorted(modules):
        if state.get(node) is None:
            cycle = visit(node)
            if cycle:
                return cycle
    return []


def semantic_problems(data: Mapping[str, Any]) -> list[str]:
    """Rules the JSON Schema cannot express. Run only on schema-valid data."""
    problems: list[str] = []
    modules = data["modules"]
    tasks = data["tasks"]
    module_ids = [m["module_id"] for m in modules]
    task_ids = [t["task_id"] for t in tasks]
    for mid, n in Counter(module_ids).items():
        if n > 1:
            problems.append(f"duplicate module id {mid}")
    for tid, n in Counter(task_ids).items():
        if n > 1:
            problems.append(f"duplicate task id {tid}")
    by_id = {m["module_id"]: m for m in modules}
    for m in modules:
        for dep in m["depends_on_modules"]:
            if dep not in by_id:
                problems.append(f"{m['module_id']} depends on undefined module {dep}")
            if dep == m["module_id"]:
                problems.append(f"{m['module_id']} depends on itself")
    cycle = _module_cycle({m["module_id"]: tuple(m["depends_on_modules"]) for m in modules})
    if cycle:
        problems.append("module dependency cycle: " + " -> ".join(cycle))
    counts = Counter(t["module_id"] for t in tasks)
    for t in tasks:
        module = by_id.get(t["module_id"])
        if module is None:
            problems.append(f"{t['task_id']} references undefined module {t['module_id']}")
            continue
        if t["task_id"] != f"{t['module_id']}-{t['sequence']:03d}":
            problems.append(f"{t['task_id']} does not match its module and sequence")
        for key in ("phase", "stage_gate", "owner_role"):
            if t[key] != module[key]:
                problems.append(f"{t['task_id']}.{key} differs from its module")
        if list(t["depends_on_modules"]) != list(module["depends_on_modules"]):
            problems.append(f"{t['task_id']}.depends_on_modules differs from its module")
    for m in modules:
        if counts.get(m["module_id"], 0) != m["expected_task_count"]:
            problems.append(f"{m['module_id']} has {counts.get(m['module_id'], 0)} tasks, expected {m['expected_task_count']}")
        sequences = sorted(t["sequence"] for t in tasks if t["module_id"] == m["module_id"])
        if sequences != list(range(1, len(sequences) + 1)):
            problems.append(f"{m['module_id']} task sequences are not 1..n")
    if len(tasks) != data["task_count"] or len(modules) != data["module_count"]:
        problems.append("published totals do not match the content")
    supplied = sum(1 for t in tasks if t["definition_source"] == "user_supplied")
    if supplied != data["user_explicit_task_count"] or len(tasks) - supplied != data["newly_authored_task_count"]:
        problems.append("definition-source attribution does not match the published counts")
    if set(data["stage_gates"]) != set(STAGE_GATES):
        problems.append(f"stage gates must be exactly {list(STAGE_GATES)}")
    return problems


def parse_catalog(raw: bytes, schema: Mapping[str, Any], *, expected_sha256: str | None = PINNED_CATALOG_SHA256) -> Catalog:
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise CatalogInvalid([f"catalog sha256 {sha} is not the pinned {expected_sha256}"])
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise CatalogInvalid([f"catalog is not JSON: {exc}"]) from exc
    problems = validate_against_schema(data, schema)
    if problems:
        raise CatalogInvalid(problems)
    problems = semantic_problems(data)
    if problems:
        raise CatalogInvalid(problems)
    return Catalog(
        catalog_id=data["catalog_id"],
        catalog_version=data["schema_version"],
        sha256=sha,
        stage_gates=dict(data["stage_gates"]),
        modules=tuple(
            ModuleDefinition(**{**m, "depends_on_modules": tuple(m["depends_on_modules"])}) for m in data["modules"]
        ),
        tasks=tuple(
            TaskDefinition(
                task_id=t["task_id"], module_id=t["module_id"], sequence=t["sequence"], title=t["title"],
                definition_source=t["definition_source"], owner_role=t["owner_role"], phase=t["phase"],
                stage_gate=t["stage_gate"], depends_on_modules=tuple(t["depends_on_modules"]),
                output_class=t["output_class"], module_deliverable=t["module_deliverable"], acceptance=t["acceptance"],
            )
            for t in data["tasks"]
        ),
    )


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    return parse_catalog(CATALOG_FILE.read_bytes(), json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))


__all__ = [
    "CATALOG_VERSION",
    "DISCIPLINES",
    "OUTPUT_CLASSES",
    "PINNED_CATALOG_SHA256",
    "STAGE_GATES",
    "Catalog",
    "CatalogInvalid",
    "ModuleDefinition",
    "TaskDefinition",
    "load_catalog",
    "parse_catalog",
    "semantic_problems",
    "validate_against_schema",
]
