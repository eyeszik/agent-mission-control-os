-- AMC durable execution foundation: job queue and content-addressed artifact storage.
-- PostgreSQL (Supabase) authoritative production schema; SQLite mirrors these in
-- local/CI with the equivalent CREATE TABLE statements (sqlite_db.py migrations 6/7).
-- Date: 2026-11-04

create table if not exists amc.amc_jobs (
    job_id text primary key,
    kind text not null check (kind in ('agency.create','agency.resume')),
    tenant_id text not null,
    project_id text not null references amc.projects(project_id) on delete restrict,
    run_id text references amc.runs(run_id) on delete set null,
    status text not null default 'queued' check (status in ('queued','running','completed','failed','dead_letter','cancelled')),
    attempt_count integer not null default 0 check (attempt_count >= 0),
    max_attempts integer not null check (max_attempts >= 1),
    payload jsonb not null,
    result jsonb,
    error text,
    claim_token text,
    lease_expires_at timestamptz,
    queued_at timestamptz not null default now(),
    claimed_at timestamptz,
    completed_at timestamptz,
    updated_at timestamptz not null default now()
);

create index if not exists idx_amc_jobs_claim on amc.amc_jobs(status, queued_at);
create index if not exists idx_amc_jobs_tenant on amc.amc_jobs(tenant_id, project_id, queued_at desc);
create index if not exists idx_amc_jobs_lease on amc.amc_jobs(status, lease_expires_at);

create table if not exists amc.artifact_objects (
    object_id text primary key,
    tenant_id text not null,
    project_id text not null references amc.projects(project_id) on delete restrict,
    content_type text not null default 'application/octet-stream',
    size_bytes bigint not null check (size_bytes >= 0),
    created_by text,
    created_at timestamptz not null default now(),
    unique (tenant_id, object_id)
);

create table if not exists amc.artifact_versions (
    artifact_id text primary key,
    tenant_id text not null,
    project_id text not null references amc.projects(project_id) on delete restrict,
    run_id text references amc.runs(run_id) on delete set null,
    kind text not null,
    version integer not null check (version >= 1),
    object_id text not null references amc.artifact_objects(object_id) on delete restrict,
    content_hash text not null,
    deleted boolean not null default false,
    deleted_at timestamptz,
    created_at timestamptz not null default now(),
    unique (tenant_id, project_id, kind, version)
);

create index if not exists idx_amc_artifacts_tenant on amc.artifact_versions(tenant_id, project_id, created_at desc);
create index if not exists idx_amc_artifacts_run on amc.artifact_versions(run_id);

comment on table amc.amc_jobs is 'Durable execution queue. Workers claim with compare-and-swap status fencing tokens; leases expire via recover_expired_leases().';
comment on table amc.artifact_objects is 'Content-addressed artifact bytes. Deduplicated per tenant by sha256 object_id.';
comment on table amc.artifact_versions is 'Immutable artifact version records pointing at content-addressed bytes.';
