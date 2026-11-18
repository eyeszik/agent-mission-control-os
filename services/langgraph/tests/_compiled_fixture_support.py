"""Shared helpers for the compiled-agency parity fixtures (see test_compiled_parity_fixture.py).

Tagged JSON values: {"$float": repr} for a Python float, {"$set": [...]} for a frozenset,
{"$int": "<decimal>"} for an int JS cannot hold exactly. `decode` turns tags into Python values,
`plain` turns Python results into order-insensitive JSON-able values, and `case` records one call
as {"call", "args", "ok"} or {"call", "args", "error"}.
"""
from __future__ import annotations

import dataclasses
import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from services.langgraph.agency.role_os import RoleOSRegistry

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages/compiled"
FIXTURES = PACKAGE / "tests/fixtures"
CORE = FIXTURES / "compiled-core.json"
PLANS = FIXTURES / "compiled-plans.json"
METHODS = FIXTURES / "compiled-methods.json"
RUNTIME_ROOT = ROOT / "runtime/role_os"
CATALOG_PATH = ROOT / "services/langgraph/agency/compiled/data/method_catalog.v1.json"

AS_OF = "2026-10-29"
HASH = "a" * 64


def regenerate() -> bool:
    return os.environ.get("AMC_REGENERATE_FIXTURES") == "1"


def f(x: float) -> dict[str, str]:
    return {"$float": repr(x)}


def decode(node: Any) -> Any:
    if isinstance(node, list):
        return [decode(x) for x in node]
    if not isinstance(node, dict):
        return node
    if len(node) == 1:
        (tag, raw), = node.items()
        if tag == "$float":
            return float(raw)
        if tag == "$set":
            return frozenset(decode(x) for x in raw)
        if tag == "$int":
            return int(raw)
    return {k: decode(v) for k, v in node.items()}


def plain(value: Any) -> Any:
    """A JSON-able, order-insensitive view of a Python result."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return plain(value.model_dump(mode="json"))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {fld.name: plain(getattr(value, fld.name)) for fld in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def locs(exc: ValidationError) -> list[str]:
    return sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})


def error_record(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, ValidationError):
        return {"type": "ValidationError", "locs": locs(exc)}
    return {"type": type(exc).__name__, "message": str(exc)}


def case(call: str, args: list[Any], fn: Callable[..., Any]) -> dict[str, Any]:
    """Record one call. `args` are the tagged JSON arguments; `fn` receives them decoded."""
    try:
        return {"call": call, "args": args, "ok": plain(fn(*decode(args)))}
    except Exception as exc:  # noqa: BLE001 - the fixture records every Python failure, by class and message
        return {"call": call, "args": args, "error": error_record(exc)}


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


_REGISTRY: RoleOSRegistry | None = None


def registry() -> RoleOSRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = RoleOSRegistry(RUNTIME_ROOT)
    return _REGISTRY


class VariantRegistry:
    """A duck-typed registry: the sealed roles with chosen authority edits and grant contract."""

    def __init__(self, base: RoleOSRegistry, *, registry_hash: str, grant_contract: dict[str, Any],
                 authority_edits: dict[str, dict[str, Any]]):
        self.roles = {
            rid: dataclasses.replace(r, runtime_authority={**r.runtime_authority, **authority_edits.get(r.skill_name, {})})
            for rid, r in base.roles.items()
        }
        self.phases = base.phases
        self.registry_hash = registry_hash
        self.authority_registry = {"grant_contract": grant_contract}

    def get_role(self, role_id: str):
        try:
            return self.roles[role_id]
        except KeyError as exc:
            raise KeyError(f"unknown role_id: {role_id}") from exc

    def get_phase(self, phase_id: str):
        try:
            return self.phases[phase_id]
        except KeyError as exc:
            raise KeyError(f"unknown phase_id: {phase_id}") from exc


def variant_registries() -> dict[str, Any]:
    base = registry()
    contract = base.authority_registry.get("grant_contract", {})
    elevated = VariantRegistry(
        base, registry_hash="variant-elevated-" + "e" * 40,
        grant_contract={"required": [*contract.get("required", ())], "high_consequence_requires_exact_approval_ref": False},
        authority_edits={
            "project-manager": {"can_execute_irreversible": True, "can_execute_reversible_external": True},
            "media-planner": {"can_execute_reversible_external": True},
            "art-director": {"can_execute_irreversible": True},
        },
    )
    strict = VariantRegistry(
        base, registry_hash="variant-strict-" + "5" * 40,
        grant_contract={"required": [*contract.get("required", ()), "bogus_field"],
                        "high_consequence_requires_exact_approval_ref": True},
        authority_edits={"project-manager": {"can_execute_irreversible": True}},
    )
    return {"sealed": base, "elevated": elevated, "strict": strict}


def compact_registry(reg: Any) -> dict[str, Any]:
    authorities: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    roles = []
    for r in reg.roles.values():
        key = canon(r.runtime_authority)
        if key not in index:
            index[key] = len(authorities)
            authorities.append(r.runtime_authority)
        roles.append([r.role_id, r.title, r.skill_name, r.department, r.family, r.organizational_seniority,
                      list(r.capabilities), index[key]])
    phases = [[p.phase_id, list(p.orchestrator_ids), p.output_contract] for p in reg.phases.values()]
    return {"registry_hash": reg.registry_hash, "roles": roles, "authorities": authorities, "phases": phases,
            "grant_contract": reg.authority_registry.get("grant_contract", {})}


def write_or_load(path: Path, build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    if regenerate() or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(build(), separators=(",", ":"), ensure_ascii=True) + "\n")
    return json.loads(path.read_text())


def matches_stored(path: Path, fresh: dict[str, Any]) -> None:
    """Every stored case must still equal what Python returns now."""
    stored = json.loads(path.read_text())
    assert set(stored) == set(fresh), (path.name, set(stored) ^ set(fresh))
    for section, cases in fresh.items():
        assert canon(stored[section]) == canon(cases), (path.name, section)
