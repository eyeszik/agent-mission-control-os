"""SQLite: idx_approvals_brand_os_pending is checked by definition, not by name, and never replaced silently."""

import sqlite3

import pytest

from services.langgraph.persistence import sqlite_db

_GOOD_TAIL = "(tenant_id, project_id, subject_ref, subject_type) " + sqlite_db._BRAND_OS_PENDING_PREDICATE


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "amc.db")
    monkeypatch.setattr(sqlite_db, "DB_PATH", path)
    return path


def _replace_index(path, statement):
    with sqlite3.connect(path) as conn:
        conn.execute("DROP INDEX idx_approvals_brand_os_pending")
        conn.execute(statement)


def test_fresh_database_index_matches_its_definition(db_path):
    sqlite_db.init_db()
    with sqlite3.connect(db_path) as conn:
        assert sqlite_db.brand_os_pending_index_problems(conn) == []
    sqlite_db.init_db()  # idempotent once present


@pytest.mark.parametrize("statement,problem", [
    ("CREATE INDEX idx_approvals_brand_os_pending ON approvals " + _GOOD_TAIL, "not unique"),
    ("CREATE UNIQUE INDEX idx_approvals_brand_os_pending ON approvals "
     "(tenant_id, project_id, subject_ref, subject_type) WHERE status = 'pending'", "predicate"),
    ("CREATE UNIQUE INDEX idx_approvals_brand_os_pending ON approvals "
     "(tenant_id, project_id, subject_ref, subject_type)", "predicate"),
    ("CREATE UNIQUE INDEX idx_approvals_brand_os_pending ON approvals "
     "(tenant_id, project_id, subject_type) " + sqlite_db._BRAND_OS_PENDING_PREDICATE, "columns"),
], ids=["not-unique", "wrong-predicate", "no-predicate", "missing-column"])
def test_same_name_index_with_another_definition_is_refused_not_replaced(db_path, statement, problem):
    sqlite_db.init_db()
    _replace_index(db_path, statement)
    with pytest.raises(RuntimeError, match=problem):
        sqlite_db.init_db()
    with sqlite3.connect(db_path) as conn:  # the operator's object is left exactly as it was
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'idx_approvals_brand_os_pending'").fetchone()
    assert sql[0] == statement
