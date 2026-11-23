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
