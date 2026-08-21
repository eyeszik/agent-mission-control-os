# Production Activation Runbook

This runbook converts the merged Agent Mission Control production foundation into an externally reachable, authenticated deployment without weakening the existing trust boundary.

## Activation invariant

Production is **ACTIVE** only when every gate below passes on the exact deployed revision. Until then the correct state is `PRODUCTION_ACTIVATION_BLOCKED`.

## 1. Required external resources

Create and verify two Vercel projects in the intended team/account rather than reusing unrelated existing projects:

- `agent-mission-control-web` — repository root directory `apps/web`
- `agent-mission-control-api` — repository root directory `services/langgraph`

Bind both projects to the same Git repository and production branch. Record the generated project IDs and deployment URLs in the deployment system, not in source code unless the values are explicitly non-secret configuration.

Do not run an unscoped deploy command before this binding is verified.

## 2. Backend production environment

Set these values in the backend deployment environment:

```text
AMC_ENV=production
AMC_AUTH_MODE=supabase
AMC_DATABASE_BACKEND=postgres
DATABASE_URL=<deployment secret>
SUPABASE_URL=<Supabase project URL>
SUPABASE_PUBLISHABLE_KEY=<publishable key>
AMC_CORS_ALLOWED_ORIGINS=<exact frontend production origin>
AMC_PUBLICATION_MODE=disabled
AMC_PAID_MEDIA_MODE=disabled
OPENAI_API_KEY=<optional model-provider secret>
AMC_OPENAI_MODEL=<reviewed model identifier>
```

`DATABASE_URL` and provider credentials are secrets. Do not commit them. Prefer the Supabase connection endpoint appropriate for the selected runtime and verify that it supports the synchronous psycopg/LangGraph checkpoint workload before production traffic.

Production startup must fail if:

- auth mode is not `supabase`
- database backend is not `postgres`
- required Supabase/database configuration is missing
- CORS uses `*`, localhost, or loopback origins
- publication is configured live without an installed adapter
- paid-media execution is enabled without an installed adapter

## 3. Frontend production environment

Set:

```text
NEXT_PUBLIC_AUTH_MODE=supabase
NEXT_PUBLIC_SUPABASE_URL=<Supabase project URL>
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable key>
NEXT_PUBLIC_API_BASE_URL=<exact backend production origin>
```

Only publishable browser configuration belongs in `NEXT_PUBLIC_*`. Never place database passwords, service-role keys, model-provider secrets, or other privileged credentials in a `NEXT_PUBLIC_*` variable.

## 4. First production identity

`AUTH_USER_REQUIRED`

Create the first operator through the supported Supabase Auth signup/admin flow. Do **not** insert directly into `auth.users`.

After email verification or other configured identity verification, obtain the provider-issued Auth user UUID.

Then grant explicit AMC membership using an administrator-controlled database operation equivalent to:

```sql
insert into amc.tenant_memberships (
    tenant_id,
    user_id,
    role,
    allowed_project_ids,
    active
)
values (
    'tenant_1',
    '<SUPABASE_AUTH_USER_UUID>',
    'owner',
    array['proj_1']::text[],
    true
)
on conflict (tenant_id, user_id)
do update set
    role = excluded.role,
    allowed_project_ids = excluded.allowed_project_ids,
    active = true,
    updated_at = now();
```

Before granting membership, independently verify the UUID belongs to the intended operator. Never auto-enroll arbitrary public signups into `tenant_1`.

## 5. Deployment order

1. Verify the Supabase project is healthy and migrations are present.
2. Verify `tenant_1` and `proj_1` exist.
3. Create/bind the backend Vercel project.
4. Inject backend configuration/secrets.
5. Deploy backend.
6. Request `/health` and verify the production capability state.
7. Create/bind the frontend Vercel project.
8. Inject frontend public configuration.
9. Deploy frontend.
10. Create/verify the first Supabase Auth user.
11. Grant explicit AMC tenant/project membership.
12. Run the authenticated smoke suite below.
13. Only after all gates pass, mark the environment ACTIVE.

## 6. Unauthenticated smoke gates

Backend `/health` must return a state consistent with:

```text
status=ok
environment=production
auth_mode=supabase
database_backend=postgres
analytics_source=amc_first_party
production_ready=true
publication_mode=disabled
paid_media_mode=disabled
```

A protected API request without a bearer token must be rejected. A request with an invalid/expired token must also be rejected.

## 7. Authenticated production smoke gates

Sign in as the explicitly provisioned operator and verify:

1. `/operations/capabilities` returns the authenticated tenant and reports:
   - publication live = false
   - publication dry-run = true
   - paid-media live spend = false
   - authorization ledger = true
   - analytics source = `amc_first_party`
2. Cross-tenant/project substitution is denied.
3. Creating an agency run for `proj_1` with a unique `Idempotency-Key` returns `201` and reaches `needs_approval`.
4. Repeating the same request with the same idempotency key replays the canonical response rather than executing again.
5. If no model-provider key exists, the run is explicitly degraded and delivery remains blocked.
6. A pending approval is visible only inside the authenticated tenant scope.
7. Rejecting an approval produces a terminal `rejected` run.
8. First-party analytics contains lifecycle events for creation, HITL, decision, and rejection.
9. Publication preview creates only a blocked/dry-run audit record; it must not publish externally.
10. Spend authorization creates only a pending authorization record; it must not execute spend.
11. SSE replay resumes from a cursor/`Last-Event-ID` without duplicate or cross-tenant events.

## 8. Provider-success smoke gate

Only after the model-provider secret is installed, create a non-degraded test run and verify:

- generation provenance reports a real provider/model and `PROVIDER_SUCCESS`
- QA does not contain a degradation release block
- an explicit human approval is required
- resume transitions atomically from `needs_approval` to `delivering` to `completed`
- lifecycle analytics records delivery start/completion
- no publication or paid-media execution occurs unless separately enabled by a reviewed adapter

## 9. Observability checks

After the smoke run, verify:

- run records persisted in Postgres
- LangGraph checkpoints persisted in Postgres
- event sequences are monotonic per run
- analytics events use `amc_first_party`
- approval reviewer is derived from the authenticated principal
- idempotency replay is deterministic
- logs contain no raw access tokens, database credentials, model-provider secrets, or unsanitized sensitive campaign input

## 10. Rollback / failure recovery

If any activation gate fails:

1. Do not enable publication or spend.
2. Mark the deployment non-production/blocked.
3. Preserve logs and deployment revision identifiers.
4. Roll back the Vercel deployment to the last verified revision when applicable.
5. Disable the affected AMC membership if identity scope is uncertain.
6. Rotate any credential suspected of exposure.
7. Repair the defect through a PR and rerun the complete CI + authenticated production smoke sequence.

## 11. External-action activation remains separate

Live campaign publishing and paid-media spend are not part of baseline production activation. Each provider must receive a separate implementation/review phase covering:

- provider OAuth/service identity
- least-privilege scopes
- token rotation
- idempotency and retry semantics
- rate limiting
- approval policy
- campaign/account allowlists
- budget ceilings
- audit logging
- reconciliation with provider-side state
- dry-run/sandbox validation
- kill switch
- incident rollback

No adapter may change `AMC_PUBLICATION_MODE` or `AMC_PAID_MEDIA_MODE` to live until these controls have executable tests and a reviewed release gate.
