from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
from services.langgraph.persistence.sqlite_db import DB_PATH

def get_checkpointer():
    """
    Returns a LangGraph SqliteSaver checkpointer instance.
    The caller must ensure the connection remains open during execution.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return SqliteSaver(conn)
