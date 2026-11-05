from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from services.langgraph.persistence.sqlite_db import DB_PATH, init_db

_VALID_BACKENDS = {"sqlite", "postgres"}


def database_backend() -> str:
    value = (os.environ.get("AMC_DATABASE_BACKEND") or "sqlite").strip().lower()
    if value not in _VALID_BACKENDS:
        raise RuntimeError(f"Unsupported AMC_DATABASE_BACKEND={value!r}")
    return value


def is_postgres() -> bool:
    return database_backend() == "postgres"


def require_database_url() -> str:
    value = (os.environ.get("DATABASE_URL") or "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required when AMC_DATABASE_BACKEND=postgres")
    return value


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
    if isinstance(value, str):
        return json.loads(value)
    return value


def normalize_record(row: Any) -> dict:
    record = dict(row)
    for key, value in list(record.items()):
        if isinstance(value, datetime):
            record[key] = value.isoformat()
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
            yield session
            conn.commit()
        except Exception:
            conn.rollback()
            raise


@contextmanager
def transaction(*, write: bool = False) -> Iterator[DBSession]:
    postgres = is_postgres()
    if not postgres:
        init_db()
        conn = sqlite3.connect(DB_PATH, isolation_level=None)
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
