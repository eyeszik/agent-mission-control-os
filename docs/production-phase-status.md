# Production Phase Status

## Completed in repository/provider configuration

- Existing Supabase project restored and verified `ACTIVE_HEALTHY`.
- `amc_production_foundation_v1` applied to live Supabase Postgres after restore completed and verified in the migration ledger.
- `amc_production_foundation_v2_fk_indexes` applied to add covering indexes for production foreign keys identified by the Supabase performance advisor.
- Production tenant/project bootstrap exists for `tenant_1` / `proj_1`; no user membership is auto-created.
- Supabase security advisor reports zero lints.
- Supabase performance advisor reports no unindexed-foreign-key findings; remaining `unused_index` INFO findings are expected before the new schema has a representative workload and must be reviewed after production traffic exists rather than removed preemptively.
- Dual SQLite/Postgres persistence implemented for runs, approvals, idempotency, events, analytics, publication jobs, and spend authorization records.
- LangGraph Postgres checkpointer configured for production.
- Supabase Auth bearer verification and server-side tenant membership authorization implemented.
- Native Next.js Supabase sign-in/signup/session bridge implemented without adding a client dependency.
- First-party analytics ingestion implemented.
- Publication dry-run ledger implemented; live publication remains deliberately unavailable until a concrete provider adapter is selected and credentialed.
- Paid-media authorization ledger implemented; live spend remains deliberately unavailable until a concrete provider adapter is selected and separately authorized.
- Vercel frontend/backend deployment manifests added.
- Production configuration fails closed when required secrets or modes are absent.
- CI includes production-readiness invariants in addition to backend/frontend/dependency/browser gates.

## External activation blockers

- Supabase Auth currently has no users, so no tenant membership can be assigned yet.
- `DATABASE_URL` database password is a deployment secret and is not exposed by the connected Supabase management surface.
- Vercel environment-secret mutation and creation of two new monorepo projects are not exposed by the connected Vercel surface in this chat.
- No social/ad provider was specified, so live publication and paid-media execution remain disabled by design.
- Production deployment cannot be truthfully marked complete until a verified deployment project receives the required secrets and its runtime health/auth/database path is exercised.
