create table if not exists amc.tenant_project_bindings (
    project_id text primary key references amc.projects(project_id) on delete cascade,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    status text not null check (status in ('ACTIVE', 'REVOKED')),
    binding_hash text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    revoked_at timestamptz
);
create index if not exists idx_amc_tenant_project_bindings_tenant on amc.tenant_project_bindings(tenant_id, status);

create table if not exists amc.policy_decision_records (
    decision_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    subject_ref text not null,
    action text not null,
    target text not null,
    policy_version text not null,
    input_hash text not null,
    effect text not null check (effect in ('ALLOW', 'DENY', 'REQUIRE_APPROVAL')),
    required_authority_refs jsonb not null default '[]'::jsonb,
    evidence_refs jsonb not null default '[]'::jsonb,
    decision_hash text not null,
    payload jsonb not null default '{}'::jsonb,
    decided_at timestamptz not null default now()
);
create index if not exists idx_amc_policy_decisions_project on amc.policy_decision_records(tenant_id, project_id, decided_at desc);

create table if not exists amc.trust_idempotency_records (
    idempotency_key text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    operation_id text not null,
    request_hash text not null,
    status text not null check (status in ('CLAIMED', 'SUCCEEDED', 'FAILED', 'AMBIGUOUS')),
    result_ref text,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_amc_trust_idempotency_project on amc.trust_idempotency_records(tenant_id, project_id, updated_at desc);

create table if not exists amc.outbox_messages (
    message_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    topic text not null,
    payload_hash text not null,
    payload_ref text not null,
    idempotency_key text not null,
    status text not null check (status in ('PENDING', 'CLAIMED', 'DELIVERED', 'FAILED')),
    attempts integer not null default 0 check (attempts >= 0 and attempts <= 3),
    claimed_by text,
    next_attempt_at timestamptz,
    delivered_at timestamptz,
    last_error text,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists idx_amc_outbox_project on amc.outbox_messages(tenant_id, project_id, status, created_at);

create table if not exists amc.audit_checkpoints (
    seq bigint primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    event_type text not null,
    object_ref text not null,
    payload_hash text not null,
    previous_hash text not null,
    checkpoint_hash text not null unique,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists idx_amc_audit_project on amc.audit_checkpoints(tenant_id, project_id, seq);

create table if not exists amc.recovery_cases (
    recovery_id text primary key,
    tenant_id text not null references amc.tenants(tenant_id) on delete cascade,
    project_id text not null references amc.projects(project_id) on delete cascade,
    operation_id text not null,
    reason text not null check (reason in ('EXECUTION_WITHOUT_OBSERVATION', 'OBSERVATION_MISMATCH', 'AMBIGUOUS_EXTERNAL_RESULT', 'IDEMPOTENCY_CONFLICT')),
    execution_ref text,
    observation_ref text,
    idempotency_key text,
    status text not null check (status in ('OPEN', 'RECONCILED', 'COMPENSATED', 'ESCALATED')),
    evidence_refs jsonb not null default '[]'::jsonb,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    resolved_at timestamptz
);
create index if not exists idx_amc_recovery_project on amc.recovery_cases(tenant_id, project_id, status, created_at desc);

alter table amc.approvals
    add column if not exists subject_type text,
    add column if not exists subject_ref text,
    add column if not exists subject_version_ref text,
    add column if not exists subject_hash text,
    add column if not exists authority_ref text,
    add column if not exists policy_version text,
    add column if not exists stale_reason text,
    add column if not exists staled_at timestamptz;

update amc.approvals
set
    subject_type = coalesce(subject_type, 'RUN_RESULT'),
    subject_ref = coalesce(subject_ref, run_id),
    subject_version_ref = coalesce(subject_version_ref, run_id),
    authority_ref = coalesce(authority_ref, 'human-review'),
    policy_version = coalesce(policy_version, 'amc-approval/v1')
where
    subject_type is null
    or subject_ref is null
    or subject_version_ref is null
    or authority_ref is null
    or policy_version is null;
