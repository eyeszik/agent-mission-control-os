-- Mission council: ideas, engine state, checkpoints, blueprints and tool audits.
-- Mirrors SQLite migration v19. Additive only: a mission is an amc.runs row, so
-- status, approvals and run_events are reused. Grants nothing to anon or
-- authenticated Data API roles; the API service is the only writer.

CREATE TABLE IF NOT EXISTS amc.council_ideas (
    idea_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES amc.tenants(tenant_id) ON DELETE CASCADE,
    project_id text NOT NULL REFERENCES amc.projects(project_id) ON DELETE CASCADE,
    title text NOT NULL,
    description text NOT NULL,
    status text NOT NULL CHECK (status IN ('OPEN','PROMOTED')),
    created_by text NOT NULL,
    seed_key text,
    created_at text NOT NULL,
    updated_at text NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_amc_council_ideas_seed ON amc.council_ideas(tenant_id, seed_key) WHERE seed_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_amc_council_ideas_project ON amc.council_ideas(project_id, created_at);

CREATE TABLE IF NOT EXISTS amc.council_missions (
    mission_id text PRIMARY KEY REFERENCES amc.runs(run_id) ON DELETE CASCADE,
    idea_id text NOT NULL REFERENCES amc.council_ideas(idea_id) ON DELETE CASCADE,
    tenant_id text NOT NULL,
    project_id text NOT NULL,
    engine text NOT NULL CHECK (engine IN ('langgraph','crewai','autogen')),
    model_mode text NOT NULL CHECK (model_mode IN ('MOCK_DETERMINISTIC','PROVIDER')),
    phase text NOT NULL CHECK (phase IN ('STRATEGY','AUDIT','GATE','PROTOTYPE','DONE')),
    version integer NOT NULL DEFAULT 0,
    lease_owner text,
    lease_expires_at text,
    approval_id text,
    approval_subject_hash text,
    consumed_approval_id text,
    cancel_requested integer NOT NULL DEFAULT 0,
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    created_at text NOT NULL,
    updated_at text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_amc_council_missions_idea ON amc.council_missions(idea_id, created_at);
CREATE INDEX IF NOT EXISTS idx_amc_council_missions_project ON amc.council_missions(project_id, created_at);

CREATE TABLE IF NOT EXISTS amc.council_checkpoints (
    checkpoint_id text PRIMARY KEY,
    mission_id text NOT NULL REFERENCES amc.council_missions(mission_id) ON DELETE CASCADE,
    seq integer NOT NULL CHECK (seq >= 0),
    phase text NOT NULL,
    engine text NOT NULL,
    state jsonb NOT NULL,
    state_hash text NOT NULL,
    prev_hash text NOT NULL,
    native_checkpoint_id text,
    created_at text NOT NULL,
    UNIQUE (mission_id, seq)
);

CREATE TABLE IF NOT EXISTS amc.council_blueprints (
    blueprint_id text PRIMARY KEY,
    idea_id text NOT NULL REFERENCES amc.council_ideas(idea_id) ON DELETE CASCADE,
    tenant_id text NOT NULL,
    project_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('DRAFT','PROMOTED')),
    content jsonb NOT NULL,
    content_hash text NOT NULL,
    sources jsonb NOT NULL,
    verification jsonb,
    created_by text NOT NULL,
    created_at text NOT NULL,
    promoted_by text,
    promoted_at text
);
CREATE INDEX IF NOT EXISTS idx_amc_council_blueprints_idea ON amc.council_blueprints(idea_id, created_at);

CREATE TABLE IF NOT EXISTS amc.council_tool_audits (
    audit_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    project_id text NOT NULL,
    mission_id text,
    seat text,
    tool_id text NOT NULL,
    sensitivity text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('ALLOWED','DENIED','FAILED','TIMEOUT')),
    reason_code text NOT NULL,
    args_redacted jsonb NOT NULL,
    args_hash text NOT NULL,
    result_summary text,
    approval_id text,
    action_hash text,
    duration_ms integer,
    created_at text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_amc_council_tool_audits_mission ON amc.council_tool_audits(mission_id, created_at);

CREATE TABLE IF NOT EXISTS amc.council_approval_consumptions (
    approval_id text NOT NULL,
    mission_id text NOT NULL,
    action_hash text NOT NULL,
    consumed_by text NOT NULL,
    consumed_at text NOT NULL,
    PRIMARY KEY (approval_id, action_hash)
);

REVOKE ALL ON amc.council_ideas, amc.council_missions, amc.council_checkpoints, amc.council_blueprints,
    amc.council_tool_audits, amc.council_approval_consumptions FROM anon, authenticated;
COMMENT ON TABLE amc.council_approval_consumptions IS
    'One row per (approval, action) consumed by a mission resume or a sensitive tool call; the primary key prevents approval replay.';
