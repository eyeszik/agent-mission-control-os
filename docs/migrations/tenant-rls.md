# Tenant row-level security (WO-04)

Migration: `supabase/migrations/20261121_amc_tenant_rls_v1.sql` (rollback generated in `supabase/rollback/`).
Code: `services/langgraph/persistence/database.py` (`tenant_scope`, `AMC_DB_RLS_MODE`).
Proof: `services/langgraph/tests/test_tenant_rls.py` (PostgreSQL), `test_tenant_scope.py`, `test_migration_roundtrip.py`.

## The three options, layered

Each option adds to the one before it. Options 1 and 2 are on as soon as the migration is applied.
Option 3 is a deployment decision, and nothing here switches it on.

| # | Option | What it does | State after this migration |
|---|---|---|---|
| 1 | Schema REVOKE | `anon` and `authenticated` have no `USAGE` on schema `amc`, so the Supabase Data API cannot reach any row. Tenant authorization is server-side through `amc.tenant_memberships`. | On (unchanged) |
| 2 | RLS enabled, owner exempt | Every `amc` table has row-level security **enabled, not forced**. The 84 tables with `tenant_id` carry one policy, `amc_tenant_isolation`, that admits a row only when `tenant_id = amc.current_tenant_id()`, for reads and writes. The 6 tables without `tenant_id` have no policy, so any role subject to RLS sees nothing. The backend connects as the owning role and is exempt, so behaviour does not change. Any non-owner role granted later is tenant-isolated by default. | On |
| 3 | Enforced for the application | The backend connects as a dedicated **non-owner** role with `AMC_DB_RLS_MODE=scoped`. Code that runs inside `tenant_scope(principal.tenant_id)` sends `amc.tenant_id` with `set_config(..., true)` at the start of each transaction, and PostgreSQL returns only that tenant's rows. Without a scope the role sees nothing (fail closed). | Implemented and proven in tests; **not activated** |

`amc.current_tenant_id()` returns `NULL` when no context is set, and `NULL` never equals a `tenant_id`.
The context is transaction-local, so a pooled connection never carries one tenant's context into the next borrower.
`tenant_scope` only narrows: re-entering it with a different tenant raises `PermissionError`.
`AMC_DB_RLS_MODE` accepts `off` (default) or `scoped`, and any other value raises.

## Activating option 3 (owner decision, not done)

1. Create the application role in production. Roles are cluster-level and are not part of these migrations:
   `create role amc_app login password '<from your secret store>' noinherit;`
   `grant usage on schema amc to amc_app;`
   `grant select, insert, update, delete on all tables in schema amc to amc_app;`
   `grant usage on all sequences in schema amc to amc_app;`
   `alter default privileges in schema amc grant select, insert, update, delete on tables to amc_app;`
2. Wrap request handling in `tenant_scope(principal.tenant_id)`. This is per call site, because a FastAPI
   dependency's context variable does not reach a sync route's threadpool. Work that is cross-tenant by
   design must keep running as the owner, or it must iterate tenants explicitly. That covers scheduler
   ticks, membership lookup before a tenant is known, and the run-event cursor.
3. Point `DATABASE_URL` at `amc_app` and set `AMC_DB_RLS_MODE=scoped` in a staging environment. Run the
   full PostgreSQL suite and the authenticated smoke gates in `docs/production-activation.md`.
4. Roll back by pointing `DATABASE_URL` back at the owner. The policies stay and do no harm.

Do not use `FORCE ROW LEVEL SECURITY` while the backend connects as the owner. Every owner query
without a tenant scope, including migrations, would return nothing.

## What this does not do

- It does not replace server-side authorization. `tenant_memberships`, the approvals route and the N2
  guards stay the authority, and RLS is a defence in depth beneath them.
- Expiry or revocation of approvals is not modelled in the schema. Revocation is the `stale` status.
- Option 3 is not wired into every route. Until it is, the owner connection (option 2) is the runtime path.
