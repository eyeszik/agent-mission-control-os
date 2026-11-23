"""Tenant RLS enforcement edges (WO-04 follow-up), on an ephemeral PostgreSQL server only.

Covers what ``test_tenant_rls.py`` leaves open: privileged roles that bypass policies, why FORCE is not applied,
pooled connections not leaking tenant context, concurrent tenants on one pool, and API-level revoked or forged
identity. Every database here is a scratch database that is created and dropped by the test; nothing touches a
production role, database or setting. Skipped (NOT_RUN) without AMC_EPHEMERAL_POSTGRES_DSN.
"""

from __future__ import annotations

import os
import threading
import uuid
from contextlib import contextmanager
from urllib.parse import quote

import pytest

from services.langgraph.tests.test_tenant_rls import DSN, _as, _migrated_with_app_role, _tenants

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.skipif(not DSN, reason="AMC_EPHEMERAL_POSTGRES_DSN not set: tenant RLS NOT_RUN")


@contextmanager
def _extra_role(db: str, attributes: str):
    role = "amc_rls_priv_" + uuid.uuid4().hex[:8]
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute(f"create role {role} nologin {attributes}")
        conn.execute(f"grant usage on schema amc to {role}")
        conn.execute(f"grant select on all tables in schema amc to {role}")
    try:
        yield role
    finally:
        with psycopg.connect(db, autocommit=True) as conn:
            conn.execute(f"drop owned by {role}")
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(f"drop role if exists {role}")


def _problems(db: str, role: str | None) -> list[str]:
    from services.langgraph.persistence.database import DBSession, rls_enforcement_problems

    from psycopg.rows import dict_row

    with psycopg.connect(db, row_factory=dict_row) as conn:
        if role:
            conn.execute(f"set role {role}")
        return rls_enforcement_problems(DBSession(conn, True))


def test_the_application_role_is_constrained_and_privileged_roles_are_named_as_bypassing():
    with _migrated_with_app_role() as (db, role):
        assert _problems(db, role) == [], "a plain non-owner role is subject to every policy"
        assert any("OWNS_AMC_TABLES" in p or "SUPERUSER" in p for p in _problems(db, None)), "the owner is exempt"
        with _extra_role(db, "bypassrls") as privileged, psycopg.connect(db) as conn:
            assert any("BYPASSRLS" in p for p in _problems(db, privileged))
            _as(conn, privileged, "t_a")
            assert _tenants(conn) == ["t_a", "t_b"], "BYPASSRLS ignores the tenant context entirely"


def test_force_would_subject_the_owner_so_it_is_deliberately_not_applied():
    with _migrated_with_app_role() as (db, _), psycopg.connect(db) as conn:
        assert _tenants(conn) == ["t_a", "t_b"]
        conn.execute("alter table amc.projects force row level security")
        owner_is_super = conn.execute("select rolsuper from pg_roles where rolname = current_user").fetchone()[0]
        seen = _tenants(conn)
        conn.rollback()
    # Superusers bypass even FORCE; an ordinary owning role would see nothing without a tenant context.
    assert seen == (["t_a", "t_b"] if owner_is_super else [])


@contextmanager
def _pooled_backend(monkeypatch, db: str, role: str, size: int):
    from services.langgraph.persistence import database

    monkeypatch.setenv("AMC_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", f"{db}?options={quote(f'-c role={role}')}")
    monkeypatch.setenv("AMC_DB_RLS_MODE", "scoped")
    monkeypatch.setenv("AMC_DB_POOL_MAX", str(size))
    monkeypatch.setenv("AMC_DB_POOL_MIN", "0")
    previous, database._pool = database._pool, None
    try:
        yield database
    finally:
        if database._pool is not None:
            database._pool.close()
        database._pool = previous


def _read(database) -> list[str]:
    with database.transaction() as session:
        return [r["tenant_id"] for r in session.execute("select tenant_id from amc.projects order by 1").fetchall()]


