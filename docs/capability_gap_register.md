# Agent Mission Control OS — Capability Gap Register

> Regenerated 2026-11-04. Gaps remaining after this session's implementation
> increment (durable execution, artifact storage, pooling, structured logging,
> OpenAPI + manifest + verifier extensions). Each gap names the owner action
> required and the completion evidence expected. No gap is silently marked done.

## BLOCKED — external credential / owner actions

| # | Gap | Blocks | Owner action | Completion evidence |
|---|---|---|---|---|
| 1 | Supabase project has no users / memberships | Production auth (Gate C) | Create operator user(s); require email confirmation; then `insert into amc.tenant_memberships (tenant_id, user_id, role, allowed_project_ids)` for each operator | `curl` filtered project access returns 403 for non-members; login works via UI |
| 2 | No live `DATABASE_URL` for the backend | Postgres persistence, pooling, checkpoint durability (Gate B) | Provide `DATABASE_URL` (pooler URI) as a deployment secret and run `supabase/migrations/*.sql` (ledger order) | `/health` shows `database_backend: postgres`; `ping_database()` true; pytest postgres shard |
| 3 | Live-Postgres CI shard missing | CI Gate B regression protection | Add a GitHub Actions service container (postgres) and run the pytest suite with `AMC_DATABASE_BACKEND=postgres` + grant CI a database URL secret or ephemeral instance | CI job green on postgres backend |
| 4 | Frontend/backend not bound to deployed projects | Deployment (Gate E) | Create Vercel project for `apps/web`; deploy Python API + worker process (any provider that runs Python and a long-lived worker: Vercel containers, Railway, Fly); set secrets (`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `DATABASE_URL`, `AMC_ENV=production`, `AMC_AUTH_MODE=supabase`, plus the background-execution / CORS / artifact vars — full list in `docs/production-activation.md` and this runbook) | `/health` on API host returns `production_ready: true`; frontend sign-in reaches Mission Control |
| 5 | No canonical domain / TLS | Gate E | Owner: point frontend and API hostnames, verify TLS, set `AMC_CORS_ALLOWED_ORIGINS` to the canonical frontend origin | HTTPS GET + CORS preflight pass on both hosts |
| 6 | R2 artifact backend uncredentialized | Optional artifact durability (Gate E) | Create an R2 bucket + API token; set `R2_ACCOUNT_ID`/`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY`/`R2_BUCKET`; ensure server runs with `amc-langgraph[r2]` (`boto3`); set `AMC_ARTIFACT_BACKEND=r2` | upload→round-trip on `r2`; `test_artifact_storage` parity run against R2 |
| 7 | Model provider for real generation | Live (non-degraded) runs | Set `OPENAI_API_KEY` (or swap adapter); generation succeeds with `PROVIDER_SUCCESS` and artifact bundle persisted | pipeline run reaches `needs_approval` without `release_blocked` |
| 8 | Live publication / paid-media providers | Gates on W10 only when requested | Select + credential concrete provider adapters (publication stays fail-closed until then) | extended `capabilities()` returns live flags only after adapters + tests exist |

## IMPLEMENTED THIS SESSION — needs production verification after #2–#4

| # | Capability | Residual gap |
|---|---|---|
| 9 | Durable execution (jobs, leases, retries, DLQ, cancellation, recovery) | Multi-node worker contention needs a Postgres-backed confirmation drill once #2/#3 exist |
| 10 | Artifact storage (local) | Directory must live on a persistent volume in the deployed environment (documented in runbook) |
| 11 | Postgres pooling | Accepted behavior unverified until live Postgres |

## NOT STARTED (deliberately deferred; no false claims)

| # | Gap | Notes |
|---|---|---|
| 12 | Cloudflare Worker production route (currently 501 scaffold) | Rarely-justified second runtime; requires W6 review after backend deploy is stable. Never deploy the 501 scaffold |
| 13 | OpenTelemetry export / dashboards / alert routing | Foundation (structured logs + request metrics + health flags) shipped; exporter + alert receiver are follow-on work, do not fabricate SLO numbers |
| 14 | Automated DB backups with retention + restore drill | Runbook procedure exists; automation requires live database |
| 15 | Step-up authentication (re-auth for final approvals) | Current model: single operator role + approval ledger. Candidates: Supabase re-auth. Not implemented |
| 16 | Content negotiation for `X-AMC-Tenant` multi-tenant UI switcher | Backend implemented; frontend tenant switcher not built (single-tenant UI assumption today) |
