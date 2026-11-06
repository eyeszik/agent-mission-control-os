create table if not exists amc.lineage_remediation_queue (
    remediation_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    run_id text not null references amc.runs(run_id) on delete cascade,
    approval_id text,
    artifact_id text not null,
    artifact_version_ref text not null,
    changed_artifact_id text not null,
    changed_version_ref text not null,
    reason text not null,
    status text not null check (status in ('OPEN', 'REGENERATED', 'RETRIED', 'RESOLVED')),
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    resolved_at timestamptz
);
create index if not exists idx_amc_lineage_remediation_project
  on amc.lineage_remediation_queue(tenant_id, project_id, status, created_at desc);
create index if not exists idx_amc_lineage_remediation_run
  on amc.lineage_remediation_queue(run_id, status, created_at desc);
