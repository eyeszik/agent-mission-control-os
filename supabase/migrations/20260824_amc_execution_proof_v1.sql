create table if not exists amc.execution_receipts (
    operation_id text primary key,
    run_id text not null references amc.runs(run_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    work_order_id text not null,
    payload jsonb not null default '{}'::jsonb,
    started_at timestamptz not null,
    ended_at timestamptz not null
);
create index if not exists idx_amc_execution_receipts_run on amc.execution_receipts(run_id, started_at);

create table if not exists amc.observation_receipts (
    operation_id text primary key,
    run_id text not null references amc.runs(run_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    payload jsonb not null default '{}'::jsonb,
    observed_at timestamptz not null,
    matches boolean not null
);
create index if not exists idx_amc_observation_receipts_run on amc.observation_receipts(run_id, observed_at);

create table if not exists amc.dispatch_permits (
    permit_id text primary key,
    run_id text not null references amc.runs(run_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    work_order_id text not null,
    payload jsonb not null default '{}'::jsonb,
    issued_at timestamptz not null
);
create index if not exists idx_amc_dispatch_permits_run on amc.dispatch_permits(run_id, issued_at);

create table if not exists amc.failure_fingerprints (
    fingerprint text primary key,
    run_id text not null references amc.runs(run_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    operation_id text not null,
    payload jsonb not null default '{}'::jsonb
);
create index if not exists idx_amc_failure_fingerprints_run on amc.failure_fingerprints(run_id, operation_id);

create table if not exists amc.completion_evaluations (
    evaluation_id text primary key,
    run_id text not null references amc.runs(run_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    terminal_candidate text not null check (terminal_candidate in ('COMPLETE', 'BLOCKED')),
    proof_coverage double precision not null check (proof_coverage >= 0 and proof_coverage <= 1),
    confidence double precision not null check (confidence >= 0 and confidence <= 1),
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists idx_amc_completion_evaluations_run on amc.completion_evaluations(run_id, created_at desc);
