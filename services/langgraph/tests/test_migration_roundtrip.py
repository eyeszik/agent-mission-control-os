"""Production migration mappings proven on an ephemeral PostgreSQL server.

Runs only when AMC_EPHEMERAL_POSTGRES_DSN names a maintenance database on a
local, disposable server (the tooling refuses any other host). Each test makes
its own scratch database and drops it. Without the DSN these tests are skipped
and must be reported NOT_RUN, never as passed.
"""

import importlib.util
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

DSN = os.environ.get("AMC_EPHEMERAL_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="AMC_EPHEMERAL_POSTGRES_DSN not set: migration round-trip NOT_RUN")

ROOT = Path(__file__).resolve().parents[3]
PRIOR_MIGRATION_BASELINE = "bb91590a"  # tree with migrations through 20261024_amc_agency_framework_v1
_spec = importlib.util.spec_from_file_location("db_migrations", ROOT / "scripts/db_migrations.py")
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_tooling_refuses_a_non_local_server():
    with pytest.raises(SystemExit, match="refusing non-local"):
        mig.assert_ephemeral("postgresql://amc@db.example.supabase.co:5432/postgres")


def test_committed_rollbacks_are_exactly_what_the_catalog_diff_generates():
    generated = mig.build_rollbacks(DSN)
    assert sorted(generated) == [p.name for p in mig.migration_files()]
    for name, sql in generated.items():
        assert mig.rollback_file(mig.MIGRATIONS / name).read_text(encoding="utf-8") == sql, name


def test_clean_init_rollback_and_remigrate_are_catalog_equivalent():
    with mig.scratch_database(DSN) as db:
        mig.run_sql(db, mig.SHIM.read_text(encoding="utf-8"))
        baseline = mig.snapshot(db)
        for path in mig.migration_files():
            mig.run_sql(db, path.read_text(encoding="utf-8"))
        migrated = mig.snapshot(db)
        mig.rollback_all(db)
        assert mig.snapshot(db) == baseline
        for path in mig.migration_files():
            mig.run_sql(db, path.read_text(encoding="utf-8"))
        assert mig.snapshot(db) == migrated


def test_every_single_migration_rolls_back_to_its_predecessor():
    with mig.scratch_database(DSN) as db:
        mig.run_sql(db, mig.SHIM.read_text(encoding="utf-8"))
        for path in mig.migration_files():
            before = mig.snapshot(db)
            mig.run_sql(db, path.read_text(encoding="utf-8"))
            mig.run_sql(db, mig.rollback_file(path).read_text(encoding="utf-8"))
            assert mig.snapshot(db) == before, path.name
            mig.run_sql(db, path.read_text(encoding="utf-8"))


def _baseline_files() -> dict[str, str]:
    present = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{PRIOR_MIGRATION_BASELINE}^{{commit}}"], capture_output=True)
    assert present.returncode == 0, (f"prior migration baseline {PRIOR_MIGRATION_BASELINE} is not in this clone; "
                                     "the upgrade path needs full history (actions/checkout fetch-depth: 0)")
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "--name-only", PRIOR_MIGRATION_BASELINE, "supabase/migrations/"],
                             capture_output=True, text=True, check=True).stdout.split()
    return {Path(p).name: subprocess.run(["git", "-C", str(ROOT), "show", f"{PRIOR_MIGRATION_BASELINE}:{p}"],
                                         capture_output=True, text=True, check=True).stdout for p in listing}


