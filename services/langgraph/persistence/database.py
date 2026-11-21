from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Iterator
from uuid import UUID

from services.langgraph.core.constants import AMC_DATABASE_BACKENDS, DB_BACKEND_POSTGRES, DB_BACKEND_SQLITE
from services.langgraph.persistence import sqlite_db

_VALID_BACKENDS = frozenset(AMC_DATABASE_BACKENDS)
_JOINED_SESSION: ContextVar[Any] = ContextVar("amc_explicit_atomic_session", default=None)
# Tenant context for PostgreSQL row-level security (supabase/migrations/20261121_amc_tenant_rls_v1.sql).
RLS_MODE_ENV = "AMC_DB_RLS_MODE"
RLS_MODES = ("off", "scoped")
_TENANT_SCOPE: ContextVar[str | None] = ContextVar("amc_tenant_scope", default=None)


def database_backend() -> str:
    value = (os.environ.get("AMC_DATABASE_BACKEND") or DB_BACKEND_SQLITE).strip().lower()
    if value not in _VALID_BACKENDS:
        raise RuntimeError(f"Unsupported AMC_DATABASE_BACKEND={value!r}")
    return value


def is_postgres() -> bool:
    return database_backend() == DB_BACKEND_POSTGRES


def require_database_url() -> str:
    value = (os.environ.get("DATABASE_URL") or "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required when AMC_DATABASE_BACKEND=postgres")
    return value


def rls_mode() -> str:
    """``off`` (default): no tenant context is sent. ``scoped``: an active :func:`tenant_scope` is sent
    to PostgreSQL as ``amc.tenant_id`` for the transaction. Unknown values fail closed."""
    value = (os.environ.get(RLS_MODE_ENV) or "off").strip().lower()
    if value not in RLS_MODES:
        raise RuntimeError(f"Unsupported {RLS_MODE_ENV}={value!r}; expected one of {RLS_MODES}")
    return value


@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[None]:
    """Bind database work in this context to one tenant for row-level security.

    It narrows, never widens: the tenant must come from the server-resolved
    principal, and an inner scope may not switch to a different tenant.
    """
    tenant = (tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_scope requires a non-empty tenant_id")
    outer = _TENANT_SCOPE.get()
    if outer is not None and outer != tenant:
        raise PermissionError("a tenant scope cannot be switched to another tenant inside an outer scope")
    token = _TENANT_SCOPE.set(tenant)
    try:
        yield
    finally:
        _TENANT_SCOPE.reset(token)


def current_tenant_scope() -> str | None:
    return _TENANT_SCOPE.get()


def _apply_tenant_scope(conn: Any) -> None:
    """Transaction-local, so a pooled connection never carries one tenant's context into the next use."""
    tenant = _TENANT_SCOPE.get()
    if tenant is not None and rls_mode() == "scoped":
        conn.execute("SELECT set_config('amc.tenant_id', %s, true)", (tenant,))


def table(name: str) -> str:
    if is_postgres():
        return f"amc.{name}"
    if name == "run_events":
        return "run_events_v2"
    return name


def json_param(value: Any) -> Any:
    if is_postgres():
        from psycopg.types.json import Jsonb

        return Jsonb(value)
    return json.dumps(value)


def decode_json(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    # SQLite stores JSON as text. psycopg already decodes json/jsonb columns,
    # so on PostgreSQL a str is a JSON string value (e.g. jsonb '"Option A"')
    # and must not be parsed a second time.
    if isinstance(value, str) and not is_postgres():
        return json.loads(value)
    return value


def normalize_record(row: Any) -> dict:
    record = dict(row)
    for key, value in list(record.items()):
        if isinstance(value, datetime):
            record[key] = value.isoformat()
        elif isinstance(value, UUID):
            # PostgreSQL uuid columns decode to uuid.UUID; SQLite stores text.
            # Normalize so records serialize identically on both backends.
            record[key] = str(value)
    return record


class DBSession:
    def __init__(self, conn: Any, postgres: bool) -> None:
        self._conn = conn
        self._postgres = postgres

    def execute(self, query: str, params: tuple | list = ()):
        sql = query.replace("?", "%s") if self._postgres else query
        return self._conn.execute(sql, params)


_pool: Any = None


def _pool_enabled() -> bool:
    """Postgres connection pooling is opt-in via AMC_DB_POOL_MAX > 0."""

    if not is_postgres():
        return False
    try:
        return int((os.environ.get("AMC_DB_POOL_MAX") or "0").strip() or "0") > 0
    except ValueError:
        return False


def _get_pool():
    """Shared psycopg_pool for production Postgres, sized by env. Settings:
    AMC_DB_POOL_MIN (default 0), AMC_DB_POOL_MAX, AMC_DB_POOL_TIMEOUT
    (connection acquire wait, seconds)."""

    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool

        min_size = int((os.environ.get("AMC_DB_POOL_MIN") or "0").strip() or "0")
        max_size = int((os.environ.get("AMC_DB_POOL_MAX") or "4").strip() or "4")
        timeout = float((os.environ.get("AMC_DB_POOL_TIMEOUT") or "10").strip() or "10")
        _pool = ConnectionPool(
            require_database_url(),
            min_size=0 if min_size < 0 else min_size,
            max_size=max_size,
            timeout=timeout,
            open=True,
        )
    return _pool


def pool_stats() -> dict:
    """Health/observability hook: queue, size and error counters of the pool."""

    if not _pool_enabled() or _pool is None:
        return {"enabled": False}
    stats = getattr(_pool, "get_stats", None)
    if not callable(stats):
        return {"enabled": True}
    return {"enabled": True, **dict(stats())}


@contextmanager
def _pooled_session() -> Iterator[DBSession]:
    pool = _get_pool()
    with pool.connection() as conn:
        session = DBSession(conn, True)
        try:
            _apply_tenant_scope(conn)
            yield session
            conn.commit()
        except Exception:
            conn.rollback()
            raise


@contextmanager
def transaction(*, write: bool = False) -> Iterator[DBSession]:
    joined = _JOINED_SESSION.get()
    if joined is not None:
        yield joined
        return
    postgres = is_postgres()
    if not postgres:
        # Resolve the path at call time so init_db() and this connection always
        # target the same file, even if sqlite_db.DB_PATH was repointed.
        sqlite_db.init_db()
        conn = sqlite3.connect(sqlite_db.DB_PATH, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        if write:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield DBSession(conn, False)
            if write:
                conn.commit()
        except Exception:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()
        return

    if _pool_enabled():
        yield from _pooled_session()
        return

    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(
        require_database_url(),
        autocommit=False,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    try:
        _apply_tenant_scope(conn)
        yield DBSession(conn, True)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ping_database() -> bool:
    with transaction() as db:
        row = db.execute("SELECT 1 AS ok").fetchone()
        return bool(row and row["ok"] == 1)


@contextmanager
def atomic_transaction() -> Iterator[DBSession]:
    """Explicitly compose existing persistence APIs into one transaction.

    Ordinary callers keep their previous behavior. Only code inside this
    scope joins a session; escaping exceptions roll the entire scope back.
    Never enter this scope across an await or around untrusted worker code.
    """
    with transaction(write=True) as db:
        token = _JOINED_SESSION.set(db)
        try:
            yield db
        finally:
            _JOINED_SESSION.reset(token)
