-- VNEXUS creative intelligence: brand genome versions, a temporal creative
-- knowledge graph, creative branches, provider-neutral media jobs, prompt
-- genomes, measured campaign results and a hash-chained audit log.
-- Mirrors services/langgraph/persistence/sqlite_db.py migration v15.
-- amc stays revoked from the anon/authenticated Data API roles.

create table if not exists amc.vnexus_brands (
    brand_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    owner_project_id text not null references amc.projects(project_id) on delete restrict,
    display_name text not null,
    created_by text not null,
    created_at text not null
);

create table if not exists amc.vnexus_genome_versions (
    version_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    brand_id text not null references amc.vnexus_brands(brand_id) on delete cascade,
    scope text not null check (scope in ('brand','project','page','component','asset')),
    scope_ref text not null,
    project_id text not null references amc.projects(project_id) on delete cascade,
    version integer not null check (version >= 1),
    parent_version_id text references amc.vnexus_genome_versions(version_id),
    status text not null check (status in ('DRAFT','EXPERIMENTAL','IN_REVIEW','APPROVED','REJECTED','SUPERSEDED')),
    document jsonb not null,
    content_hash text not null,
    revision integer not null default 1 check (revision >= 1),
    origin text not null check (origin in ('AUTHORED','REVERT','BRANCH_PROMOTION','IMPORT')),
    origin_ref text,
    created_by text not null,
    created_at text not null,
    updated_at text not null,
    submitted_by text,
    submitted_at text,
    approval_id text,
    decided_by text,
    decided_at text,
    unique (brand_id, scope, scope_ref, version)
);

-- At most one approved (authoritative) version per scope.
create unique index if not exists uq_amc_vnexus_genome_approved
    on amc.vnexus_genome_versions(brand_id, scope, scope_ref) where status = 'APPROVED';

create table if not exists amc.vnexus_audit_log (
    entry_id bigint generated always as identity primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    chain_ref text not null,
    subject_type text not null,
    subject_id text not null,
    action text not null,
    actor text not null,
    from_state text,
    to_state text,
    detail jsonb not null default '{}'::jsonb,
    prev_hash text,
    entry_hash text not null unique,
    created_at text not null
);

create table if not exists amc.vnexus_graph_nodes (
    node_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    brand_id text not null references amc.vnexus_brands(brand_id) on delete cascade,
    kind text not null,
    label text not null,
    attributes jsonb not null default '{}'::jsonb,
    content_hash text not null,
    valid_from text not null,
    valid_to text,
    superseded_by text references amc.vnexus_graph_nodes(node_id),
    created_by text not null,
    created_at text not null
);

create table if not exists amc.vnexus_graph_edges (
    edge_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    brand_id text not null references amc.vnexus_brands(brand_id) on delete cascade,
    kind text not null,
    src_node_id text not null references amc.vnexus_graph_nodes(node_id) on delete cascade,
    dst_node_id text not null references amc.vnexus_graph_nodes(node_id) on delete cascade,
    provenance jsonb not null default '{}'::jsonb,
    valid_from text not null,
    valid_to text,
    created_by text not null,
    created_at text not null,
    check (src_node_id <> dst_node_id)
);

create table if not exists amc.vnexus_branches (
    branch_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    brand_id text not null references amc.vnexus_brands(brand_id) on delete cascade,
    scope text not null,
    scope_ref text not null,
    project_id text not null references amc.projects(project_id) on delete cascade,
    base_version_id text not null references amc.vnexus_genome_versions(version_id),
    parent_branch_id text references amc.vnexus_branches(branch_id),
    name text not null,
    hypothesis text not null default '',
    changes jsonb not null,
    changes_hash text not null,
    state text not null check (state in ('OPEN','IN_REVIEW','PROMOTED','REJECTED','ARCHIVED')),
    revision integer not null default 1 check (revision >= 1),
    proposal_version_id text references amc.vnexus_genome_versions(version_id),
    decision_note text,
    created_by text not null,
    created_at text not null,
    updated_at text not null
);

