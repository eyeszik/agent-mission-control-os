"""Method catalog loader, validator and predicate evaluator.

The catalog (``data/method_catalog.v1.json``) is curated and extensible, never
claimed exhaustive. Each entry separates the factual description of a method
(name, purpose, aliases) from AMC's executable policy about it (slot, which
needs it covers, applicability predicates, relative effort). Provenance is
``DESCRIPTION_UNVERIFIED`` until a source is cited; the loader refuses a
``SOURCE_CITED`` entry without refs.

Predicates are a closed, tiny language evaluated against a ProblemSignature:

* ``<field>==<value>`` / ``<field>!=<value>``  (``true``/``false`` or a literal)
* ``<field> in a|b|c``
* ``observed:<fact>`` / ``not_observed:<fact>``
* ``family:<FAMILY_ID>`` / ``domain:<domain>``

All predicates in a list must hold. An unknown (``None``) boolean never
satisfies ``==true`` or ``==false``, so missing facts never make a method
applicable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .hashing import semantic_hash
from .method_models import FamilySpec, MethodSpec, ProblemSignature, Slot

CATALOG_PATH = Path(__file__).parent / "data" / "method_catalog.v1.json"
CATALOG_SCHEMA = "amc-method-catalog/v1"

_PRED = re.compile(
    r"^(?:(?P<field>[a-z_]+)(?P<op>==|!=)(?P<value>[A-Za-z0-9_\-]+)"
    r"|(?P<infield>[a-z_]+) in (?P<choices>[A-Za-z0-9_|\-]+)"
    r"|(?P<kind>observed|not_observed|family|domain):(?P<arg>[A-Za-z0-9_\-]+))$"
)


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class MethodCatalog:
    families: dict[str, FamilySpec]
    methods: dict[str, MethodSpec]
    catalog_hash: str

    def methods_covering(self, need: str) -> list[MethodSpec]:
        return [m for m in self.methods.values() if need in m.expected_outputs]

    def family_of(self, method_id: str) -> str:
        return self.methods[method_id].family


def _check_predicate(text: str, where: str) -> None:
    if not _PRED.match(text):
        raise CatalogError(f"{where}: unparseable predicate {text!r}")


def _literal(raw: str) -> Any:
    return {"true": True, "false": False}.get(raw, raw)


def evaluate_predicate(predicate: str, signature: ProblemSignature) -> bool:
    match = _PRED.match(predicate)
    if match is None:
        raise CatalogError(f"unparseable predicate {predicate!r}")
    if match.group("kind"):
        kind, arg = match.group("kind"), match.group("arg")
        if kind == "observed":
            return arg in signature.observations
        if kind == "not_observed":
            return arg not in signature.observations
        if kind == "family":
            return arg in signature.problem_families
        return arg in signature.domains
    if match.group("infield"):
        value = getattr(signature, match.group("infield"))
        return value is not None and str(value) in match.group("choices").split("|")
    value = getattr(signature, match.group("field"))
    expected = _literal(match.group("value"))
    if match.group("op") == "==":
        return value is not None and value == expected
    return value != expected


def all_hold(predicates: tuple[str, ...], signature: ProblemSignature) -> bool:
    return all(evaluate_predicate(p, signature) for p in predicates)


def any_holds(predicates: tuple[str, ...], signature: ProblemSignature) -> bool:
    return any(evaluate_predicate(p, signature) for p in predicates)


def parse_catalog(raw: dict[str, Any]) -> MethodCatalog:
    if raw.get("schema_version") != CATALOG_SCHEMA:
        raise CatalogError("unsupported catalog schema_version")
    families: dict[str, FamilySpec] = {}
    for item in raw.get("families") or []:
        family = FamilySpec.model_validate(item)
        if family.family_id in families:
            raise CatalogError(f"duplicate family {family.family_id}")
        families[family.family_id] = family
    methods: dict[str, MethodSpec] = {}
    for item in raw.get("methods") or []:
        method = MethodSpec.model_validate(item)
        if method.method_id in methods:
            raise CatalogError(f"duplicate method {method.method_id}")
        methods[method.method_id] = method

    for method in methods.values():
        for family in (method.family, *method.secondary_families):
            if family not in families:
                raise CatalogError(f"{method.method_id}: unknown family {family}")
        for predicate in (*method.applicability_predicates, *method.contraindications):
            _check_predicate(predicate, method.method_id)
        for ref in (*method.composable_with, *method.conflicts_with):
            if ref not in methods:
                raise CatalogError(f"{method.method_id}: unknown related method {ref}")
        for ref in method.conflicts_with:
            if method.method_id not in methods[ref].conflicts_with:
                raise CatalogError(f"conflict {method.method_id}/{ref} is not symmetric")
        if method.slot is Slot.MACRO and "macro:structured_cycle" not in method.expected_outputs:
            raise CatalogError(f"{method.method_id}: MACRO methods must cover macro:structured_cycle")

    covered = {need for m in methods.values() for need in m.expected_outputs}
    for family in families.values():
        missing = sorted(set(family.needs) - covered)
        if missing:
            raise CatalogError(f"{family.family_id}: needs with no covering method {missing}")
    return MethodCatalog(families=families, methods=methods, catalog_hash=semantic_hash(raw))


@lru_cache(maxsize=1)
def load_catalog(path: str = str(CATALOG_PATH)) -> MethodCatalog:
    return parse_catalog(json.loads(Path(path).read_text(encoding="utf-8")))
