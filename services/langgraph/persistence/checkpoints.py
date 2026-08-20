from __future__ import annotations

import atexit
import sqlite3
import threading
from typing import Any, Optional

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from services.langgraph.persistence.database import is_postgres, require_database_url
from services.langgraph.persistence.sqlite_db import DB_PATH

_SERDE = JsonPlusSerializer(allowed_msgpack_modules=[("services.langgraph.graph.models", "AgentRun")])
_LOCK = threading.Lock()
_CONNECTION: Optional[Any] = None
_CHECKPOINTER: Optional[Any] = None


def get_checkpointer():
    global _CONNECTION, _CHECKPOINTER
    with _LOCK:
        if _CHECKPOINTER is not None:
            return _CHECKPOINTER

        if is_postgres():
            import psycopg
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row

            conn = psycopg.connect(
                require_database_url(),
                autocommit=True,
                prepare_threshold=0,
                row_factory=dict_row,
            )
            saver = PostgresSaver(conn, serde=_SERDE)
            saver.setup()
            _CONNECTION = conn
            _CHECKPOINTER = saver
            return saver

        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        _CONNECTION = conn
        _CHECKPOINTER = SqliteSaver(conn, serde=_SERDE)
        return _CHECKPOINTER


def close_checkpointer() -> None:
    global _CONNECTION, _CHECKPOINTER
    with _LOCK:
        conn = _CONNECTION
        _CONNECTION = None
        _CHECKPOINTER = None
        if conn is not None:
            conn.close()


atexit.register(close_checkpointer)
