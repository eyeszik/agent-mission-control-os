#!/usr/bin/env python3
"""Phase 0 discovery: bind the canonical AGM definition and the baseline paths.

Read-only. Writes ``acceptance/discovery_manifest.json`` with ``--write`` and
otherwise prints it. Exits 2 with status ``BLOCKED_AMBIGUOUS_SPEC`` when the AGM
definition is missing, ambiguous, or a required baseline path does not exist,
so later phases never build on a guessed specification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "acceptance/discovery_manifest.json"
OF = "services/langgraph/agency/operating_framework"

CANONICAL_AGM = {
    "definition": f"{OF}/data/catalog.seed-v1.json",
    "schema": f"{OF}/data/catalog.schema.json",
    "loader": f"{OF}/catalog.py",
    "bindings": f"{OF}/bindings.py",
    "documentation": "docs/agency-operating-framework.md",
}
REQUIRED_PATHS = {
    "operating_framework_engine": f"{OF}/engine.py",
    "execution_fabric": "services/langgraph/agency/execution_fabric/consumer.py",
    "durable_runtime": "services/langgraph/agency/durable/fsm.py",
    "intake": "services/langgraph/agency/intake/__init__.py",
    "project_os": "services/langgraph/agency/project_os/__init__.py",
    "agency_graph": "services/langgraph/graph/agency/build.py",
    "agency_nodes": "services/langgraph/graph/agency/nodes.py",
    "workflow_topology": "services/langgraph/agency/delivery/workflow.py",
    "n3_roles": "services/langgraph/agency/kernel/roles.py",
    "n2_lifecycle": "services/langgraph/agency/kernel/lifecycle.py",
    "sqlite_schema": "services/langgraph/persistence/sqlite_db.py",
    "postgres_migrations": "supabase/migrations",
    "ci_supabase_shim": "supabase/ci/supabase_shim.sql",
    "invariants_gate": "scripts/verify_repository_invariants.py",
    "core_constants_py": "services/langgraph/core/constants.py",
    "core_constants_ts": "packages/constants/src/index.ts",
    "openapi": "packages/shared/openapi/agent-mission-control.openapi.yaml",
}
ROOT_SPECS = [
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "Makefile", "README.md",
    "contract_architecture.json", "requirements_extract.json", "assumption_ledger.json",
    "constraint_ledger.yaml", "claim_registry.json", "fsm_spec.json", "task_dag.json",
    "execution_flow.json", "role_orchestration.json", "execution_trace.schema.json",
    "validation_report.json", "tool_proof_log.json", "system_layers.json",
]
AGM_ID = re.compile(r"\bAGM-\d{2}\b")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shape(value: object, depth: int = 0) -> object:
    """Key/type outline of a JSON document, two levels deep."""
    if isinstance(value, dict):
        if depth >= 2:
            return "object"
        return {key: shape(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def agm_binding() -> tuple[dict, list[str]]:
    problems: list[str] = []
    entry = {key: {"path": rel} for key, rel in CANONICAL_AGM.items()}
    for key, rel in CANONICAL_AGM.items():
        path = ROOT / rel
        if not path.is_file():
            problems.append(f"canonical AGM {key} missing: {rel}")
            continue
        entry[key]["sha256"] = sha256(path)
    if problems:
        return entry, problems
    catalog = json.loads((ROOT / CANONICAL_AGM["definition"]).read_text(encoding="utf-8"))
    loader = (ROOT / CANONICAL_AGM["loader"]).read_text(encoding="utf-8")
    pin = re.search(r'PINNED_CATALOG_SHA256\s*=\s*"([0-9a-f]{64})"', loader)
    module_ids = [m["module_id"] for m in catalog["modules"]]
    entry["catalog"] = {
        "catalog_id": catalog["catalog_id"],
        "schema_version": catalog["schema_version"],
        "pinned_sha256": pin.group(1) if pin else None,
        "pin_matches_bytes": bool(pin) and pin.group(1) == entry["definition"]["sha256"],
        "module_count": len(module_ids),
        "task_count": len(catalog["tasks"]),
        "module_ids": module_ids,
    }
    if not entry["catalog"]["pin_matches_bytes"]:
        problems.append("catalog bytes do not match PINNED_CATALOG_SHA256")
    if len(set(module_ids)) != len(module_ids) or len(module_ids) != catalog["module_count"]:
        problems.append("catalog module ids are not unique or disagree with module_count")
    return entry, problems


def agm_references() -> dict[str, list[str]]:
    """Every tracked file that names an AGM id, so a competing definition is visible."""
    found: dict[str, list[str]] = {}
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT).as_posix()
        if not path.is_file() or any(part in rel for part in ("node_modules/", ".git/", ".next/", "acceptance/")):
            continue
        if path.suffix not in {".py", ".ts", ".tsx", ".md", ".json", ".yaml", ".yml", ".sql"}:
            continue
        ids = sorted(set(AGM_ID.findall(path.read_text(encoding="utf-8", errors="ignore"))))
        if ids:
            found[rel] = ids
    return found


def competing_definitions(refs: dict[str, list[str]]) -> list[str]:
    """Files other than the canonical catalog that define modules (not just cite them)."""
    canonical = set(CANONICAL_AGM.values()) | {"packages/shared/tests/fixtures/agency-framework.json"}
    competing = []
    for rel in refs:
        if rel in canonical or not rel.endswith(".json"):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        if '"module_id"' in text and '"expected_task_count"' in text:
            competing.append(rel)
    return competing


def build() -> dict:
    binding, problems = agm_binding()
    paths = {key: {"path": rel, "exists": (ROOT / rel).exists()} for key, rel in REQUIRED_PATHS.items()}
    problems += [f"required path missing: {v['path']}" for v in paths.values() if not v["exists"]]
    refs = agm_references()
    competing = competing_definitions(refs)
    problems += [f"competing AGM definition: {rel}" for rel in competing]
    specs = {}
    for rel in ROOT_SPECS:
        path = ROOT / rel
        specs[rel] = {"exists": path.is_file(), "sha256": sha256(path) if path.is_file() else None}
    shapes = {rel: shape(json.loads((ROOT / rel).read_text(encoding="utf-8")))
              for rel in ("validation_report.json", "tool_proof_log.json", "claim_registry.json")}
    return {
        "schema": "amc-acceptance-discovery/v1",
        "status": "BLOCKED_AMBIGUOUS_SPEC" if problems else "BOUND",
        "problems": problems,
        "agm": {
            "meaning": "Agency Operating Framework module (AGM-01..AGM-24) in the version-pinned catalog",
            "precedence": [
                "catalog.seed-v1.json bytes (SHA-256 pinned in catalog.py) are the definition",
                "bindings.py maps modules to N3 roles and native owners; verify_bindings checks the live kernel",
                "docs/agency-operating-framework.md is a description and is reconciled against the catalog",
            ],
            "canonical": binding,
            "citing_files": refs,
            "competing_definitions": competing,
        },
        "required_paths": paths,
        "root_specs": specs,
        "root_spec_note": "The root JSON/YAML bundle is a pre-implementation planning bundle "
                          "(draft_until_verified); it is a reconciliation source, not runtime truth.",
        "report_schemas": shapes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write acceptance/discovery_manifest.json")
    args = parser.parse_args(argv)
    manifest = build()
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    print(f"discovery: {manifest['status']} ({len(manifest['problems'])} problems)", file=sys.stderr)
    return 0 if manifest["status"] == "BOUND" else 2


if __name__ == "__main__":
    raise SystemExit(main())
