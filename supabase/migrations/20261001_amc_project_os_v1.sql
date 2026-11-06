-- Project OS: PROJECT is the durable unit of state.
-- Mirrors services/langgraph/persistence/sqlite_db.py migration v13.
-- Every table is tenant- and project-scoped; amc stays revoked from the
-- anon/authenticated Data API roles (see the production foundation migration).

create table if not exists amc.project_workspaces (
    project_id text primary key references amc.projects(project_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    slug text not null,
    display_name text not null,
    description text not null default '',
    lifecycle_state text not null check (lifecycle_state in ('ACTIVE','PAUSED','ARCHIVED')),
    brand_id text,
    brand_name text,
    workspace_schema_version text not null,
    manifest jsonb not null,
    manifest_hash text not null,
    created_by text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, slug)
);

create table if not exists amc.project_events (
    event_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    sequence bigint not null check (sequence > 0),
    event_type text not null,
    actor text not null,
    thread_id text,
    subject_ref text,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (project_id, sequence)
);

create table if not exists amc.storage_objects (
    object_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    backend text not null check (backend in ('LOCAL','R2')),
    storage_uri text not null,
    content_hash text not null,
    byte_size bigint not null check (byte_size >= 0),
    mime_type text not null,
    status text not null check (status in ('PRESENT','MISSING','UNVERIFIED')),
    created_at timestamptz not null default now(),
    verified_at timestamptz,
    unique (project_id, backend, content_hash)
);

create table if not exists amc.artifact_versions (
    artifact_id text not null references amc.agency_artifacts(artifact_id) on delete cascade,
    version integer not null check (version > 0),
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    content_hash text,
    content_location text,
    semantic_fingerprint text,
    metadata jsonb not null default '{}'::jsonb,
    change_kind text not null check (change_kind in ('create','revise','restore','replace_master')),
    restored_from_version integer,
    created_by text not null,
    created_at timestamptz not null default now(),
    primary key (artifact_id, version)
);

create table if not exists amc.asset_rights (
    rights_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    artifact_id text not null references amc.agency_artifacts(artifact_id) on delete cascade,
    license text not null,
    territory text not null,
    usage_scope text not null,
    attribution text,
    source_ref text,
    expires_at timestamptz,
    status text not null check (status in ('active','expired','revoked')),
    created_at timestamptz not null default now()
);

