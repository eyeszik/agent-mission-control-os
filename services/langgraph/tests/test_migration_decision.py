"""Decision table for scripts/db_migrations.py detect: a catalog observation never becomes replay permission.

Pure classifier tests on synthetic catalog snapshots (no database). The native PostgreSQL counterparts are in
test_migration_detect.py. Each row's legacy fields (state, present, expected, missing_examples) are unchanged;
the decision fields are additive.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("db_migrations_decision", ROOT / "scripts/db_migrations.py")
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

LAST = "20261122_amc_brand_os_pending_approval_unique_v1.sql"  # has DML (marks duplicates stale)
FIRST = "20260820_amc_production_foundation_v1.sql"
IDX = ("index", "amc.approvals", "idx_amc_approvals_brand_os_pending")
TABLE = ("table", "amc.approvals")
GOOD, BAD = '{"unique": true}', '{"unique": false}'
LEGACY = {"migration", "state", "present", "expected", "missing_examples"}


def _snap(tables=("amc.approvals",), index_def=None, major=16):
    snap = {key: [] for key in mig._Q}
    snap["tables"] = [(t, True, False, "", "") for t in tables]
    objects = {}
    if index_def is not None:
        snap["indexes"] = [IDX[1:] + ("CREATE INDEX ...",)]
        objects[IDX] = index_def
    snap["definitions"] = {"server_major": major, "objects": objects}
    return snap


SIGS = {FIRST: {TABLE}, LAST: {IDX}}
EXPECTED = {"server_major": 16, "objects": {IDX: GOOD}}


def _rows(target, sigs=SIGS, expected=EXPECTED, history=None):
    return {r["migration"]: r for r in mig.detect_applied(sigs, target, expected, history)}


def test_legacy_fields_and_states_are_unchanged():
    rows = mig.detect_applied(SIGS, _snap())
    assert [(r["migration"], r["state"], r["present"], r["expected"]) for r in rows] == [(FIRST, "APPLIED", 1, 1),
                                                                                          (LAST, "PENDING", 0, 1)]
    assert all(LEGACY <= set(r) for r in rows)


def test_missing_index_after_applied_prefix_is_never_selectable():
    last = _rows(_snap())[LAST]
    assert last["state"] == "PENDING"  # legacy observation kept
    assert last["eligibility"] == "INELIGIBLE"
    assert {"HISTORY_UNKNOWN", "DATA_EFFECT_UNPROVEN"} <= set(last["blockers"])
    assert last["history_status"] == "UNKNOWN" and last["history_source"] is None
    assert last["reconciliation"] == "UNVERIFIABLE"


@pytest.mark.parametrize("index_def", [BAD, '{"unique": true, "predicate": null}'])
def test_same_name_index_with_other_semantics_is_a_mismatch(index_def):
    last = _rows(_snap(index_def=index_def))[LAST]
    assert last["state"] == "APPLIED"  # by name
    assert last["definition_status"] == "MISMATCH" and last["definition_mismatches"] == [list(IDX)]
    assert last["eligibility"] == "INELIGIBLE" and "DEFINITION_MISMATCH" in last["blockers"]


def test_matching_definitions_need_no_replay():
    last = _rows(_snap(index_def=GOOD))[LAST]
    assert last["definition_status"] == "MATCH"
    assert last["eligibility"] == "INELIGIBLE" and "ALREADY_PRESENT" in last["blockers"]


def test_definitions_from_another_major_version_are_unverifiable_not_matched():
    last = _rows(_snap(index_def=GOOD, major=17))[LAST]
    assert last["definition_status"] == "UNVERIFIABLE"
    assert "DEFINITIONS_NOT_COMPARED" in last["blockers"] and last["eligibility"] != "ELIGIBLE_FOR_APPROVAL_REVIEW"


def test_no_expected_definitions_means_unverifiable():
    last = _rows(_snap(index_def=GOOD), expected=None)[LAST]
    assert last["definition_status"] == "UNVERIFIABLE" and "DEFINITIONS_NOT_COMPARED" in last["blockers"]


def test_a_hole_in_the_applied_prefix_is_a_gap():
    rows = _rows(_snap(tables=(), index_def=GOOD))
    assert rows[FIRST]["state"] == "PENDING" and rows[FIRST]["sequence_status"] == "GAP"
    assert rows[FIRST]["eligibility"] == "INELIGIBLE" and "SEQUENCE_GAP" in rows[FIRST]["blockers"]
    assert rows[LAST]["sequence_status"] == "CONSISTENT"


def test_undetectable_and_partial_are_ineligible():
    sigs = {FIRST: set(), LAST: {IDX, TABLE}}
    rows = _rows(_snap(), sigs=sigs)
    assert rows[FIRST]["state"] == "UNDETECTABLE" and rows[FIRST]["sequence_status"] == "UNKNOWN"
    assert rows[FIRST]["eligibility"] == "INELIGIBLE"
    assert rows[LAST]["state"] == "PARTIAL" and "PARTIAL_EFFECTS" in rows[LAST]["blockers"]


@pytest.mark.parametrize("history,reconciliation,eligibility", [
    ("UNKNOWN", "UNVERIFIABLE", "INELIGIBLE"),          # DML file, unknown history
    ("APPLIED", "DIVERGENT", "INELIGIBLE"),             # history says applied, effects missing
    ("CONFLICTING", "AMBIGUOUS", "INELIGIBLE"),
    ("NOT_APPLIED", "PENDING", "ELIGIBLE_FOR_APPROVAL_REVIEW"),  # the only route to review
])
def test_history_drives_reconciliation_and_only_not_applied_reaches_review(history, reconciliation, eligibility):
    last = _rows(_snap(), history={LAST: history})[LAST]
    assert (last["reconciliation"], last["eligibility"]) == (reconciliation, eligibility)


def test_effects_without_recorded_history_are_divergent():
    last = _rows(_snap(index_def=GOOD), history={LAST: "NOT_APPLIED"})[LAST]
    assert last["reconciliation"] == "DIVERGENT" and last["eligibility"] == "INELIGIBLE"


def test_unknown_history_never_reaches_review_even_without_data_effects():
    sigs = {"no_dml.sql": {IDX}}  # not a real file: no data effects can be read
    row = _rows(_snap(), sigs=sigs)["no_dml.sql"]
    assert row["has_data_effects"] is False
    assert row["blockers"] == ["HISTORY_UNKNOWN"] and row["eligibility"] == "UNVERIFIABLE"


def test_data_effects_are_read_from_the_migration_files():
    assert mig._has_data_effects(LAST) and mig._has_data_effects("20260824_amc_trust_kernel_v1.sql")
    assert not mig._has_data_effects("20261121_amc_tenant_rls_v1.sql")


def test_a_later_file_is_never_eligible_while_an_earlier_one_is_not_applied_and_matching():
    # An earlier file whose index exists with another definition (history APPLIED), then a missing file that
    # history shows NOT_APPLIED: the playbook needs every earlier file applied with matching definitions.
    earlier_idx = ("index", "amc.approvals", "idx_earlier")
    sigs = {FIRST: {earlier_idx}, LAST: {IDX}}
    expected = {"server_major": 16, "objects": {earlier_idx: GOOD, IDX: GOOD}}
    target = _snap()
    target["indexes"] = [earlier_idx[1:] + ("CREATE INDEX ...",)]
    target["definitions"]["objects"] = {earlier_idx: BAD}
    rows = _rows(target, sigs=sigs, expected=expected, history={FIRST: "APPLIED", LAST: "NOT_APPLIED"})
    assert rows[FIRST]["definition_status"] == "MISMATCH" and rows[FIRST]["eligibility"] == "INELIGIBLE"
    assert rows[LAST]["reconciliation"] == "PENDING"
    assert "EARLIER_MIGRATION_NOT_APPLIED" in rows[LAST]["blockers"] and rows[LAST]["eligibility"] == "INELIGIBLE"


def test_only_the_first_missing_file_can_be_eligible_when_several_are_missing():
    middle = "20261121_amc_tenant_rls_v1.sql"  # no data effects
    sigs = {FIRST: {TABLE}, middle: {("function", "amc.current_tenant_id()")}, LAST: {IDX}}
    rows = _rows(_snap(), sigs=sigs, history={FIRST: "APPLIED", middle: "NOT_APPLIED", LAST: "NOT_APPLIED"})
    assert rows[middle]["eligibility"] == "ELIGIBLE_FOR_APPROVAL_REVIEW"
    assert rows[LAST]["eligibility"] == "INELIGIBLE" and "EARLIER_MIGRATION_NOT_APPLIED" in rows[LAST]["blockers"]
