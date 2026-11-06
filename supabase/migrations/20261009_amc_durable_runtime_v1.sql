-- Durable run runtime: leases with fencing tokens, write-ahead intents keyed by a
-- stable idempotency identity, an append-only transition log and per-tick telemetry.
-- Mirrors services/langgraph/persistence/sqlite_db.py migration v14.
-- amc stays revoked from the anon/authenticated Data API roles.

create table if not exists amc.durable_jobs (
    job_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    kind text not null,
    spec jsonb not null,
    spec_hash text not null,
    requested_by text not null,
    state text not null,
    logical_tick integer not null default 0 check (logical_tick >= 0),
    version integer not null default 1 check (version >= 1),
    lease_owner text,
    lease_token integer not null default 0 check (lease_token >= 0),
    lease_expires_at text,
    attempts integer not null default 0 check (attempts >= 0),
    max_attempts integer not null default 3 check (max_attempts between 1 and 3),
    recurrence_seconds integer,
    next_due_at text not null,
    last_reasons jsonb not null default '[]'::jsonb,
    failure_fingerprints jsonb not null default '{}'::jsonb,
    result jsonb not null default '{}'::jsonb,
    created_at text not null,
    updated_at text not null
);

create table if not exists amc.durable_intents (
    idempotency_key text primary key,
    job_id text not null references amc.durable_jobs(job_id) on delete cascade,
    tenant_id text not null,
    project_id text not null,
    logical_tick integer not null,
    operation text not null,
    target text not null,
    input_hash text not null,
    contract_version text not null,
    retry_class text not null check (retry_class in ('RETRY_SAFE','COMPENSATABLE','NON_RETRYABLE')),
    pre_image jsonb not null default '{}'::jsonb,
    status text not null check (status in ('INTENT','COMMITTED','ABANDONED')),
    fencing_token integer not null,
    receipt jsonb not null default '{}'::jsonb,
    created_at text not null,
    committed_at text
);

create table if not exists amc.durable_transitions (
    transition_id bigint generated always as identity primary key,
    job_id text not null references amc.durable_jobs(job_id) on delete cascade,
    tenant_id text not null,
    project_id text not null,
    from_state text not null,
    to_state text not null,
    fencing_token integer not null,
    logical_tick integer not null,
    reason text not null default '',
    trace_id text,
    observed_at text not null
);

create table if not exists amc.durable_ticks (
    trace_id text primary key,
    job_id text,
    tenant_id text,
    project_id text,
    worker_id text not null,
    logical_tick integer,
    outcome text not null,
    telemetry jsonb not null,
    started_at text not null,
    finished_at text not null
);

create index if not exists idx_amc_durable_jobs_due on amc.durable_jobs(state, next_due_at);
create index if not exists idx_amc_durable_jobs_project on amc.durable_jobs(project_id, state);
create index if not exists idx_amc_durable_intents_job on amc.durable_intents(job_id, logical_tick);
create index if not exists idx_amc_durable_transitions_job on amc.durable_transitions(job_id, transition_id);

comment on table amc.durable_jobs is 'Run FSM state per job. Every write after a claim is fenced on lease_token.';
comment on table amc.durable_intents is 'Write-ahead intent per side effect, unique on a stable idempotency identity; reconciled before any replay.';
