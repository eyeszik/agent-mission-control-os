# PostgreSQL tenant RLS: implementation and rollout (outcome E)

Canonical runbook: `docs/migrations/tenant-rls.md`. This file is the verification record for this cycle.

## Implemented and proven (ephemeral PostgreSQL 16, local scratch databases only)

| Requirement | State | Test |
|---|---|---|
| RLS enabled on all 90 `amc` tables; `amc_tenant_isolation` on the 84 with `tenant_id` | PASS | `test_tenant_rls.py::test_every_amc_table_has_rls_…` |
| Non-BYPASSRLS, non-owner application role is constrained | PASS | `test_tenant_rls_enforcement.py::test_the_application_role_is_constrained_…` |
| Privileged bypass named (superuser, BYPASSRLS, owner) by the read-only preflight `rls_enforcement_problems` | PASS | same |
| FORCE treatment: deliberately not applied; the test shows what it would do | PASS | `test_force_would_subject_the_owner_…` |
| Transaction-scoped context (`set_config(…, true)`), fail closed without a scope | PASS | `test_tenant_rls.py` (scoped and off modes) |
| Pooled cleanup: no context carried into the next borrower, including after a rollback | PASS | `test_a_pooled_connection_never_carries_…` |
| Concurrency: two tenants on a two-connection pool never see each other's rows | PASS | `test_concurrent_tenants_on_one_pool_…` |
| Cross-tenant read, update, delete, insert and move are refused | PASS | `test_tenant_rls.py::test_app_role_sees_only_its_tenant_…` |
| Revoked membership (API, supabase mode, real `tenant_memberships` row) → 403 | PASS | `test_a_revoked_membership_loses_access_…` |
| Forged tenant (`X-AMC-Tenant` outside the membership) → 403 | PASS | `test_an_active_member_is_served_and_a_forged_tenant_header_is_refused` |
| Rollback restores the pre-RLS catalog exactly | PASS | `test_rollback_restores_the_pre_rls_catalog` (now locates the migration by name, since a later migration follows it) |

Three consecutive runs: 13 passed each time.

## Defect found and fixed

`transaction()` with `AMC_DB_POOL_MAX>0` raised `TypeError: '_GeneratorContextManager' object is not iterable`. It did `yield from` on a context manager. Pooled connections also lacked `dict_row` and `prepare_threshold=0`. The defect dates from f863a4cb and had no test. Both are fixed, and the pooled tests above failed before the fix.

## Not done (approval-gated)

- No production role was created or bound.
- `AMC_DB_RLS_MODE` stays `off`.
- No route is wrapped in `tenant_scope`.
- No migration was applied outside the throwaway local cluster.

Routes are not wrapped because `tenant_scope` has to be applied per call site, and cross-tenant work such as scheduler ticks and membership lookup must stay on the owner connection. That is a staged rollout decision; `docs/migrations/tenant-rls.md` gives the steps, including the new preflight check.
