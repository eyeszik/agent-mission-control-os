# Agent Mission Control OS

Agent Mission Control OS is a local-first LangGraph + FastAPI + Next.js control plane for running a branding/marketing agency workflow with durable checkpoints, approval gating, cursor-addressable event replay, typed runtime contracts, and explicit degraded-provider semantics.

## Current implementation status

**Implemented and usable locally**

- Agency workflow: `brief_intake → brand_strategy → creative_concepting → copywriting → design_brief → campaign_assembly → brand_safety_qa → hitl_gate → delivery`.
- Human approval before delivery.
- Server-derived loopback development principal; browser-supplied tenant/reviewer values are not authoritative.
- Sensitive campaign input is recursively sanitized/redacted before run persistence/checkpointing.
- Atomic approval decisions and scoped idempotency reservations with deterministic replay.
- Versioned local SQLite migrations.
- Explicit provider provenance and `FALLBACK_DEGRADED` handling; degraded generation cannot be delivered.
- Truthful local evaluation metrics (`faithfulness`/`hallucination_rate` remain `NOT_MEASURED` without grounding evidence).
- Cursor-addressable persisted run events with runtime-validated frontend consumption.
- Zod runtime validation for core agency/approval API responses.
- Shared frontend pipeline-stage contract.
- Next.js `16.3.0` frontend with an audited, lockfile-pinned production dependency graph.

**Not claimed / deliberately blocked**

- Production authentication provider: **not implemented**. `AMC_AUTH_MODE=local` is loopback-only.
- Production deployment: not performed by this repository setup.
- External campaign publication or paid-media spend: not implemented.
- Real campaign analytics: deferred until a verified channel/data source exists.
- Initial pipeline execution is still synchronous. The SSE endpoint supports durable cursor replay/tailing of persisted events, but the synchronous request path does not claim pre-node live-start timing.
- Cloudflare/Supabase bindings are planning inputs until independently configured and verified.

## Repository layout

- `services/langgraph/` — FastAPI API, LangGraph workflow, persistence, security, evaluation, tests.
- `apps/web/` — Next.js Mission Control frontend.
- `packages/shared/` — shared Zod/TypeScript contracts and OpenAPI artifact.
- `scripts/verify_repository_invariants.py` — executable repository/contract drift checks.
- `scripts/verify_manifest.py` + `manifest.json` — critical-runtime integrity verification.
- `constraint_ledger.yaml` — explicit runtime/governance constraints.
- `runtime_topology.yaml`, `streaming_resilience_spec.json`, `contract_architecture.json` — intended architecture and invariants.

## Local setup

### Prerequisites

- Node.js **20.9+**
- pnpm version pinned by the root `packageManager` field
- Python 3.11 recommended for parity with CI

### 1. Configure environment

Copy `.env.example` to your local environment and keep secrets out of Git.

For local loopback use, the minimum security/runtime variables are:

```text
AMC_AUTH_MODE=local
AMC_LOCAL_USER_ID=local-operator
AMC_LOCAL_TENANT_ID=tenant_1
AMC_LOCAL_PROJECT_IDS=proj_1
AMC_LOCAL_ROLE=operator
AMC_DB_PATH=amc_local.db
AMC_CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

To use real provider generation, set `OPENAI_API_KEY` in your local environment. If it is absent or provider output repeatedly fails validation, the run is explicitly degraded and delivery remains blocked.

### 2. Install frontend/shared dependencies

```bash
pnpm install --frozen-lockfile
pnpm --filter @amc/shared build
```

### 3. Install backend

From `services/langgraph`:

```bash
python -m pip install -e ".[dev]"
```

### 4. Run backend

From the repository root:

```bash
python -m uvicorn services.langgraph.app.main:app --host 127.0.0.1 --port 8000 --reload
```

Local auth intentionally rejects non-loopback clients.

### 5. Run frontend

```bash
pnpm --filter @amc/web dev
```

Open `http://localhost:3000`.

## Validation

Run the same core deterministic gates used by CI:

```bash
python scripts/verify_repository_invariants.py
python scripts/verify_manifest.py
python -m compileall -q services/langgraph scripts
python -m pytest services/langgraph/tests -q
pnpm --filter @amc/shared build
pnpm --filter @amc/shared typecheck
pnpm --filter @amc/shared test
pnpm --filter @amc/web typecheck
pnpm --filter @amc/web test
pnpm --filter @amc/web build
```

CI additionally runs Python and production JavaScript dependency audits. Security/concurrency tests cover tenant substitution, pre-persistence redaction, immutable approval decisions, atomic idempotency reservation/replay, provider degradation, event cursor replay, and checkpointer lifecycle.

## Production boundary

Do not expose the current API to a network as a production multi-user service using `AMC_AUTH_MODE=local`. Before production deployment, integrate a verified authentication/authorization provider, configure durable production persistence, run production-specific dependency/security scans, and validate deployment/runtime bindings in the target environment.
