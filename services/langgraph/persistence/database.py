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
