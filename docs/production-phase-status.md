# Production Phase Status

## Completed in repository/provider configuration

- Existing Supabase project restored and verified `ACTIVE_HEALTHY`.
- `amc_production_foundation_v1` applied to live Supabase Postgres after restore completed and verified in the migration ledger.
- `amc_production_foundation_v2_fk_indexes` applied to add covering indexes for production foreign keys identified by the Supabase performance advisor.
- `20261104_amc_durable_execution_v1_jobs_artifacts` DDL committed for the new durable-execution job queue and content-addressed artifact tables (apply with the others once `DATABASE_URL` is available).
- Production tenant/project bootstrap exists for `tenant_1` / `proj_1`; no user membership is auto-created.
- Supabase security advisor reports zero lints.
- Supabase performance advisor reports no unindexed-foreign-key findings.
- Dual SQLite/Postgres persistence implemented for runs, approvals, idempotency, events, analytics, publication jobs, spend authorization records, durable jobs, and artifact content.
- **Durable execution implemented (2026-11-04):** `persistence/jobs.py` job queue with atomic claim fencing, worker leases with heartbeat renewal, retry budgets, dead-lettering, cancellation, and lease-expiry recovery; `runtime/worker.py` worker process plus optional in-process poller; shared execution core used by both the inline API route and the worker so semantics cannot drift; background mode (`AMC_EXECUTION_MODE=background`) is required in production and fires a config error otherwise. Covered by `tests/test_durable_execution.py` (claim races, lease recovery, retry exhaustion, cancellation, end-to-end background run, crash-recovery with no duplicated committed effects).
- **Artifact storage implemented (2026-11-04):** content-addressed sha256 object storage (tenant-scoped local FS backend; Cloudflare R2 adapter on the same interface, UNVERIFIED until credentials), immutable version records per (project, kind), upload/list/download/delete HTTP API with tenant isolation and read-back integrity verification (tamper detection covered). Supabase DDL mirrors it, SQLite migration v7 keeps local/CI parity.
- **Postgres connection pooling added (2026-11-04):** opt-in via `AMC_DB_POOL_MAX` using `psycopg_pool`; unpooled path unchanged for SQLite/CI.
- **Observability foundation added (2026-11-04):** structured JSON logging (`AMC_LOG_FORMAT=json`), request-id middleware (`X-Request-ID`, per-request access log with status and duration), `executed` `/health` contract extended with `execution_mode`, `artifact_backend`, `deployed_revision`, and pool stats. OpenTelemetry export remains deferred.
- LangGraph Postgres checkpointer configured for production.
- Supabase Auth bearer verification and server-side tenant membership authorization implemented.
- Native Next.js Supabase sign-in/signup/session bridge implemented without adding a client dependency.
- First-party analytics ingestion implemented.
- Publication dry-run ledger implemented; live publication remains deliberately unavailable until a concrete provider adapter is selected and credentialed.
- Paid-media authorization ledger implemented; live spend remains deliberately unavailable until a concrete provider adapter is selected and separately authorized.
- Vercel frontend/backend deployment manifests added.
- Production configuration fails closed when required secrets or modes are absent.
- CI includes production-readiness invariants; the integrity manifest now pins 71 critical files including the new runtime/persistence modules and tests.

## External activation blockers

- Supabase Auth currently has no users, so no tenant membership can be assigned yet.
- `DATABASE_URL` database password is a deployment secret and is not exposed by the connected Supabase management surface.
- Vercel environment-secret mutation and creation of two new monorepo projects are not exposed by the connected Vercel surface in this chat.
- No social/ad provider was specified, so live publication and paid-media execution remain disabled by design.
- The Cloudflare Worker scaffold still ends at a 501; it must not be deployed unchanged.
- Production deployment cannot be truthfully marked complete until a verified deployment project receives the required secrets and its runtime health/auth/database path is exercised.
- Full detail per gap: `docs/capability_gap_register.md`; capability inventory: `docs/system_inventory.generated.md`; runbooks: `docs/operations-runbook.md`.
