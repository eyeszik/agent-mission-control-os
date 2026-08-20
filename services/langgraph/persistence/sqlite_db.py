import os
import sqlite3

DB_PATH = os.environ.get("AMC_DB_PATH", "amc_local.db")

_MIGRATIONS = [
    (1, """CREATE TABLE IF NOT EXISTS idempotency_keys (key TEXT PRIMARY KEY, result TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"""),
    (2, """
        CREATE TABLE IF NOT EXISTS idempotency_records (
            scope TEXT NOT NULL, key TEXT NOT NULL, request_hash TEXT NOT NULL,
            status TEXT NOT NULL, result TEXT, error TEXT, attempt_count INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            PRIMARY KEY (scope, key)
        );
        CREATE INDEX IF NOT EXISTS idx_idempotency_expires_at ON idempotency_records (expires_at);
    """),
    (3, """
        CREATE TABLE IF NOT EXISTS run_events_v2 (
            event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
            sequence INTEGER NOT NULL, schema_version TEXT NOT NULL, event_type TEXT NOT NULL, node_id TEXT,
            observed_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, persisted_at TEXT NOT NULL,
            checkpoint_ref TEXT, safe_payload TEXT NOT NULL, redactions_applied TEXT NOT NULL,
            UNIQUE (run_id, sequence)
        );
        CREATE INDEX IF NOT EXISTS idx_run_events_v2_cursor ON run_events_v2 (run_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_run_events_v2_tenant ON run_events_v2 (tenant_id, project_id, run_id);
    """),
    (4, """
        CREATE TABLE IF NOT EXISTS analytics_events (
            event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, run_id TEXT,
            event_name TEXT NOT NULL, source TEXT NOT NULL, occurred_at TEXT NOT NULL,
            properties TEXT NOT NULL, schema_version TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_analytics_tenant_time ON analytics_events (tenant_id, project_id, occurred_at DESC);
        CREATE TABLE IF NOT EXISTS publication_jobs (
            job_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
            provider TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL, idempotency_key TEXT NOT NULL,
            payload TEXT NOT NULL, external_id TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (provider, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS spend_authorizations (
            authorization_id TEXT PRIMARY KEY, run_id TEXT, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
            provider TEXT NOT NULL, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL,
            requested_by TEXT NOT NULL, approved_by TEXT, reason TEXT NOT NULL, external_id TEXT,
            created_at TEXT NOT NULL, decided_at TEXT, executed_at TEXT
        );
    """),
]


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}
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
