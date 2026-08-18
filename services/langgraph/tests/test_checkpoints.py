from services.langgraph.persistence.checkpoints import get_checkpointer

def test_get_checkpointer_returns_usable_sqlite_backed_saver():
    checkpointer = get_checkpointer()
    assert checkpointer.conn is not None
    cur = checkpointer.conn.execute("SELECT 1")
    assert cur.fetchone() == (1,)