def test_incremental_upgrade_from_the_prior_baseline_equals_clean_init():
    prior = _baseline_files()
    current = {p.name: p.read_text(encoding="utf-8") for p in mig.migration_files()}
    assert prior and set(prior) < set(current)
    assert all(prior[name] == current[name] for name in prior), "an already-applied migration was edited in place"
    with mig.scratch_database(DSN) as clean:
        mig.apply_all(clean)
        expected = mig.snapshot(clean)
    with mig.scratch_database(DSN) as upgraded:
        mig.run_sql(upgraded, mig.SHIM.read_text(encoding="utf-8"))
        for name in sorted(prior):
            mig.run_sql(upgraded, prior[name])
        for name in sorted(set(current) - set(prior)):
            mig.run_sql(upgraded, current[name])
        assert mig.snapshot(upgraded) == expected


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("table", ["amc.approvals", "amc.tenant_memberships", "amc.runs"])
def test_data_api_roles_cannot_reach_tenant_data(role, table):
    psycopg = pytest.importorskip("psycopg")
    with mig.scratch_database(DSN) as db:
        mig.apply_all(db)
        with psycopg.connect(db) as conn:
            conn.execute(f"set role {role}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"select * from {table}")


def test_the_mapping_reports_exactly_the_rls_the_catalog_has():
    """REVOKE stays the outer layer; RLS is claimed only as far as the migrated catalog actually has it."""
    mapping = json.loads((ROOT / "acceptance/migration_mapping.json").read_text(encoding="utf-8"))
    rls = mapping["row_level_security"]
    assert rls["rls_enabled"] == rls["tables"] and rls["rls_forced"] == 0
    secured = [t["security"] for t in mapping["tables"] if t.get("security")]
    assert secured and all(s["rls_enabled"] for s in secured)
    assert all(s["policies"] == (["amc_tenant_isolation"] if s["tenant_scoped"] else []) for s in secured)
    assert rls["policies"] == sum(1 for s in secured if s["tenant_scoped"])
    assert mapping["schema_privileges"] == {"anon": {"amc_usage": False}, "authenticated": {"amc_usage": False}}


def test_every_unmapped_table_has_a_disposition_and_mapped_columns_all_exist():
    mapping = json.loads((ROOT / "acceptance/migration_mapping.json").read_text(encoding="utf-8"))
    assert mapping["summary"]["tables_without_disposition"] == []
    assert mapping["summary"]["columns"]["NOT_IN_POSTGRES"] == 0
    assert mapping["migrations"] == [p.name for p in mig.migration_files()]


def _seed_sqlite(path: Path) -> None:
    from services.langgraph.persistence import sqlite_db
    previous = sqlite_db.DB_PATH
    sqlite_db.DB_PATH = str(path)
    try:
        sqlite_db.init_db()
    finally:
        sqlite_db.DB_PATH = previous
    conn = sqlite3.connect(path)
    for tenant in ("tenant-a", "tenant-b"):
        conn.execute("insert into tenants values (?, ?, '2026-11-01 10:00:00')", (tenant, tenant.upper()))
        for i in range(3):
            project, run = f"{tenant}-p{i}", f"{tenant}-r{i}"
            conn.execute("insert into projects values (?, ?, ?, '2026-11-01T10:00:00+00:00')", (project, tenant, f"Project {i}"))
            conn.execute("insert into runs (run_id, tenant_id, project_id, pipeline, status, metadata, result, created_at, updated_at) "
                         "values (?, ?, ?, 'agency', 'needs_approval', ?, ?, '2026-11-01 10:00:00', '2026-11-01 10:05:00')",
                         (run, tenant, project, json.dumps({"brief": {"brand_name": "Ü"}}), json.dumps({"agency": {"n": i}})))
            conn.execute("insert into approvals (approval_id, run_id, tenant_id, project_id, reason, status, created_at, subject_hash) "
                         "values (?, ?, ?, ?, 'review', 'pending', '2026-11-01 10:06:00', ?)", (f"apr-{run}", run, tenant, project, "a" * 64))
    conn.commit()
    conn.close()


def test_tenant_scoped_backfill_is_chunked_idempotent_and_checksum_verified(tmp_path):
    source = tmp_path / "local.db"
    _seed_sqlite(source)
    tables = ["tenants", "projects", "runs", "approvals"]
    with mig.scratch_database(DSN) as db:
        mig.apply_all(db)
        first = mig.backfill(str(source), db, tables, tenant="tenant-a", chunk=2)
        again = mig.backfill(str(source), db, tables, tenant="tenant-a", chunk=2)
        assert [r["table"] for r in first] == tables  # FK order
        assert all(r["verified"] for r in first + again)
        assert [r["rows"] for r in first] == [1, 3, 3, 3] == [r["pg_rows"] for r in again]
        import psycopg
        with psycopg.connect(db) as conn:
            assert conn.execute("select count(*) from amc.runs where tenant_id = 'tenant-b'").fetchone()[0] == 0
            meta = conn.execute("select metadata->'brief'->>'brand_name', created_at from amc.runs where run_id='tenant-a-r0'").fetchone()
        assert meta[0] == "Ü" and meta[1].tzinfo is not None
