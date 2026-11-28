"""Read-only detection of which migrations a database already has (AMC keeps no migration ledger).

Runs only on an ephemeral local PostgreSQL server (AMC_EPHEMERAL_POSTGRES_DSN); otherwise skipped as NOT_RUN.
"""

import importlib.util
import os
from pathlib import Path

import pytest

DSN = os.environ.get("AMC_EPHEMERAL_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="AMC_EPHEMERAL_POSTGRES_DSN not set: migration detection NOT_RUN")
ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("db_migrations_detect", ROOT / "scripts/db_migrations.py")
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture(scope="module")
def signatures():
    return mig.migration_signatures(DSN)


def test_every_migration_has_a_detectable_signature(signatures):
    assert list(signatures) == [p.name for p in mig.migration_files()]
    assert [name for name, keys in signatures.items() if not keys] == []


@pytest.mark.parametrize("applied", [0, 1, 19, None])
def test_detection_names_exactly_the_applied_prefix_and_writes_nothing(signatures, applied):
    files = mig.migration_files()
    n = len(files) if applied is None else applied
    with mig.scratch_database(DSN) as db:
        mig.run_sql(db, mig.SHIM.read_text(encoding="utf-8"))
        for path in files[:n]:
            mig.run_sql(db, path.read_text(encoding="utf-8"))
        before = mig.snapshot_digest(mig.snapshot(db))
        report = mig.detect_applied(signatures, mig.readonly_snapshot(db))
        assert mig.snapshot_digest(mig.snapshot(db)) == before, "detection must not change the target"
    assert [r["state"] for r in report] == ["APPLIED"] * n + ["PENDING"] * (len(files) - n)


def test_a_half_applied_migration_is_partial_not_applied(signatures):
    files = mig.migration_files()
    with mig.scratch_database(DSN) as db:
        mig.apply_all(db, files)
        mig.run_sql(db, "drop index amc.idx_amc_approvals_brand_os_pending;")
        report = {r["migration"]: r for r in mig.detect_applied(signatures, mig.readonly_snapshot(db))}
    last = report["20261122_amc_brand_os_pending_approval_unique_v1.sql"]
    assert last["state"] == "PENDING" and last["missing_examples"]
    with mig.scratch_database(DSN) as db:
        mig.apply_all(db, files)
        mig.run_sql(db, "alter table amc.approvals disable row level security;")
        rls = {r["migration"]: r for r in mig.detect_applied(signatures, mig.readonly_snapshot(db))}
    assert rls["20261121_amc_tenant_rls_v1.sql"]["state"] == "PARTIAL"


def test_the_target_session_is_read_only():
    with mig.scratch_database(DSN) as db:
        mig.apply_all(db)
        psycopg = pytest.importorskip("psycopg")
        with psycopg.connect(db) as conn:
            conn.execute("set transaction read only")
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                conn.execute("create table amc.should_not_exist (x int)")


# ----------------------------------------------------------------------------- native decision fields (PG)
LAST = "20261122_amc_brand_os_pending_approval_unique_v1.sql"
RLS = "20261121_amc_tenant_rls_v1.sql"
HMAC = "20261104_amc_hmac_replay_v1.sql"
_DROP = "drop index amc.idx_amc_approvals_brand_os_pending;"
_COLS = "on amc.approvals (tenant_id, project_id, subject_ref, subject_type)"
_PRED = "where status = 'pending' and subject_type in ('BRAND_OS_SOP_ADOPTION', 'BRAND_OS_SOURCE')"


@pytest.fixture(scope="module")
def expectations():
    return mig.replay_expectations(DSN)


def _decide_after(expectations, sql):
    signatures, expected = expectations
    with mig.scratch_database(DSN) as db:
        mig.apply_all(db)
        if sql:
            mig.run_sql(db, sql)
        return {r["migration"]: r for r in mig.detect_applied(signatures, mig.readonly_snapshot(db), expected)}


def test_replay_expectations_agree_with_signatures(expectations, signatures):
    assert expectations[0] == signatures
    assert expectations[1]["server_major"] >= 15 and expectations[1]["objects"]


def test_fully_migrated_target_matches_and_needs_no_replay(expectations):
    report = _decide_after(expectations, None)
    assert {r["state"] for r in report.values()} == {"APPLIED"}
    assert {r["definition_status"] for r in report.values()} == {"MATCH"}
    assert {r["eligibility"] for r in report.values()} == {"INELIGIBLE"}
    assert all("ALREADY_PRESENT" in r["blockers"] for r in report.values())


def test_missing_index_is_pending_but_never_selectable(expectations):
    last = _decide_after(expectations, _DROP)[LAST]
    assert last["state"] == "PENDING" and last["eligibility"] == "INELIGIBLE"
    assert {"HISTORY_UNKNOWN", "DATA_EFFECT_UNPROVEN"} <= set(last["blockers"])


@pytest.mark.parametrize("sql", [
    _DROP + f" create unique index idx_amc_approvals_brand_os_pending {_COLS} where status = 'pending';",  # predicate
    _DROP + f" create index idx_amc_approvals_brand_os_pending {_COLS} {_PRED};",                         # uniqueness
    _DROP + " create unique index idx_amc_approvals_brand_os_pending on amc.approvals "
            f"(tenant_id, project_id, subject_type, subject_ref) {_PRED};",                                 # columns
], ids=["wrong-predicate", "not-unique", "column-order"])
def test_same_name_index_with_other_semantics_is_detected(expectations, sql):
    last = _decide_after(expectations, sql)[LAST]
    assert last["state"] == "APPLIED"  # the name is all the legacy state can see
    assert last["definition_status"] == "MISMATCH" and last["eligibility"] == "INELIGIBLE"


@pytest.mark.parametrize("sql", [
    "alter policy amc_tenant_isolation on amc.approvals using (true);",
    "create or replace function amc.current_tenant_id() returns text language sql stable as $$ select null::text $$;",
], ids=["policy-using-true", "function-body"])
def test_rewritten_rls_policy_or_function_is_detected(expectations, sql):
    rls = _decide_after(expectations, sql)[RLS]
    assert rls["definition_status"] == "MISMATCH" and "DEFINITION_MISMATCH" in rls["blockers"]


def test_a_dropped_earlier_migration_is_a_gap_not_pending_work(expectations):
    report = _decide_after(expectations, "drop table amc.hmac_replay_nonces;")
    assert report[HMAC]["state"] == "PENDING" and report[HMAC]["sequence_status"] == "GAP"
    assert report[HMAC]["eligibility"] == "INELIGIBLE"


def test_empty_target_without_history_is_never_eligible(expectations):
    signatures, expected = expectations
    with mig.scratch_database(DSN) as db:
        mig.run_sql(db, mig.SHIM.read_text(encoding="utf-8"))
        report = mig.detect_applied(signatures, mig.readonly_snapshot(db), expected)
    assert {r["state"] for r in report} == {"PENDING"}
    assert "ELIGIBLE_FOR_APPROVAL_REVIEW" not in {r["eligibility"] for r in report}
    assert {r["history_status"] for r in report} == {"UNKNOWN"}


def test_cli_detect_emits_decision_fields_and_leaves_the_target_unchanged(capsys):
    with mig.scratch_database(DSN) as db:
        mig.apply_all(db)
        mig.run_sql(db, _DROP)
        before = mig.snapshot_digest(mig.snapshot(db))
        assert mig.main(["detect", "--dsn", DSN, "--target", db]) == 0
        assert mig.snapshot_digest(mig.snapshot(db)) == before
    import json
    last = {r["migration"]: r for r in json.loads(capsys.readouterr().out)}[LAST]
    assert last["state"] == "PENDING" and last["eligibility"] == "INELIGIBLE"