def test_a_pooled_connection_never_carries_one_tenants_context_into_the_next_use(monkeypatch):
    with _migrated_with_app_role() as (db, role), _pooled_backend(monkeypatch, db, role, size=1) as database:
        assert database._pool_enabled()
        with database.tenant_scope("t_a"):
            assert _read(database) == ["t_a"]
        assert _read(database) == [], "same physical connection, no scope: fail closed"
        with database.tenant_scope("t_b"):
            assert _read(database) == ["t_b"]
        with pytest.raises(RuntimeError, match="boom"), database.tenant_scope("t_a"), database.transaction():
            raise RuntimeError("boom")
        assert _read(database) == [], "a rolled-back scoped transaction leaves no context behind"


def test_concurrent_tenants_on_one_pool_each_see_only_their_own_rows(monkeypatch):
    with _migrated_with_app_role() as (db, role), _pooled_backend(monkeypatch, db, role, size=2) as database:
        barrier, wrong, errors = threading.Barrier(4), [], []

        def worker(tenant: str):
            barrier.wait()
            try:
                for _ in range(25):
                    with database.tenant_scope(tenant):
                        seen = _read(database)
                    if seen != [tenant]:
                        wrong.append((tenant, seen))
            except Exception as exc:  # noqa: BLE001 - collected and asserted below, never swallowed
                errors.append(exc)
        threads = [threading.Thread(target=worker, args=(t,)) for t in ("t_a", "t_b", "t_a", "t_b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        assert errors == [] and wrong == []


# ----------------------------------------------------------------------------- API level, real membership rows
BACKEND_PG = os.environ.get("AMC_DATABASE_BACKEND") == "postgres" and bool(os.environ.get("DATABASE_URL"))


@pytest.fixture()
def supabase_mode(monkeypatch, tmp_path):
    if not BACKEND_PG:
        pytest.skip("NOT_RUN: membership resolution is PostgreSQL-only (AMC_DATABASE_BACKEND=postgres)")
    from services.langgraph.persistence.database import transaction
    from services.langgraph.persistence.projects import create_project_workspace
    from services.langgraph.security import auth

    tenant, other, pid = "t-mem-" + uuid.uuid4().hex[:8], "t-mem-o-" + uuid.uuid4().hex[:8], "p-mem-" + uuid.uuid4().hex[:8]
    user = str(uuid.uuid4())
    monkeypatch.setenv("AMC_EXPORT_ROOT", str(tmp_path))
    create_project_workspace(tenant_id=tenant, project_id=pid, actor=user, display_name="mem", export_root=tmp_path)
    create_project_workspace(tenant_id=other, project_id=pid + "-o", actor=user, display_name="other", export_root=tmp_path)
    with transaction(write=True) as db:
        db.execute("INSERT INTO auth.users (id) VALUES (?) ON CONFLICT DO NOTHING", (user,))
        db.execute("INSERT INTO amc.tenant_memberships (tenant_id, user_id, role, allowed_project_ids, active) "
                   "VALUES (?, ?, 'operator', ?, true)", (tenant, user, [pid]))
    monkeypatch.setenv("AMC_AUTH_MODE", "supabase")
    monkeypatch.setattr(auth, "_verify_supabase_user", lambda token: user)
    yield {"tenant": tenant, "other": other, "pid": pid, "user": user}
    with transaction(write=True) as db:
        db.execute("DELETE FROM amc.tenant_memberships WHERE user_id = ?", (user,))


def _adoption(pid: str, headers: dict | None = None):
    from services.langgraph.tests._project_os_support import client

    return client.get(f"/brand-os/projects/{pid}/sops/F01/adoption", headers={"Authorization": "Bearer t", **(headers or {})})


def test_an_active_member_is_served_and_a_forged_tenant_header_is_refused(supabase_mode):
    assert _adoption(supabase_mode["pid"]).status_code == 200
    forged = _adoption(supabase_mode["pid"] + "-o", {"X-AMC-Tenant": supabase_mode["other"]})
    assert forged.status_code == 403, "naming a tenant outside the membership grants nothing"
    assert _adoption(supabase_mode["pid"] + "-o").status_code in (403, 404), "the other tenant's project is not visible"


def test_a_revoked_membership_loses_access_on_the_next_request(supabase_mode):
    from services.langgraph.persistence.database import transaction

    assert _adoption(supabase_mode["pid"]).status_code == 200
    with transaction(write=True) as db:
        db.execute("UPDATE amc.tenant_memberships SET active = false WHERE user_id = ?", (supabase_mode["user"],))
    assert _adoption(supabase_mode["pid"]).status_code == 403
