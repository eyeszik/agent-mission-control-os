# Agent Mission Control OS — Generated System Inventory

> Regenerated 2026-11-04 at working tree on top of commit `b037d27` (master).
> Every entry carries an evidence classification from this session's executable
> checks: 100 backend pytest, 19 shared + 9 web tests, clean typechecks, and
> all 5 repository verifiers passing (`verify_repository_invariants`,
> `verify_production_readiness`, `verify_auth_bindings`,
> `verify_ontology_parity`, `verify_manifest` at 71 pinned files).

## Backend (services/langgraph)

| Capability | Status | Evidence |
|---|---|---|
| FastAPI service + CORS allowlist (loopback-rejecting in production) | IMPLEMENTED / WORKING | `tests/test_cors.py`; `/health` endpoint |
| Fail-closed production config (`config.py` env contract) | IMPLEMENTED / WORKING | `test_production_foundation.py`; `verify_production_readiness.py` fixture |
| Supabase Auth bearer verification + X-AMC-Tenant multi-tenant selection | IMPLEMENTED / WORKING (code) | `tests/test_security_boundaries.py`; live verification BLOCKED on Supabase users (owner action) |
| Local loopback-only auth mode (dev/CI) | WORKING | conftest; all API tests |
| Tenant membership authorization (`memberships.py`) | IMPLEMENTED / UNVERIFIED | projection of membership rows; live-Postgres verification blocked on `DATABASE_URL` |
| SQLite persistence (runs, approvals, idempotency, events, analytics, publication, spend, kernel 5 tables, jobs, artifacts) | WORKING | full test suite, `current_schema_version() == 7` |
| PostgreSQL persistence (same contracts) | IMPLEMENTED / UNVERIFIED | DDL in Supabase migration ledger v1/v2/v3; live-Postgres execution blocked on `DATABASE_URL` |
| Postgres connection pooling (`AMC_DB_POOL_MAX`, psycopg_pool) | IMPLEMENTED / UNVERIFIED (pooled path requires live Postgres) | `database.py`; unpooled proven by full sqlite suite |
| LangGraph pipeline + HITL gates (brand strategy → … → delivery) | WORKING | `test_agency_pipeline.py`, `test_delivery_gate.py`, degraded e2e |
| LangGraph checkpointers (SQLite local, Postgres production) | IMPLEMENTED / WORKING (sqlite) | `test_checkpointer_lifecycle.py`; Postgres checkpointer UNVERIFIED |
| **Synchronous inline execution (`AMC_EXECUTION_MODE=inline`)** | WORKING | original route tests (87 pre-existing + parity) |
| **Durable job queue (`persistence/jobs.py`)** — atomic claim fencing, leases, retry budget, dead-lettering, cancellation, lease-expiry recovery | IMPLEMENTED / WORKING (sqlite) | `test_durable_execution.py` (10 tests) |
| **Background execution mode (`AMC_EXECUTION_MODE=background`, required in production)** | IMPLEMENTED / WORKING (sqlite) | end-to-end create→poll→approve→resume→completed test |
| **Worker (`runtime/worker.py`)** — poll loop, in-process heartbeat lease renewal, module entrypoint, FastAPI in-process option | IMPLEMENTED / WORKING (sqlite) | `test_durable_execution.py`; multiprocessing deployment UNVERIFIED |
| Shared execution core (`runtime/execution.py`) used by both inline route and worker | IMPLEMENTED / WORKING | route parity tests |
| SSE event stream backed by persisted events + Last-Event-ID cursor replay | WORKING | `test_events.py` |
| First-party analytics ingestion + lifecycle analytics | WORKING | `test_lifecycle_analytics.py`, `test_production_foundation.py` |
| Idempotency: reserve/complete/replay/conflict with TTL | WORKING | `test_idempotency_concurrency.py` |
| Approvals (pending/resolved, reviewer binding, terminal state) | WORKING | `test_approvals.py`, `test_delivery_gate.py` |
| Publication dry-run ledger; live publication fail-closed | WORKING | `test_provider_semantics.py`, verifier token |
| Paid-media authorization ledger; live spend fail-closed (`and False`) | WORKING | `test_production_foundation.py` |
| Brand safety QA + degraded provenance handling | WORKING | `test_agency_pipeline.py` |
| Knowledge kernel ontology (N1/N2) parity across Python/TS | WORKING | `test_agency_ontology.py`; `verify_ontology_parity.py` |
| **Artifact storage (`persistence/artifacts.py`)**: content-addressed objects (sha256), immutable version rows, local FS backend, tombstoning | IMPLEMENTED / WORKING (local sqlite) | `test_artifact_storage.py` (3 tests) |
| Artifact HTTP API (upload/list/download/delete, tenant isolation, read-back integrity, tamper detection) | IMPLEMENTED / WORKING | `test_artifact_storage.py` |
| R2 object-storage adapter (same interface, boto3 S3 API) | IMPLEMENTED / UNVERIFIED — no live credentials | code + fail-closed env contract in `config.py` |
| Structured JSON logging (`AMC_LOG_FORMAT=json`), request-id middleware (`X-Request-ID`, access log with status/duration) | IMPLEMENTED / WORKING | `app/observability.py`; exercised in all API tests |
| `/health` with `execution_mode`, `artifact_backend`, `deployed_revision`, pool stats | IMPLEMENTED / WORKING | this session |

