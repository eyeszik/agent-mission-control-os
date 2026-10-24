-- Agency operating framework: per-project plans pinned to the immutable
-- 295-task catalog, and one instance row per task. Mirrors SQLite migration v20.
-- Additive only: evidence, artifacts, decisions, approvals and audit events stay
-- in their existing tables and are referenced, never copied. Grants nothing to
-- anon or authenticated Data API roles; the API service is the only writer.
--
-- Rollback (no other table references these):
--   DROP TABLE IF EXISTS amc.agency_task_instances;
--   DROP TABLE IF EXISTS amc.agency_framework_plans;

CREATE TABLE IF NOT EXISTS amc.agency_framework_plans (
    plan_id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES amc.tenants(tenant_id) ON DELETE CASCADE,
    project_id text NOT NULL REFERENCES amc.projects(project_id) ON DELETE CASCADE,
    catalog_id text NOT NULL,
    catalog_version text NOT NULL,
    catalog_sha256 text NOT NULL,
    archetype text NOT NULL,
    engagement_scope text NOT NULL DEFAULT '',
    created_by text NOT NULL,
    created_at text NOT NULL,
    UNIQUE (project_id, catalog_version)
);

CREATE TABLE IF NOT EXISTS amc.agency_task_instances (
    plan_id text NOT NULL REFERENCES amc.agency_framework_plans(plan_id) ON DELETE CASCADE,
    task_id text NOT NULL,
    tenant_id text NOT NULL,
    project_id text NOT NULL,
    module_id text NOT NULL,
    stage_gate text NOT NULL,
    applicability text NOT NULL CHECK (applicability IN ('UNASSESSED','REQUIRED','CONDITIONAL','NOT_APPLICABLE')),
    applicability_reason text,
    applicability_by text,
    state text NOT NULL CHECK (state IN ('BACKLOG','READY','ACTIVE','IN_REVIEW','VERIFIED','APPROVED','BLOCKED','INVALIDATED','NOT_APPLICABLE')),
    blocked_from text,
    status_reason text,
    assignee_role text NOT NULL,
    evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    artifact_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    decision_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    submitted_by text,
    verification jsonb,
    approval_ref text,
    version integer NOT NULL DEFAULT 0,
    updated_by text NOT NULL,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    PRIMARY KEY (plan_id, task_id)
);
CREATE INDEX IF NOT EXISTS idx_amc_agency_task_instances_project ON amc.agency_task_instances(project_id, module_id);

REVOKE ALL ON amc.agency_framework_plans, amc.agency_task_instances FROM anon, authenticated;
COMMENT ON TABLE amc.agency_task_instances IS
    'Project-scoped state of one catalog task. Starts BACKLOG/UNASSESSED; VERIFIED only via server re-check by a second person; APPROVED only by settling an existing approval bound to the proof hash.';
