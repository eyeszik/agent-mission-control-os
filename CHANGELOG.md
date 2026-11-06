# CHANGELOG.md

## 1.1.0 — Production foundation: durable execution, artifacts, observability (2026-11-04)

### Added
- Durable execution: `persistence/jobs.py` (atomic claim fencing, leases with heartbeat renewal, retry budget with dead-lettering, cancellation, lease-expiry recovery), `runtime/worker.py` worker process + optional in-process poller, shared `runtime/execution.py` core; `AMC_EXECUTION_MODE=background` required in production.
- Content-addressed artifact storage (`persistence/artifacts.py` + `/agency/artifacts` API): sha256 objects per tenant, immutable version records, tombstoning, tenant isolation, read-back integrity verification, fail-closed Cloudflare R2 adapter (UNVERIFIED until credentials).
- Postgres connection pooling (opt-in, `AMC_DB_POOL_MAX`, `psycopg_pool`).
- Structured JSON logging + request-id access log middleware; `/health` now reports `execution_mode`, `artifact_backend`, `deployed_revision`, pool stats.
- Supabase migration `20261104_amc_durable_execution_v1_jobs_artifacts.sql` (jobs + artifact tables); SQLite ledger v6/v7 mirrors.
- OpenAPI contract extended (artifacts CRUD, execution modes, health fields); production-readiness verifier and integrity manifest (71 files) extended.
- Docs: generated capability inventory (`docs/system_inventory.generated.md`), capability gap register (`docs/capability_gap_register.md`), operations runbook (`docs/operations-runbook.md`).

### Tested
- 100 backend pytest tests passing including 10 new durable-execution tests (crash recovery, no duplicate committed effects) and 3 new artifact-storage tests (tamper detection, cross-tenant isolation).
- Frontend/shared suites and typechecks unchanged and green; all five repository verifiers green.

## 1.0.0 — Repo-ready artifact bundle

### Added
- Added complete deterministic agent operating spec artifact files.
- Added Codex implementation prompt.
- Added Codex phase plan.
- Added Codex file handoff matrix.
- Added GitHub setup guide.
- Added repo bootstrap command script.
- Added `.codex/config.toml` starter config.
- Added GitHub pull request template.

### Decision
- Bundle is complete as an architecture/specification package.
- Bundle is not production-release approved.
- Repository audit is required before implementation.
- Cloudflare binding verification is required before edge deployment.
- Provider/tool contract verification is required before production adapters.

### Open Flags
- FLAG-REPO-NOT-PROVIDED
- FLAG-VERSIONS-NULL-UNTIL-REPO-AUDIT
- FLAG-CLOUDFLARE-BINDINGS-UNVERIFIED
- FLAG-OBSERVABILITY-ADAPTERS-UNVERIFIED
- FLAG-MCP-TRANSPORTS-UNVERIFIED
- FLAG-SEC-DISSENT-BLOCKS-PRODUCTION
- FLAG-RUNTIME-SCHEMA-VALIDATION-NOT-EXECUTED
