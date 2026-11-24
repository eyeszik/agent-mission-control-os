"""Tenant row-level security (WO-04) proven on an ephemeral PostgreSQL server.

Three isolation options are layered (docs/migrations/tenant-rls.md):

1. schema REVOKE from the Data API roles (already covered by test_migration_roundtrip.py);
2. RLS enabled with ``amc_tenant_isolation`` on every tenant table, with the owning role exempt;
3. a non-owner application role plus ``AMC_DB_RLS_MODE=scoped`` and ``tenant_scope``.

Runs only when AMC_EPHEMERAL_POSTGRES_DSN names a local, disposable server; otherwise every test
is skipped and must be reported NOT_RUN. Each test makes and drops its own scratch database.
"""

import importlib.util
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import pytest

DSN = os.environ.get("AMC_EPHEMERAL_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="AMC_EPHEMERAL_POSTGRES_DSN not set: tenant RLS NOT_RUN")

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("db_migrations_rls", ROOT / "scripts/db_migrations.py")
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)
psycopg = pytest.importorskip("psycopg")


@contextmanager
def _migrated_with_app_role():
    """A scratch database at the latest migration, two tenants' rows, and a non-owner app role."""
    role = "amc_rls_app_" + uuid.uuid4().hex[:8]
    with mig.scratch_database(DSN) as db:
        mig.apply_all(db)
        with psycopg.connect(db, autocommit=True) as conn:
            conn.execute(f"create role {role} nologin")
            conn.execute(f"grant usage on schema amc to {role}")
            conn.execute(f"grant select, insert, update, delete on all tables in schema amc to {role}")
            conn.execute("insert into amc.tenants (tenant_id, name) values ('t_a', 'A'), ('t_b', 'B')")
            conn.execute("insert into amc.projects (project_id, tenant_id, name) values ('p_a', 't_a', 'A'), ('p_b', 't_b', 'B')")
        try:
            yield db, role
        finally:
            with psycopg.connect(db, autocommit=True) as conn:
                conn.execute(f"drop owned by {role}")
            with psycopg.connect(DSN, autocommit=True) as conn:
                conn.execute(f"drop role if exists {role}")


def _as(conn, role, tenant=None):
    conn.execute(f"set role {role}")
    if tenant is not None:
        conn.execute("select set_config('amc.tenant_id', %s, false)", (tenant,))


def _tenants(conn) -> list[str]:
    return [r[0] for r in conn.execute("select tenant_id from amc.projects order by tenant_id").fetchall()]


def test_every_amc_table_has_rls_and_every_tenant_table_has_the_isolation_policy():
    with mig.scratch_database(DSN) as db:
        mig.apply_all(db)
        with psycopg.connect(db) as conn:
            rows = conn.execute(
                """select c.relname, c.relrowsecurity, c.relforcerowsecurity,
                          exists (select 1 from pg_attribute a where a.attrelid = c.oid and a.attname = 'tenant_id'
                                  and a.attnum > 0 and not a.attisdropped),
                          exists (select 1 from pg_policies p where p.schemaname = 'amc' and p.tablename = c.relname
                                  and p.policyname = 'amc_tenant_isolation')
                     from pg_class c join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = 'amc' and c.relkind = 'r'""").fetchall()
    assert rows
    assert [r[0] for r in rows if not r[1]] == [], "tables without row-level security"
    assert [r[0] for r in rows if r[2]] == [], "FORCE would subject the owning backend role to tenant context"
    assert [r[0] for r in rows if r[3] != r[4]] == [], "tenant_id tables must carry exactly the isolation policy"


def test_the_owning_backend_role_is_unaffected_option_2():
    with _migrated_with_app_role() as (db, _):
        with psycopg.connect(db) as conn:
            assert _tenants(conn) == ["t_a", "t_b"]


def test_app_role_without_tenant_context_sees_nothing_fail_closed():
    with _migrated_with_app_role() as (db, role):
        with psycopg.connect(db) as conn:
            _as(conn, role)
            assert _tenants(conn) == []


def test_app_role_sees_only_its_tenant_and_cannot_write_or_move_rows_across_tenants_option_3():
    with _migrated_with_app_role() as (db, role):
        with psycopg.connect(db) as conn:
            _as(conn, role, "t_a")
            assert _tenants(conn) == ["t_a"]
            assert conn.execute("update amc.projects set name = 'x' where tenant_id = 't_b'").rowcount == 0
            assert conn.execute("delete from amc.projects where project_id = 'p_b'").rowcount == 0
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("update amc.projects set tenant_id = 't_b' where project_id = 'p_a'")
        with psycopg.connect(db) as conn:
            _as(conn, role, "t_a")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("insert into amc.projects (project_id, tenant_id, name) values ('p_x', 't_b', 'X')")


def test_tables_without_tenant_id_deny_the_app_role_entirely():
    with _migrated_with_app_role() as (db, role):
        with psycopg.connect(db, autocommit=True) as conn:
            conn.execute("""insert into amc.idempotency_records (scope, key, request_hash, status, created_at, updated_at,
                            expires_at) values ('s', 'k', 'h', 'completed', now(), now(), now() + interval '1 day')""")
        with psycopg.connect(db) as conn:
            _as(conn, role, "t_a")
            assert conn.execute("select count(*) from amc.idempotency_records").fetchone()[0] == 0


def _backend_env(monkeypatch, db: str, role: str, mode: str) -> None:
    monkeypatch.setenv("AMC_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", f"{db}?options={quote(f'-c role={role}')}")
    monkeypatch.setenv("AMC_DB_RLS_MODE", mode)
    monkeypatch.delenv("AMC_DB_POOL_MAX", raising=False)


def test_backend_transaction_sends_the_tenant_scope_only_in_scoped_mode(monkeypatch):
    from services.langgraph.persistence.database import tenant_scope, transaction

    def read() -> list[str]:
        with transaction() as session:
            return [r["tenant_id"] for r in session.execute("select tenant_id from amc.projects order by 1").fetchall()]

    with _migrated_with_app_role() as (db, role):
        _backend_env(monkeypatch, db, role, "scoped")
        assert read() == []
        with tenant_scope("t_b"):
            assert read() == ["t_b"]
        assert read() == [], "the scope is transaction-local and does not leak to later transactions"
        _backend_env(monkeypatch, db, role, "off")
        with tenant_scope("t_b"):
            assert read() == [], "off mode sends no context, so a non-owner role sees nothing"


def test_rollback_restores_the_pre_rls_catalog():
    files = mig.migration_files()
    names = [f.name for f in files]
    rls = names.index("20261121_amc_tenant_rls_v1.sql")  # later migrations may follow it; roll back only this one
    with mig.scratch_database(DSN) as db:
        mig.apply_all(db, files[:rls])
        before = mig.snapshot(db)
        mig.apply_all(db, files[rls:rls + 1])
        mig.run_sql(db, mig.rollback_file(files[rls]).read_text(encoding="utf-8"))
        assert mig.snapshot_digest(mig.snapshot(db)) == mig.snapshot_digest(before)
