# Agent Mission Control — Production Operations Runbook

> Audience: on-call operator. Last validated against the repository tests on
> 2026-11-04 (100 backend tests + 5 verifiers green). Anything untested in a
> live environment is labeled as a procedure to execute, not a verified fact.

## 1. Runtime environment variables (project contract)

Base contract lives in `/env` example files; authoritative list:

| Variable | Required | Meaning |
|---|---|---|
| `AMC_ENV` | prod: `production` | selects fail-closed config enforcement |
| `AMC_AUTH_MODE` | prod: `supabase` | `local` (dev, loopback only), `supabase`, `disabled` |
| `AMC_DATABASE_BACKEND` | prod: `postgres` | `sqlite` (local/CI), `postgres` |
| `DATABASE_URL` | yes for postgres | Postgres (Supabase) pooler DSN |
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | yes for supabase auth | Supabase project coordinates |
| `AMC_CORS_ALLOWED_ORIGINS` | prod: canonical origins | comma list; loopback/`*` rejected in production |
| `AMC_EXECUTION_MODE` | prod: `background` | `inline` (request-lifetime execution), `background` (durable jobs) |
| `AMC_JOB_MAX_ATTEMPTS` | optional | retry budget per job (default 3, max 20) |
| `AMC_JOB_LEASE_SECONDS` | optional | worker lease duration (default 900) |
| `AMC_WORKER_INPROCESS` | optional | `1` runs worker threads inside the API (single-node only) |
| `AMC_DB_POOL_MIN`/`AMC_DB_POOL_MAX`/`AMC_DB_POOL_TIMEOUT` | optional | psycopg_pool sizing (max > 0 enables pooling) |
| `AMC_ARTIFACT_BACKEND` | optional (`local` default) | `local` or `r2` |
| `AMC_ARTIFACT_ROOT` | for local | persistent volume path for artifact bytes |
| `R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET` | for r2 | Cloudflare R2 credentials |
| `AMC_LOG_FORMAT`, `AMC_LOG_LEVEL` | optional | `json` for structured logs |
| `AMC_DEPLOYED_REVISION` | optional | git revision surfaced by `/health` for deploy verification |
| `OPENAI_API_KEY` | for real generation | unset ⇒ runs degrade (release-blocked) by design |
| `AMC_PUBLICATION_MODE`, `AMC_PAID_MEDIA_MODE` | keep `disabled` | live modes fail closed until provider adapters exist |

## 2. Start / verify

**Backend single-node (single container):**
```bash
python -m uvicorn services.langgraph.app.main:app --host 0.0.0.0 --port 8000
```
`/health` must return `production_ready: true` before traffic. Record
`deployed_revision` in the deploy evidence.

**Worker as its own process (multi-node, recommended):**
```bash
python -m services.langgraph.runtime.worker --poll-interval 2
```
(Add `--once` to drain and exit; use a supervisor/restart policy. Workers
recover correctness after abrupt termination via lease expiry — see §5.)

**Frontend:** `next start` behind TLS; `NEXT_PUBLIC_API_BASE_URL` must point at the
API host, `NEXT_PUBLIC_*_SUPABASE_*` at the same Supabase project as the backend.

## 3. Deployment (procedure — unverified until owner executes)

1. CI must be green on the exact commit (`gh run list --branch master`).
2. Apply the Supabase migration ledger in filename order (apply #4 once #2 in
   the gap register is unblocked): v1 → v2 → agency kernel → jobs/artifacts.
3. Deploy the API, then the worker, then set frontend env to the API origin.
4. Smoke test: sign in → create run (degraded) → approve → resume → artifact
   upload → SSE `/runs/{id}/events?follow=true` shows node events.
5. Record: deploy URL, commit, `/health` snapshot, smoke result — deploy is
   not "done" without this evidence.

## 4. Rollback

- Frontend: redeploy previous immutable Vercel deployment (dashboard).
- API: redeploy previous image/revision.
- Schema: **forward-only policy.** Migrations are additive (`create if not exists`);
  emergency use: restore from backup (§6) instead of downward DDL.
- Execution mode fallback: `AMC_EXECUTION_MODE=inline` only for emergency,
  single-instance maintenance windows; configuration still passes production
  validation but durability is reduced while inline (documented risk, never
  disable auth or weaken guards).

## 5. Worker recovery & duplicate protection (procedure — unit-tested)

 Guarantees (all maintained by design and covered by `test_durable_execution.py`):
- Job claim is a compare-and-swap; two workers can never hold one job.
- `fail_job` requeues until `AMC_JOB_MAX_ATTEMPTS`, then dead-letters; a
  dead-lettered job stops being picked automatically.
- complete/fail are fenced by the claim token: zombies that lost their leases
  cannot finish someone else's job.
- If a worker dies mid-run: lease expires → `expire_stale_leases()` requeues →
  a fresh claim resumes run execution from the persisted checkpointer.

Procedure:
1. `GET /operations/capabilities` (auth) — service surface alive.
2. Inspect jobs: `select job_id, kind, status, attempt_count, error from amc.amc_jobs order by queued_at desc limit 20;`
3. Stuck `running` rows older than the lease: they self-recover on the next
   worker poll; to force it, run `select service.expire...` is not required —
   simply restart a worker.
4. Dead-letter triage: fix the root cause, then set
   `update amc.amc_jobs set status='queued', attempt_count=0 where job_id='...'`
   — a conscious operator action, never automatic.

## 6. Backup / restore (procedure — needs live database)

- Supabase managed backups: verify daily snapshot exists; set retention per plan.
- Logical dump: `pg_dump --schema=amc --data-only --format=c` at least daily,
  off-cluster storage, 30-day retention.
- Restore drill (quarterly): restore dump into scratch DB; `ping_database()` on a
  scratch app boot; verify a known `run_id` + its events + one artifact row.
  Record the drill result in CHANGELOG.

## 7. Secret rotation

1. Supabase publishable key: rotate in dashboard → update both processes at
   next restart (frontend env values too).
2. `DATABASE_URL` password: update DB password → deploy env change → rolling
   restart API/worker (pool caps stall but drain; workers retry via job queue).
3. `OPENAI_API_KEY`/provider keys: rotate in provider; update secret store.
4. Sessions live in sessionStorage client-side and are short-lived by policy —
   no server-side token store to scrub; users re-login on next navigation.

## 8. Alerts worth wiring (requires alert receiver — deferred work)

- `/health` `production_ready` false ⇒ page.
- `amc.amc_jobs` dead_letter count > 0 in 5 minutes ⇒ investigate.
- p95 `/agency/runs` latency + 5xx rate via access logs (`amc.request`).
- Artifact integrity failures (`ArtifactIntegrityError`) ⇒ treat as data-loss
  incident, check storage backend volume/credentials.
