create table if not exists amc.engagements (
    engagement_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete restrict,
    objective text not null,
    desired_outcome text not null,
    status text not null,
    constraints jsonb not null default '{}'::jsonb,
    permissions jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_amc_engagements_tenant_project on amc.engagements(tenant_id, project_id, created_at desc);
create index if not exists idx_amc_engagements_status on amc.engagements(status, updated_at desc);

create table if not exists amc.workstreams (
    workstream_id text primary key,
    engagement_id text not null references amc.engagements(engagement_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete restrict,
    department text not null,
    objective text not null,
    status text not null,
    dependencies jsonb not null default '[]'::jsonb,
    acceptance_criteria jsonb not null default '[]'::jsonb,
    permissions jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_amc_workstreams_engagement on amc.workstreams(engagement_id, status, created_at);
create index if not exists idx_amc_workstreams_project on amc.workstreams(project_id, created_at desc);

create table if not exists amc.agency_evidence (
    evidence_id text primary key,
    engagement_id text not null references amc.engagements(engagement_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete restrict,
    evidence_type text not null,
    source_ref text,
    claim text not null,
    epistemic_status text not null check (epistemic_status in ('verified','inferred','assumption','hypothesis','stale','conflict','unverified','blocked')),
    confidence double precision not null check (confidence >= 0 and confidence <= 1),
    collected_at timestamptz not null,
    freshness_seconds bigint check (freshness_seconds is null or freshness_seconds >= 0),
    payload jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb
);
create index if not exists idx_amc_agency_evidence_engagement on amc.agency_evidence(engagement_id, epistemic_status, collected_at desc);
create index if not exists idx_amc_agency_evidence_project on amc.agency_evidence(project_id, collected_at desc);

create table if not exists amc.agency_decisions (
    decision_id text primary key,
    engagement_id text not null references amc.engagements(engagement_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete restrict,
    question text not null,
    alternatives jsonb not null default '[]'::jsonb,
    selected_option jsonb not null default 'null'::jsonb,
    evidence_ids jsonb not null default '[]'::jsonb,
    assumptions jsonb not null default '[]'::jsonb,
    affected_artifact_ids jsonb not null default '[]'::jsonb,
    confidence jsonb not null,
    status text not null check (status in ('proposed','accepted','superseded','rejected')),
    approver text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_amc_agency_decisions_engagement on amc.agency_decisions(engagement_id, status, created_at desc);
create index if not exists idx_amc_agency_decisions_project on amc.agency_decisions(project_id, created_at desc);

create table if not exists amc.agency_artifacts (
    artifact_id text primary key,
    engagement_id text not null references amc.engagements(engagement_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete restrict,
    workstream_id text references amc.workstreams(workstream_id) on delete set null,
    artifact_type text not null,
    subtype text,
    owner_department text not null,
    version integer not null check (version > 0),
    status text not null check (status in ('draft','validating','approved','release_eligible','released','review_required','invalidated','archived')),
    content_location text,
    content_hash text,
    semantic_fingerprint text,
    assumptions jsonb not null default '[]'::jsonb,
    validation jsonb not null default '{}'::jsonb,
    approval jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_amc_agency_artifacts_engagement on amc.agency_artifacts(engagement_id, status, artifact_type);
create index if not exists idx_amc_agency_artifacts_workstream on amc.agency_artifacts(workstream_id) where workstream_id is not null;
create index if not exists idx_amc_agency_artifacts_project on amc.agency_artifacts(project_id, created_at desc);

create table if not exists amc.artifact_dependencies (
    artifact_id text not null references amc.agency_artifacts(artifact_id) on delete cascade,
    depends_on_artifact_id text not null references amc.agency_artifacts(artifact_id) on delete cascade,
    relationship text not null check (relationship in ('hard','soft')),
    created_at timestamptz not null default now(),
    primary key (artifact_id, depends_on_artifact_id),
    check (artifact_id <> depends_on_artifact_id)
);
create index if not exists idx_amc_artifact_dependencies_upstream on amc.artifact_dependencies(depends_on_artifact_id, artifact_id);

comment on table amc.engagements is 'Client-facing autonomous agency engagements above individual Agent Mission Control runs.';
comment on table amc.artifact_dependencies is 'Directed artifact dependency edges used for selective invalidation and review propagation.';