create table if not exists amc.vnexus_branch_evaluations (
    evaluation_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    branch_id text not null references amc.vnexus_branches(branch_id) on delete cascade,
    kind text not null check (kind in ('DETERMINISTIC','HUMAN')),
    evaluator text not null,
    changes_hash text not null,
    payload jsonb not null,
    payload_hash text not null,
    created_at text not null
);

create table if not exists amc.vnexus_media_jobs (
    job_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    provider_id text not null,
    capability text not null,
    request jsonb not null,
    request_hash text not null,
    idempotency_key text not null,
    state text not null check (state in ('PLANNED','VALIDATED','AUTHORIZED','QUEUED','RUNNING','ARTIFACT_RECEIVED','QC_PASSED','FAILED','CANCELED')),
    estimate jsonb not null default '{}'::jsonb,
    budget_ceiling_minor integer not null default 0 check (budget_ceiling_minor >= 0),
    currency text not null default 'USD',
    authorized_by text,
    authorized_at text,
    attempts integer not null default 0 check (attempts >= 0),
    max_attempts integer not null default 2 check (max_attempts between 1 and 3),
    provider_job_ref text,
    artifact jsonb not null default '{}'::jsonb,
    qc jsonb not null default '{}'::jsonb,
    error text,
    version integer not null default 1 check (version >= 1),
    created_by text not null,
    created_at text not null,
    updated_at text not null,
    unique (tenant_id, idempotency_key)
);

create table if not exists amc.vnexus_media_job_transitions (
    transition_id bigint generated always as identity primary key,
    job_id text not null references amc.vnexus_media_jobs(job_id) on delete cascade,
    tenant_id text not null,
    from_state text not null,
    to_state text not null,
    reason text not null default '',
    actor text not null,
    observed_at text not null
);

create table if not exists amc.vnexus_prompt_genomes (
    prompt_version_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    brand_id text not null references amc.vnexus_brands(brand_id) on delete cascade,
    prompt_id text not null,
    version integer not null check (version >= 1),
    parent_version_id text references amc.vnexus_prompt_genomes(prompt_version_id),
    status text not null check (status in ('DRAFT','APPROVED','SUPERSEDED','SOURCE_REQUIRED')),
    source_kind text not null check (source_kind in ('ORIGINAL_IMPORT','DERIVED','AUTHORED')),
    source_hash text,
    document jsonb not null,
    content_hash text not null,
    created_by text not null,
    created_at text not null,
    unique (brand_id, prompt_id, version)
);

create table if not exists amc.vnexus_measurements (
    measurement_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    campaign_ref text not null,
    metric text not null,
    value double precision not null,
    unit text not null,
    source text not null,
    source_ref text not null,
    observed_at text not null,
    recorded_by text not null,
    recorded_at text not null,
    kind text not null default 'MEASURED' check (kind = 'MEASURED')
);

create index if not exists idx_amc_vnexus_genome_scope on amc.vnexus_genome_versions(brand_id, scope, scope_ref, status);
create index if not exists idx_amc_vnexus_audit_chain on amc.vnexus_audit_log(chain_ref, entry_id);
create index if not exists idx_amc_vnexus_nodes_brand on amc.vnexus_graph_nodes(brand_id, kind);
create index if not exists idx_amc_vnexus_edges_src on amc.vnexus_graph_edges(src_node_id, kind);
create index if not exists idx_amc_vnexus_edges_dst on amc.vnexus_graph_edges(dst_node_id, kind);
create index if not exists idx_amc_vnexus_branches_brand on amc.vnexus_branches(brand_id, state);
create index if not exists idx_amc_vnexus_media_jobs_project on amc.vnexus_media_jobs(project_id, state);
create index if not exists idx_amc_vnexus_measurements_campaign on amc.vnexus_measurements(project_id, campaign_ref);

comment on table amc.vnexus_genome_versions is 'Brand genome layer versions. APPROVED rows are immutable; a revert is a new version.';
comment on table amc.vnexus_audit_log is 'Append-only, hash-chained per chain_ref (brand) record of every VNEXUS state change.';
comment on table amc.vnexus_media_jobs is 'Provider-neutral media jobs. QC_PASSED requires a received artifact whose bytes were re-hashed and checked.';
comment on table amc.vnexus_measurements is 'Measured campaign results with a named source. Forecasts and simulations are never stored here.';
