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
    (5, """
        CREATE TABLE IF NOT EXISTS engagements (
            engagement_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            objective TEXT NOT NULL,
            desired_outcome TEXT NOT NULL,
            status TEXT NOT NULL,
            constraints TEXT NOT NULL,
            permissions TEXT NOT NULL,
            metadata TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_engagements_tenant_project ON engagements (tenant_id, project_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_engagements_status ON engagements (status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS workstreams (
            workstream_id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL REFERENCES engagements(engagement_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            department TEXT NOT NULL,
            objective TEXT NOT NULL,
            status TEXT NOT NULL,
            dependencies TEXT NOT NULL,
            acceptance_criteria TEXT NOT NULL,
            permissions TEXT NOT NULL,
            metadata TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_workstreams_engagement ON workstreams (engagement_id, status, created_at);

        CREATE TABLE IF NOT EXISTS agency_evidence (
            evidence_id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL REFERENCES engagements(engagement_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            source_ref TEXT,
            claim TEXT NOT NULL,
            epistemic_status TEXT NOT NULL,
            confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
            collected_at TEXT NOT NULL,
            freshness_seconds INTEGER CHECK (freshness_seconds IS NULL OR freshness_seconds >= 0),
            payload TEXT NOT NULL,
            metadata TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agency_evidence_engagement ON agency_evidence (engagement_id, epistemic_status, collected_at DESC);

        CREATE TABLE IF NOT EXISTS agency_decisions (
            decision_id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL REFERENCES engagements(engagement_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            question TEXT NOT NULL,
            alternatives TEXT NOT NULL,
            selected_option TEXT NOT NULL,
            evidence_ids TEXT NOT NULL,
            assumptions TEXT NOT NULL,
            affected_artifact_ids TEXT NOT NULL,
            confidence TEXT NOT NULL,
            status TEXT NOT NULL,
            approver TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agency_decisions_engagement ON agency_decisions (engagement_id, status, created_at DESC);

        CREATE TABLE IF NOT EXISTS agency_artifacts (
            artifact_id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL REFERENCES engagements(engagement_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            workstream_id TEXT REFERENCES workstreams(workstream_id) ON DELETE SET NULL,
            artifact_type TEXT NOT NULL,
            subtype TEXT,
            owner_department TEXT NOT NULL,
            version INTEGER NOT NULL CHECK (version > 0),
            status TEXT NOT NULL,
            content_location TEXT,
            content_hash TEXT,
            semantic_fingerprint TEXT,
            assumptions TEXT NOT NULL,
            validation TEXT NOT NULL,
            approval TEXT NOT NULL,
            metadata TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agency_artifacts_engagement ON agency_artifacts (engagement_id, status, artifact_type);
        CREATE INDEX IF NOT EXISTS idx_agency_artifacts_workstream ON agency_artifacts (workstream_id) WHERE workstream_id IS NOT NULL;

        CREATE TABLE IF NOT EXISTS artifact_dependencies (
            artifact_id TEXT NOT NULL REFERENCES agency_artifacts(artifact_id) ON DELETE CASCADE,
            depends_on_artifact_id TEXT NOT NULL REFERENCES agency_artifacts(artifact_id) ON DELETE CASCADE,
            relationship TEXT NOT NULL CHECK (relationship IN ('hard', 'soft')),
            created_at TEXT NOT NULL,
            PRIMARY KEY (artifact_id, depends_on_artifact_id),
            CHECK (artifact_id <> depends_on_artifact_id)
        );
        CREATE INDEX IF NOT EXISTS idx_artifact_dependencies_upstream ON artifact_dependencies (depends_on_artifact_id, artifact_id);
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
