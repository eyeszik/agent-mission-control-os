-- ACE v12 governed action plane and agency clients. Additive only: no existing
-- table is altered. Mirrors services/langgraph/persistence/sqlite_db.py migration v16.
-- amc stays revoked from the anon/authenticated Data API roles.

create table if not exists amc.action_requests (
    action_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    client_id text,
    capability_id text not null,
    capability_version text not null,
    environment text not null check (environment in ('LOCAL','SANDBOX','LIVE')),
    actor_ref text not null,
    target_ref text not null,
    args jsonb not null,
    args_hash text not null,
    payload_hash text not null,
    context_hash text not null,
    dependency_hashes jsonb not null,
    policy_version text not null,
    risk jsonb not null,
    risk_hash text not null,
    effective_class text not null check (effective_class in ('R0','R1','R2','R3','R4','R5','R6')),
    binding jsonb not null,
    binding_hash text not null,
    run_id text,
    approval_id text,
    financial_approval_id text,
    budget_reservation_id text,
    idempotency_key text not null,
    request_hash text not null,
    correlation_id text not null,
    state text not null check (state in ('PROPOSED','VALIDATED','PREPARED','AWAITING_APPROVAL','AUTHORIZED','RESERVED',
        'DISPATCHING','OBSERVING','VERIFIED','COMPLETED','REJECTED','BLOCKED','EXPIRED','CANCELLED','FAILED','UNKNOWN',
        'RECONCILING','NEEDS_HUMAN')),
    version integer not null default 1 check (version >= 1),
    attempts integer not null default 0 check (attempts >= 0 and attempts <= 3),
    reconcile_attempts integer not null default 0 check (reconcile_attempts >= 0),
    lease_owner text,
    lease_expires_at text,
    retry_eligible boolean not null default false,
    reasons jsonb not null,
    outcome jsonb,
    injection_flags jsonb not null,
    created_at text not null,
    updated_at text not null,
    expires_at text not null,
    unique (tenant_id, idempotency_key)
);

create table if not exists amc.action_transitions (
    entry_id bigint generated always as identity primary key,
    action_id text not null references amc.action_requests(action_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    from_state text,
    to_state text not null,
    actor text not null,
    reason text not null,
    evidence jsonb not null,
    prev_hash text,
    entry_hash text not null,
    created_at text not null
);

create table if not exists amc.action_budget_policies (
    policy_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    scope_kind text not null check (scope_kind in ('ACTION','PROJECT','CLIENT','TENANT_DAY','TENANT_MONTH')),
    scope_ref text not null,
    currency text not null check (currency ~ '^[A-Z]{3}$'),
    ceiling_minor bigint not null check (ceiling_minor >= 0),
    created_by text not null,
    created_at text not null,
    unique (tenant_id, scope_kind, scope_ref, currency)
);

create table if not exists amc.action_budget_reservations (
    reservation_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    client_id text,
    action_id text not null references amc.action_requests(action_id) on delete cascade,
    currency text not null check (currency ~ '^[A-Z]{3}$'),
    amount_minor bigint not null check (amount_minor >= 0),
    committed_minor bigint check (committed_minor is null or committed_minor >= 0),
    status text not null check (status in ('RESERVED','COMMITTED','RELEASED','EXPIRED','REFUNDED')),
    expires_at text not null,
    evidence jsonb not null,
    created_at text not null,
    updated_at text not null
);

create table if not exists amc.action_freezes (
    freeze_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    scope_kind text not null check (scope_kind in ('TENANT','PROJECT')),
    scope_ref text not null,
    reason text not null,
    frozen_by text not null,
    frozen_at text not null,
    lifted_by text,
    lifted_at text,
    lift_reason text
);

create table if not exists amc.action_project_settings (
    project_id text primary key references amc.projects(project_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    autonomy text not null check (autonomy in ('OBSERVE','DRAFT','PREPARE','REQUEST_APPROVAL')),
    updated_by text not null,
    updated_at text not null
);

-- The sandbox fake providers' "remote" state. Only sandbox adapters read or
-- write it; nothing here was delivered anywhere.
create table if not exists amc.action_sandbox_effects (
    effect_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    provider text not null,
    operation text not null,
    idempotency_key text not null,
    target_ref text not null,
    payload_hash text not null,
    state text not null,
    cost_minor bigint not null default 0,
    currency text,
    body jsonb not null,
    created_at text not null,
    updated_at text not null,
    unique (tenant_id, provider, idempotency_key)
);

create table if not exists amc.agency_clients (
    client_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    display_name text not null,
    slug text not null,
    status text not null check (status in ('ACTIVE','OFFBOARDING','ARCHIVED')),
    notes text not null default '',
    created_by text not null,
    created_at text not null,
    updated_at text not null,
    unique (tenant_id, slug)
);

create table if not exists amc.agency_client_projects (
    project_id text primary key references amc.projects(project_id) on delete cascade,
    client_id text not null references amc.agency_clients(client_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    linked_by text not null,
    linked_at text not null
);

create index if not exists idx_amc_action_requests_project on amc.action_requests(project_id, state);
create index if not exists idx_amc_action_requests_tenant_state on amc.action_requests(tenant_id, state);
create index if not exists idx_amc_action_transitions_action on amc.action_transitions(action_id, entry_id);
create index if not exists idx_amc_action_reservations_tenant on amc.action_budget_reservations(tenant_id, currency, status);
create index if not exists idx_amc_action_freezes_scope on amc.action_freezes(tenant_id, scope_kind, scope_ref);
create index if not exists idx_amc_agency_client_projects_client on amc.agency_client_projects(client_id);

comment on table amc.action_requests is 'Governed external actions (R0-R6). Persisted before dispatch and after observation; LIVE is never dispatched.';
comment on table amc.action_transitions is 'Append-only, hash-chained per action state history.';
comment on table amc.action_sandbox_effects is 'Sandbox fake provider state. Nothing in this table reached a real provider.';
