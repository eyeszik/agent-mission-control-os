import os
import sqlite3

DB_PATH = os.environ.get("AMC_DB_PATH", "amc_local.db")

_MIGRATIONS = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            key TEXT PRIMARY KEY,
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS idempotency_records (
            scope TEXT NOT NULL,
            key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            result TEXT,
            error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            PRIMARY KEY (scope, key)
        );
        CREATE INDEX IF NOT EXISTS idx_idempotency_expires_at
            ON idempotency_records (expires_at);
        """,
    ),
]


def init_db() -> None:
    """Apply additive, versioned local SQLite schema migrations."""

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {
            row[0]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for version, script in _MIGRATIONS:
            if version in applied:
                continue
            conn.executescript(script)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        conn.commit()


def current_schema_version() -> int:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
        return int(row[0])
