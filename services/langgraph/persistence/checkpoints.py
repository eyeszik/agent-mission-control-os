import atexit
import sqlite3
import threading
from typing import Optional

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from services.langgraph.persistence.sqlite_db import DB_PATH

_SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[("services.langgraph.graph.models", "AgentRun")]
)
_LOCK = threading.Lock()
_CONNECTION: Optional[sqlite3.Connection] = None
_CHECKPOINTER: Optional[SqliteSaver] = None


def get_checkpointer() -> SqliteSaver:
    """Return one process-owned SQLite checkpointer with explicit lifecycle."""

    global _CONNECTION, _CHECKPOINTER
    with _LOCK:
        if _CHECKPOINTER is not None:
            return _CHECKPOINTER
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
