"""Source-to-AGM reconciliation fails closed: orphans, edits, weak MATCHED claims and doc drift all fail."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("reconcile", ROOT / "scripts/verify_source_reconciliation.py")
reconcile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reconcile)


def _entries() -> list[dict]:
    return json.loads(reconcile.MAP.read_text(encoding="utf-8"))["entries"]


def test_the_committed_tree_reconciles_with_full_parity():
    report, problems = reconcile.build_report()
    assert problems == []
    assert report["result"] == "PASS"
    assert report["status_counts"]["MISSING"] == 0
    assert report["unresolved_drifted"] == 0
    assert all(p["status"] == "MATCHED" for p in report["parity"])


def test_a_new_source_without_a_mapping_is_an_orphan():
    sources = reconcile.extract_sources()
    sources["requirements_extract.json#/constraints/99"] = "A brand-new constraint"
    _, problems = reconcile.reconcile_entries(sources, _entries())
    assert "orphaned source requirements_extract.json#/constraints/99: no mapping entry" in problems


def test_an_edited_source_reports_drift_until_it_is_reviewed_again():
    sources = reconcile.extract_sources()
    sources["requirements_extract.json#/prohibitions/0"] = "Deploy freely."
    rows, problems = reconcile.reconcile_entries(sources, _entries())
    row = next(r for r in rows if r["source_id"] == "requirements_extract.json#/prohibitions/0")
    assert row["status"] == "DRIFTED" and not row["resolved"]
    assert any("content hash mismatch" in p for p in problems)


def test_matched_without_verification_is_rejected():
    entries = _entries()
    entry = next(e for e in entries if e["status"] == "MATCHED")
    entry["verification"] = []
    _, problems = reconcile.reconcile_entries(reconcile.extract_sources(), entries)
    assert f"{entry['source_id']}: MATCHED needs a target, an implementation and a verification" in problems


def test_an_unresolvable_reference_is_reported():
    entries = _entries()
    entries[0]["implementation"] = ["symbol:services/langgraph/graph/agency/nodes.py::does_not_exist"]
    _, problems = reconcile.reconcile_entries(reconcile.extract_sources(), entries)
    assert any("unresolved reference symbol:services/langgraph/graph/agency/nodes.py::does_not_exist" in p for p in problems)


def test_a_drifted_agm_doc_row_fails(monkeypatch, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(reconcile.DOC.read_text(encoding="utf-8").replace("| AGM-05 | Value Proposition & Offer Validation | 12 |",
                                                                      "| AGM-05 | Value Proposition & Offer Validation | 13 |"), encoding="utf-8")
    monkeypatch.setattr(reconcile, "DOC", doc)
    rows, problems = reconcile.reconcile_agm_doc()
    assert next(r for r in rows if r["source_id"].endswith("AGM-05"))["status"] == "DRIFTED"
    assert problems == ["AGM-05: tasks: doc='13' canonical='12'"]


@pytest.mark.parametrize("status", ["MISSING"])
def test_missing_is_never_a_pass(status):
    entries = _entries()
    entries[0]["status"] = status
    _, problems = reconcile.reconcile_entries(reconcile.extract_sources(), entries)
    assert f"{entries[0]['source_id']}: MISSING is unresolved" in problems
