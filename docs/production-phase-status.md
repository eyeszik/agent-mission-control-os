# Production Phase Status

## Completed in repository/provider configuration

- Existing Supabase project restored.
- `amc_production_foundation_v1` applied to Supabase Postgres.
- Supabase security advisor: zero lints after migration.
- Supabase performance advisor: zero lints after migration.
- Dual SQLite/Postgres persistence implemented for runs, approvals, idempotency, events, analytics, publication jobs, and spend authorization records.
- LangGraph Postgres checkpointer configured for production.
- Supabase Auth bearer verification and server-side tenant membership authorization implemented.
- Native Next.js Supabase sign-in/signup/session bridge implemented without adding a client dependency.
- First-party analytics ingestion implemented.
- Publication dry-run ledger implemented; live publication remains deliberately unavailable until a concrete provider adapter is selected and credentialed.
- Paid-media authorization ledger implemented; live spend remains deliberately unavailable until a concrete provider adapter is selected and separately authorized.
- Vercel frontend/backend deployment manifests added.
- Production configuration fails closed when required secrets or modes are absent.

## External activation blockers

- Supabase Auth currently has no users, so no tenant membership can be assigned yet.
- `DATABASE_URL` database password is a deployment secret and is not exposed by the connected Supabase management surface.
- Vercel environment-secret mutation and creation of two new monorepo projects are not exposed by the connected Vercel surface in this chat.
- No social/ad provider was specified, so live publication and paid-media execution remain disabled by design.