create table if not exists amc.conversation_threads (
    thread_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    campaign_id text,
    title text not null,
    status text not null check (status in ('open','archived')),
    created_by text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists amc.conversation_messages (
    message_id text primary key,
    thread_id text not null references amc.conversation_threads(thread_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    author text not null,
    role text not null check (role in ('user','agent','system')),
    activity_type text not null,
    body text not null,
    artifact_refs jsonb not null default '[]'::jsonb,
    event_id text,
    created_at timestamptz not null default now()
);

create table if not exists amc.artifact_comments (
    comment_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    artifact_id text not null references amc.agency_artifacts(artifact_id) on delete cascade,
    version_ref text not null,
    author text not null,
    body text not null,
    created_at timestamptz not null default now()
);

create table if not exists amc.artifact_edit_requests (
    request_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    artifact_id text not null references amc.agency_artifacts(artifact_id) on delete cascade,
    base_version_ref text not null,
    instruction text not null,
    status text not null check (status in ('open','applied','rejected','stale')),
    requested_by text not null,
    created_at timestamptz not null default now(),
    resolved_at timestamptz
);

create table if not exists amc.content_atoms (
    atom_id text not null,
    version integer not null check (version > 0),
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    campaign_id text,
    title text not null,
    claims jsonb not null default '[]'::jsonb,
    source_refs jsonb not null default '[]'::jsonb,
    content_hash text not null,
    created_by text not null,
    created_at timestamptz not null default now(),
    primary key (atom_id, version)
);

create table if not exists amc.content_items (
    content_item_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    campaign_id text,
    atom_id text,
    atom_version integer,
    artifact_id text,
    kind text not null,
    channel text not null,
    title text not null,
    state text not null check (state in ('IDEA','PLANNED','IN_PRODUCTION','REVIEW','APPROVED','READY','SCHEDULED','DUE','PUBLISHING','PUBLISHED','VERIFIED','MEASURED','REFRESH_DUE','ARCHIVED')),
    version integer not null check (version > 0),
    body jsonb not null default '{}'::jsonb,
    claim_refs jsonb not null default '[]'::jsonb,
    rights_ref text,
    approved_version integer,
    approval_ref text,
    evidence_fresh_until timestamptz,
    created_by text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists amc.calendars (
    calendar_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    name text not null,
    timezone text not null,
    created_at timestamptz not null default now()
);

create table if not exists amc.schedule_slots (
    slot_id text primary key,
    calendar_id text not null references amc.calendars(calendar_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    content_item_id text references amc.content_items(content_item_id) on delete set null,
    channel text not null,
    scheduled_for timestamptz not null,
    state text not null check (state in ('open','filled','released','cancelled')),
    created_at timestamptz not null default now()
);

create table if not exists amc.scheduled_jobs (
    job_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    slot_id text,
    content_item_id text,
    job_kind text not null check (job_kind in ('PUBLISH','REFRESH','LIFECYCLE')),
    due_at timestamptz not null,
    status text not null check (status in ('PENDING','BLOCKED','ENQUEUED','DELIVERED','FAILED','CANCELLED')),
    idempotency_key text not null unique,
    outbox_message_id text,
    block_reasons jsonb not null default '[]'::jsonb,
    payload jsonb not null default '{}'::jsonb,
    attempts integer not null default 0 check (attempts >= 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists amc.publication_attempts (
    attempt_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    job_id text,
    content_item_id text not null,
    provider text not null,
    mode text not null check (mode in ('DISABLED','DRY_RUN','LIVE')),
    state text not null check (state in ('SPEC','VALIDATED','AUTHORIZED','APPROVED','EXECUTING','READBACK','RECONCILED','VERIFIED','BLOCKED','FAILED','UNCERTAIN')),
    request_hash text not null,
    idempotency_key text not null,
    external_ref text,
    readback jsonb not null default '{}'::jsonb,
    error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (provider, idempotency_key)
);

create table if not exists amc.publication_receipts (
    receipt_id text primary key,
    attempt_id text not null references amc.publication_attempts(attempt_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    kind text not null check (kind in ('dispatch_permit','execution','observation')),
    payload jsonb not null,
    receipt_hash text not null,
    created_at timestamptz not null default now()
);

create table if not exists amc.memory_records (
    memory_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text references amc.projects(project_id) on delete cascade,
    thread_id text,
    scope text not null check (scope in ('M0_AGENCY','M1_BRAND_CANON','M2_PROJECT','M3_CONVERSATION','M4_EVIDENCE','M5_PERFORMANCE','M6_LEARNING')),
    authority text not null check (authority in ('BRAND_CANON','APPROVED_PROJECT_DECISION','VERIFIED_EVIDENCE','WORKING_CONTEXT','LEARNING_SIGNAL')),
    subject_key text not null,
    body jsonb not null,
    source_refs jsonb not null default '[]'::jsonb,
    fresh_until timestamptz,
    status text not null check (status in ('ACTIVE','SUPERSEDED','INVALIDATED','QUARANTINED')),
    supersedes text,
    content_hash text not null,
    created_by text not null,
    created_at timestamptz not null default now()
);

create table if not exists amc.knowledge_items (
    item_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text references amc.projects(project_id) on delete cascade,
    domain text not null,
    source_uri text not null,
    rights_class text not null,
    stage text not null,
    status text not null check (status in ('IN_PIPELINE','AWAITING_REVIEW','PROMOTED','REJECTED')),
    claims jsonb not null default '[]'::jsonb,
    evidence_score double precision not null,
    rejection_reasons jsonb not null default '[]'::jsonb,
    content_hash text not null,
    fetched_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists amc.prompt_records (
    prompt_id text not null,
    version integer not null check (version > 0),
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    artifact_target text,
    department text not null,
    family text,
    campaign_id text,
    status text not null,
    prompt_hash text not null,
    body jsonb not null,
    created_by text not null,
    created_at timestamptz not null default now(),
    primary key (prompt_id, version)
);

create table if not exists amc.provider_profiles (
    profile_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    provider text not null,
    model text not null,
    task text not null,
    mode text not null check (mode in ('DISABLED','DRY_RUN','LIVE')),
    body jsonb not null,
    last_verified_at timestamptz,
    created_at timestamptz not null default now(),
    unique (tenant_id, provider, model, task)
);

create table if not exists amc.growth_experiments (
    experiment_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    hypothesis text not null,
    target_metric text not null,
    segment text not null,
    intervention text not null,
    asset_refs jsonb not null default '[]'::jsonb,
    start_at timestamptz,
    end_at timestamptz,
    sample_requirement integer not null check (sample_requirement > 0),
    status text not null check (status in ('DRAFT','RUNNING','CONCLUDED','ABANDONED')),
    observed_result jsonb,
    decision text check (decision is null or decision in ('ADOPT','REJECT','INCONCLUSIVE')),
    learning_signal_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists amc.learning_signals (
    signal_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    seq bigint not null check (seq > 0),
    status text not null,
    payload jsonb not null,
    prev_hash text not null,
    hash text not null,
    created_at timestamptz not null default now(),
    unique (tenant_id, seq)
);

create table if not exists amc.learning_promotions (
    promotion_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    signal_id text not null references amc.learning_signals(signal_id) on delete cascade,
    stage text not null,
    status text not null check (status in ('IN_PROGRESS','AWAITING_HUMAN_APPROVAL','PROMOTED','ROLLED_BACK','REJECTED')),
    evidence jsonb not null default '{}'::jsonb,
    approved_by text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_amc_project_workspaces_tenant on amc.project_workspaces(tenant_id, updated_at desc);
create index if not exists idx_amc_project_events_cursor on amc.project_events(project_id, sequence);
create index if not exists idx_amc_storage_objects_project on amc.storage_objects(project_id, status);
create index if not exists idx_amc_artifact_versions_project on amc.artifact_versions(project_id, created_at desc);
create index if not exists idx_amc_asset_rights_artifact on amc.asset_rights(artifact_id, status);
create index if not exists idx_amc_asset_rights_expiry on amc.asset_rights(project_id, expires_at);
create index if not exists idx_amc_threads_project on amc.conversation_threads(project_id, updated_at desc);
create index if not exists idx_amc_messages_thread on amc.conversation_messages(thread_id, created_at);
create index if not exists idx_amc_comments_artifact on amc.artifact_comments(artifact_id, created_at);
create index if not exists idx_amc_edit_requests_artifact on amc.artifact_edit_requests(artifact_id, status);
create index if not exists idx_amc_content_atoms_project on amc.content_atoms(project_id, atom_id);
create index if not exists idx_amc_content_items_project on amc.content_items(project_id, state, updated_at desc);
create index if not exists idx_amc_calendars_project on amc.calendars(project_id);
create index if not exists idx_amc_slots_calendar on amc.schedule_slots(calendar_id, scheduled_for);
create index if not exists idx_amc_jobs_due on amc.scheduled_jobs(status, due_at);
create index if not exists idx_amc_jobs_project on amc.scheduled_jobs(project_id, due_at);
create index if not exists idx_amc_publication_attempts_item on amc.publication_attempts(content_item_id, created_at);
create index if not exists idx_amc_publication_receipts_attempt on amc.publication_receipts(attempt_id);
create index if not exists idx_amc_memory_scope on amc.memory_records(tenant_id, project_id, scope, subject_key, status);
create index if not exists idx_amc_knowledge_tenant on amc.knowledge_items(tenant_id, project_id, status);
create index if not exists idx_amc_knowledge_hash on amc.knowledge_items(tenant_id, content_hash);
create index if not exists idx_amc_prompt_records_project on amc.prompt_records(project_id, prompt_id);
create index if not exists idx_amc_growth_experiments_project on amc.growth_experiments(project_id, status);
create index if not exists idx_amc_learning_promotions_signal on amc.learning_promotions(signal_id);

comment on table amc.project_workspaces is 'Durable project identity and workspace manifest. Runs are executions within a project.';
comment on table amc.project_events is 'Project activity stream; conversations and runs append here so chat state is never invisible to the artifact graph.';
comment on table amc.memory_records is 'Scoped memory. Authority order: BRAND_CANON > APPROVED_PROJECT_DECISION > VERIFIED_EVIDENCE > WORKING_CONTEXT > LEARNING_SIGNAL.';
