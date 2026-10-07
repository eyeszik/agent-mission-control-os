from services.langgraph.persistence.checkpoints import get_checkpointer


def test_get_checkpointer_returns_a_usable_saver():
    # SQLite connections return tuples; the Postgres saver's connection uses
    # psycopg's dict_row factory. Either way the connection must answer.
    checkpointer = get_checkpointer()
    assert checkpointer.conn is not None
    row = checkpointer.conn.execute("SELECT 1").fetchone()
    values = list(row.values()) if isinstance(row, dict) else list(row)
    assert values == [1]
