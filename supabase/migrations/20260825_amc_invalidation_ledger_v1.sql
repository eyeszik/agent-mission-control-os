CREATE TABLE IF NOT EXISTS amc.invalidation_obligations (
    obligation_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    artifact_branch TEXT NOT NULL,
    node_id TEXT NOT NULL,
    event_class TEXT NOT NULL CHECK (event_class IN (
        'SPEC_CHANGE',
        'MODEL_PARAM_CHANGE',
        'TOOL_RESULT_CHANGE',
        'SCHEMA_CHANGE',
        'ACL_SECRET_CHANGE',
        'MEMORY_WRITE',
        'CLOCK_WINDOW_ADVANCE',
        'HOOK_GAP'
    )),
    state TEXT NOT NULL CHECK (state IN (
        'OPEN',
        'DISCHARGED_RECOMPUTE',
        'DISCHARGED_CUTOFF',
        'HOOK_GAP'
    )),
    demanded BOOLEAN NOT NULL,
    cause_k TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    discharged_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_invalidation_obligations_project
  ON amc.invalidation_obligations(tenant_id, project_id, state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_invalidation_obligations_branch
  ON amc.invalidation_obligations(run_id, artifact_branch, event_class, updated_at DESC);