## Frontend (apps/web)

| Capability | Status | Evidence |
|---|---|---|
| Mission Control UI (command input, workflow map, artifact preview, approval inbox, audit log, live progress) | IMPLEMENTED / WORKING | browser E2E in CI (`agency-smoke.spec.ts`) |
| Session storage without refresh tokens (access_token + expiry only; re-login on expiry) | IMPLEMENTED / VERIFIED | this working tree (`lib/auth/session.ts`, `lib/auth/supabase.ts`) |
| Native Supabase sign-in/sign-up bridge | IMPLEMENTED | `lib/auth/supabase.ts` |
| Zustand stores incl. project selection (no hardcoded `proj_1`) | WORKING | `tests/stores.test.ts` |
| PII redaction client-side | WORKING | `tests/pii.test.ts` |
| XSS sanitization (synced with backend patterns) | WORKING | `lib/security/sanitize.ts` |
| Idempotency keys in API client | WORKING | `tests/idempotency.test.ts` |
| Production build (`next build`) + Vercel manifest | IMPLEMENTED | CI frontend job |

## CI/CD (.github/workflows/ci.yml)

| Capability | Status | Evidence |
|---|---|---|
| Backend gates: invariants, readiness, auth bindings, ontology parity, manifest, compileall, pip check, pytest (sqlite) | WORKING | workflow definition + all pass locally |
| Frontend gates: shared build/typecheck/test, web typecheck/test/build | WORKING | same |
| Browser E2E stack (uvicorn + Next.js + Playwright) | WORKING | workflow + spec |
| Dependency audits (pip-audit, pnpm audit --prod high) | WORKING | workflow |
| **Live PostgreSQL test shard** | MISSING | blocked on a CI-provisioned Postgres + `DATABASE_URL` secret (owner action) |
| Staging auto-deploy + production promote gates | MISSING | no deployment target configured yet (owner action) |

## Infrastructure / Providers

| Capability | Status | Evidence |
|---|---|---|
| Supabase Postgres schema v1/v2 + agency kernel v1 + durable-execution v3 (jobs + artifacts) | DOCUMENTED (SQL committed) | migration ledger; live apply UNVERIFIED (owner action) |
| Vercel frontend/backend manifests | DOCUMENTED | `apps/web/vercel.json`, `services/langgraph/vercel.json`; binding + smoke UNVERIFIED |
| Cloudflare Worker scaffold (worker.ts, durable-object, idempotency, shard, bindings) + tests | PARTIAL / SANDBOX_ONLY | `durable-object.test.ts`; integration with backend UNBUILT; do not deploy the 501 scaffold |
| Custom domain + TLS + HTTPS enforcement | MISSING | owner action (DNS) |
| OpenTelemetry export, dashboards, alerting | PARTIAL | structured logs + request metrics implemented as foundation; OTel export MISSING |
| Automated backups + restore drill | MISSING | procedure documented in operations runbook; execution needs live DB |
