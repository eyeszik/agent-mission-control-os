#!/usr/bin/env python3
"""Source-to-AGM reconciliation and cross-stack semantic parity.

Extracts every requirement, assumption, constraint and claim from the root
planning sources with an immutable JSON-pointer id and a content hash, joins
them to ``acceptance/source_trace_map.json``, resolves every target,
implementation and verification reference against the tree, reconciles the
AGM module table in ``docs/agency-operating-framework.md`` against the pinned
catalog and ``bindings.py``, and checks Python / TypeScript / OpenAPI / AGM
vocabulary parity. Writes ``acceptance/reconciliation_report.json`` with
``--write``. Exits 1 on any orphaned source, unresolved reference, MISSING,
unresolved DRIFTED or parity failure. ``--pin`` records the reviewed content
hash of each mapped source; run it only after reviewing the mapping.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
MAP = ROOT / "acceptance/source_trace_map.json"
REPORT = ROOT / "acceptance/reconciliation_report.json"
CATALOG = ROOT / "services/langgraph/agency/operating_framework/data/catalog.seed-v1.json"
SOP = ROOT / "services/langgraph/agency/sop/data/sop_registry.v1.json"
DOC = ROOT / "docs/agency-operating-framework.md"
STATUSES = ("MATCHED", "PARTIAL", "MISSING", "DRIFTED", "PROVIDER_GAP", "NOT_MEASURED")
REQ_KINDS = ("objectives", "deliverables", "success_metrics", "constraints", "prohibitions", "non_goals", "conflicts")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def extract_sources() -> dict[str, object]:
    """Every source item keyed by an immutable JSON-pointer id."""
    sources: dict[str, object] = {}
    req = json.loads((ROOT / "requirements_extract.json").read_text(encoding="utf-8"))
    for kind in REQ_KINDS:
        for i, item in enumerate(req[kind]):
            sources[f"requirements_extract.json#/{kind}/{i}"] = item
    for i, item in enumerate(json.loads((ROOT / "assumption_ledger.json").read_text(encoding="utf-8"))["assumptions"]):
        sources[f"assumption_ledger.json#/assumptions/{i}"] = item
    for i, item in enumerate(json.loads((ROOT / "claim_registry.json").read_text(encoding="utf-8"))):
        sources[f"claim_registry.json#/{i}"] = item
    ledger = yaml.safe_load((ROOT / "constraint_ledger.yaml").read_text(encoding="utf-8"))
    for key, value in ledger.items():
        if key in ("version", "status"):
            continue
        if key == "agency_pipeline_decisions":
            for sub, item in value.items():
                sources[f"constraint_ledger.yaml#/{key}/{sub}"] = item
        else:
            sources[f"constraint_ledger.yaml#/{key}"] = value
    return sources


# --------------------------------------------------------------------- references
def _py_defines(path: Path, name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return True
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return True
    return False


def _symbol(rel: str, name: str) -> bool:
    path = ROOT / rel
    if not path.is_file():
        return False
    if path.suffix == ".py":
        return _py_defines(path, name)
    text = path.read_text(encoding="utf-8")
    return re.search(rf"\b(it|test)\(\s*['\"]{re.escape(name)}['\"]", text) is not None or f"export const {name}" in text


def _catalog_ids() -> set[str]:
    return {m["module_id"] for m in json.loads(CATALOG.read_text(encoding="utf-8"))["modules"]}


def _sop_ids() -> set[str]:
    registry = json.loads(SOP.read_text(encoding="utf-8"))
    return {s["sop_id"] for s in registry["steps"]} | {p["procedure_id"] for p in registry["procedures"]}


def _tables() -> set[str]:
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "supabase/migrations").glob("*.sql")))
    return set(re.findall(r"create table if not exists (amc\.[a-z_]+)", text, re.I))


def resolve(ref: str) -> bool:
    kind, _, value = ref.partition(":")
    if kind == "file":
        return (ROOT / value).exists()
    if kind in ("symbol", "test"):
        rel, _, name = value.partition("::")
        return bool(name) and _symbol(rel, name)
    if kind == "agm":
        return value in _catalog_ids()
    if kind == "sop":
        return value in _sop_ids()
    if kind == "table":
        return value in _tables()
    if kind == "check":
        return run_check(value)
    return False


# --------------------------------------------------------------------- machine checks
def _parses(rel: str) -> bool:
    path = ROOT / rel
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix == ".json":
            json.loads(text)
        elif path.suffix in (".yaml", ".yml"):
            yaml.safe_load(text)
        elif path.suffix == ".csv":
            return len(list(csv.reader(text.splitlines()))) > 1
    except (ValueError, yaml.YAMLError):
        return False
    return bool(text.strip())


def _task_dag_fields() -> bool:
    tasks = json.loads((ROOT / "task_dag.json").read_text(encoding="utf-8"))["tasks"]
    required = ("inputs", "outputs", "dependencies", "idempotency_class", "acceptance_checks", "failure_modes")
    classes = {"retry_safe", "guarded_retry", "non_retryable"}
    return all(all(k in t for k in required) and t["idempotency_class"] in classes and t["failure_modes"] for t in tasks)


def _claim_statuses() -> bool:
    claims = json.loads((ROOT / "claim_registry.json").read_text(encoding="utf-8"))
    return all(c["status"] in {"verified", "source_provided", "inferred", "verification_unavailable"} for c in claims)


def _deliverables_present() -> bool:
    deliverables = json.loads((ROOT / "requirements_extract.json").read_text(encoding="utf-8"))["deliverables"]
    return all(_parses(d) for d in deliverables)


def _bundle_is_data() -> bool:
    deliverables = json.loads((ROOT / "requirements_extract.json").read_text(encoding="utf-8"))["deliverables"]
    return all(Path(d).suffix in {".json", ".yaml", ".yml", ".md", ".csv"} for d in deliverables)


def _openapi_pipeline_enum() -> bool:
    from verify_repository_invariants import backend_stages, openapi_stages
    return backend_stages() == openapi_stages()


CHECKS = {
    "task_dag_fields": _task_dag_fields,
    "claim_statuses": _claim_statuses,
    "deliverables_present": _deliverables_present,
    "bundle_is_data": _bundle_is_data,
    "openapi_pipeline_enum": _openapi_pipeline_enum,
}


def run_check(spec: str) -> bool:
    name, _, arg = spec.partition(":")
    if name == "parses":
        return _parses(arg)
    return name in CHECKS and CHECKS[name]()


# --------------------------------------------------------------------- source entries
def _entry_problems(entry: dict, unresolved: list[str]) -> list[str]:
    sid, status = entry["source_id"], entry["status"]
    problems = [f"{sid}: unresolved reference {ref}" for ref in unresolved]
    if status not in STATUSES:
        return problems + [f"{sid}: unknown status {status}"]
    if status != "MATCHED" and not entry.get("note"):
        problems.append(f"{sid}: {status} needs a note")
    if status == "MATCHED" and not (entry["targets"] and entry["implementation"] and entry["verification"]):
        problems.append(f"{sid}: MATCHED needs a target, an implementation and a verification")
    if status == "PARTIAL" and not entry["implementation"]:
        problems.append(f"{sid}: PARTIAL needs the implementation that does exist")
    if status == "MISSING":
        problems.append(f"{sid}: MISSING is unresolved")
    if status == "DRIFTED" and not entry.get("resolution"):
        problems.append(f"{sid}: DRIFTED without a resolution is unresolved")
    return problems


def reconcile_entries(sources: dict[str, object], entries: list[dict]) -> tuple[list[dict], list[str]]:
    rows, problems = [], []
    mapped = {e["source_id"] for e in entries}
    problems += [f"orphaned source {sid}: no mapping entry" for sid in sources if sid not in mapped]
    problems += [f"stale mapping {sid}: no such source" for sid in mapped if sid not in sources]
    for entry in entries:
        sid = entry["source_id"]
        if sid not in sources:
            continue
        refs = [*entry["targets"], *entry["implementation"], *entry["verification"], *entry.get("resolution", [])]
        unresolved = [ref for ref in refs if not resolve(ref)]
        status = entry["status"]
        if entry.get("source_sha256") != digest(sources[sid]):
            status = "DRIFTED"
            problems.append(f"{sid}: source text changed since review (content hash mismatch)")
        problems += _entry_problems({**entry, "status": status}, unresolved)
        rows.append({"source_id": sid, "native_id": entry.get("native_id"), "status": status,
                     "resolved": not unresolved and (status != "DRIFTED" or bool(entry.get("resolution"))),
                     "targets": entry["targets"], "implementation": entry["implementation"],
                     "verification": entry["verification"], "resolution": entry.get("resolution", []),
                     "note": entry.get("note"), "unresolved_refs": unresolved})
    return rows, problems


# --------------------------------------------------------------------- AGM doc table
_ROW = re.compile(r"^\| (AGM-\d{2}) \| (.+?) \| (\d+) \| `([a-z_]+)` \| `([a-z_]+)` \| ([A-Z_0-9]+) \| (.+?) \| ([A-Z_]+) \| ([a-z]+) \|$")


def reconcile_agm_doc() -> tuple[list[dict], list[str]]:
    from services.langgraph.agency.operating_framework.bindings import binding
    catalog = {m["module_id"]: m for m in json.loads(CATALOG.read_text(encoding="utf-8"))["modules"]}
    doc_rows = {m.group(1): m.groups() for m in map(_ROW.match, DOC.read_text(encoding="utf-8").splitlines()) if m}
    rows, problems = [], []
    for module_id, module in catalog.items():
        found = doc_rows.get(module_id)
        if found is None:
            rows.append({"source_id": f"docs/agency-operating-framework.md#{module_id}", "status": "MISSING", "diffs": ["row absent"]})
            problems.append(f"{module_id}: no row in docs/agency-operating-framework.md")
            continue
        b = binding(module_id)
        expected = (module_id, module["title"], str(module["expected_task_count"]), b.n3_role, b.artifact_type,
                    b.coverage, b.native_owner, b.capability, b.external_effect)
        fields = ("module_id", "title", "tasks", "n3_role", "artifact_type", "coverage", "native_owner", "capability", "external_effect")
        diffs = [f"{f}: doc={d!r} canonical={c!r}" for f, d, c in zip(fields, found, expected) if d != c]
        rows.append({"source_id": f"docs/agency-operating-framework.md#{module_id}", "status": "DRIFTED" if diffs else "MATCHED",
                     "targets": [f"agm:{module_id}"], "diffs": diffs})
        problems += [f"{module_id}: {d}" for d in diffs]
    problems += [f"{m}: doc row for a module not in the catalog" for m in doc_rows if m not in catalog]
    return rows, problems


# --------------------------------------------------------------------- parity
def _ts_array(rel: str, name: str) -> list[str]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    match = re.search(rf"{name}\s*=\s*(?:z\.enum\()?\[(.*?)\]", text, re.S)
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)) if match else []


def _py_tuple(rel: str, name: str) -> list[str]:
    for node in ast.parse((ROOT / rel).read_text(encoding="utf-8")).body:
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id == name:
            return list(ast.literal_eval(node.value))
    return []


def _error_codes() -> tuple[set[str], set[str]]:
    py = set(re.findall(r'default_code[^=\n]*= "([A-Z_]+)"', (ROOT / "services/langgraph/core/errors.py").read_text(encoding="utf-8")))
    ts = set(re.findall(r"code: '([A-Z_]+)'", (ROOT / "packages/errors/src/index.ts").read_text(encoding="utf-8")))
    return py - {"AMC_ERROR"}, ts - {"INTERNAL", "UNKNOWN"}


def _openapi_run_states() -> list[str]:
    text = (ROOT / "packages/shared/openapi/agent-mission-control.openapi.yaml").read_text(encoding="utf-8")
    match = re.search(r"enum:\s*\[(running[^\]]*needs_approval[^\]]*)\]", text)
    return [s.strip() for s in match.group(1).split(",")] if match else []


def _agm_fixture_ids() -> set[str]:
    text = (ROOT / "packages/shared/tests/fixtures/agency-framework.json").read_text(encoding="utf-8")
    return set(re.findall(r'"module_id":\s*"(AGM-\d{2})"', text))


def parity_checks() -> list[dict]:
    from verify_repository_invariants import backend_stages, openapi_stages, shared_stages
    from services.langgraph.agency.operating_framework.bindings import MODULE_BINDINGS
    py_err, ts_err = _error_codes()
    run_py = _py_tuple("services/langgraph/core/constants.py", "AMC_AGENCY_RUN_STATES")
    sop = json.loads(SOP.read_text(encoding="utf-8"))
    fixture = json.loads((ROOT / "packages/shared/tests/fixtures/sop-registry.json").read_text(encoding="utf-8"))
    ontology = subprocess.run([sys.executable, "scripts/verify_ontology_parity.py"], cwd=ROOT, capture_output=True, text=True)
    checks = [
        ("pipeline_stages: python == shared zod == openapi", backend_stages() == shared_stages() == openapi_stages()),
        ("agency_run_states: python == @amc/constants == @amc/shared zod",
         run_py == _ts_array("packages/constants/src/index.ts", "AMC_AGENCY_RUN_STATES") == _ts_array("packages/shared/src/schemas/agency.ts", "AgencyRunStatusSchema")),
        ("agency_run_states: openapi lists every state", set(run_py) <= set(_openapi_run_states())),
        ("error_codes: core/errors.py == @amc/errors", bool(py_err) and py_err == ts_err),
        ("sop_ids: python registry == typescript fixture", sop == fixture),
        ("agm_ids: catalog == bindings.py", _catalog_ids() == set(MODULE_BINDINGS)),
        ("agm_ids: catalog ⊇ typescript fixture", _agm_fixture_ids() <= _catalog_ids() and bool(_agm_fixture_ids())),
        ("ontology/lifecycle: verify_ontology_parity.py", ontology.returncode == 0),
    ]
    return [{"check": name, "status": "MATCHED" if ok else "DRIFTED"} for name, ok in checks]


# --------------------------------------------------------------------- main
def build_report() -> tuple[dict, list[str]]:
    trace_map = json.loads(MAP.read_text(encoding="utf-8"))
    sources = extract_sources()
    rows, problems = reconcile_entries(sources, trace_map["entries"])
    doc_rows, doc_problems = reconcile_agm_doc()
    parity = parity_checks()
    problems += doc_problems + [f"parity: {p['check']}" for p in parity if p["status"] != "MATCHED"]
    all_rows = rows + doc_rows
    counts = {s: sum(1 for r in all_rows if r["status"] == s) for s in STATUSES}
    report = {
        "schema": "amc-reconciliation-report/v1",
        "result": "FAIL" if problems else "PASS",
        "sources": {"planning_items": len(sources), "agm_doc_rows": len(doc_rows), "total": len(all_rows)},
        "status_counts": counts,
        "unresolved_drifted": sum(1 for r in rows if r["status"] == "DRIFTED" and not r["resolved"]),
        "orphaned_sources": sum(1 for p in problems if p.startswith("orphaned source")),
        "excluded_source_kinds": trace_map["excluded_source_kinds"],
        "parity": parity,
        "problems": problems,
        "rows": all_rows,
    }
    return report, problems


def pin() -> int:
    trace_map = json.loads(MAP.read_text(encoding="utf-8"))
    sources = extract_sources()
    for entry in trace_map["entries"]:
        if entry["source_id"] in sources:
            entry["source_sha256"] = digest(sources[entry["source_id"]])
    MAP.write_text(json.dumps(trace_map, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"pinned {len(trace_map['entries'])} reviewed sources")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write acceptance/reconciliation_report.json")
    parser.add_argument("--pin", action="store_true", help="record reviewed source hashes in the trace map")
    args = parser.parse_args(argv)
    if args.pin:
        return pin()
    report, problems = build_report()
    if args.write:
        REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("result", "sources", "status_counts", "unresolved_drifted", "orphaned_sources")}))
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
