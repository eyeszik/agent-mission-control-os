from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
import sqlite3
from services.langgraph.persistence.sqlite_db import DB_PATH

# GraphState checkpoints a pydantic AgentRun instance directly. Without this,
# the checkpointer emits "Deserializing unregistered type ... This will be
# blocked in a future version" on every read and will hard-fail once
# LANGGRAPH_STRICT_MSGPACK is enabled by default. Explicitly allow it.
_SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[("services.langgraph.graph.models", "AgentRun")]
)

def get_checkpointer():
    """
    Returns a LangGraph SqliteSaver checkpointer instance.
    The caller must ensure the connection remains open during execution.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return SqliteSaver(conn, serde=_SERDE)
