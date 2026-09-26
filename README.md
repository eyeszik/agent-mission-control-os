# Agent Mission Control OS

Agent Mission Control OS is the execution and governance layer for an autonomous AI branding, marketing, product, and digital-delivery agency. The current production foundation combines LangGraph + FastAPI + Next.js with durable state, human approval gates, event replay, first-party lifecycle analytics, multi-tenant authorization, and fail-closed external-action controls.

## Product boundary

The user-facing product is intended to operate as an **autonomous full-service digital agency**. Agent Mission Control is the internal agency operating system that coordinates research, strategy, brand development, creative production, product/design workflows, engineering, launch, marketing, analytics, approvals, and governance.

The currently implemented agency workflow is:

`brief_intake → brand_strategy → creative_concepting → copywriting → design_brief → campaign_assembly → brand_safety_qa → hitl_gate → delivery`

Broader product-development, creative-studio, growth, publishing, and paid-media departments are subsequent agency-expansion layers built on this control plane.

## Current implementation status

### Implemented

- Human-in-the-loop approval before delivery.
- Server-derived identity and authorization boundaries; browser-supplied tenant/reviewer values are not authoritative.
- Local loopback authentication for development.
- Production **Supabase Auth** bearer-token verification.
- Server-side `amc.tenant_memberships` authorization for tenant/project access.
- SQLite local/CI persistence and **PostgreSQL production persistence**.
- PostgreSQL-backed LangGraph checkpoints in production mode.
- Recursive input sanitization/redaction before run persistence/checkpointing.
- Atomic approval decisions and scoped idempotency with deterministic replay.
- Explicit model/provider provenance and `FALLBACK_DEGRADED`; degraded generation cannot be delivered.
- Truthful evaluation fields: unsupported grounding metrics remain `NOT_MEASURED`.
- Cursor-addressable persisted run events and SSE replay/tailing.
- First-party `amc.analytics_events` storage and authenticated analytics ingestion.
- Automatic agency lifecycle analytics for creation, HITL, delivery, failure, rejection, publication previews, and spend-authorization requests.
- Publication audit/dry-run boundary; no live publication executor is installed.
- Paid-media authorization ledger; no live spend executor is installed.
- Canonical OpenAPI coverage for agency, approval, event, analytics, and operations APIs.
- Vercel deployment manifests for frontend/backend project roots.
- Next.js `16.3.0` with an audited lockfile-pinned production dependency graph.
- **Browser E2E release gate** using pinned Playwright/Chromium against the real local Next.js + FastAPI stack.
- CI production-readiness and critical-file integrity gates.
- Deterministic **UI/UX design compiler** (`agency/ui_ux`) producing governed specs and `UI_UX` prompt packages, with one DTCG 2025.10 token compiler and frontend token gates — see [`docs/ui-ux-design-compiler.md`](docs/ui-ux-design-compiler.md).

### Live infrastructure already prepared

- Supabase production project restored and healthy.
- `amc` production schema migrated.
- Production tenant `tenant_1` and project `proj_1` seeded.
- Supabase security advisor has no actionable security findings from the AMC schema.
- Required foreign-key covering indexes were added in the second production migration.

### Deliberately not claimed as active production

- No Agent Mission Control Vercel project is currently verified/bound to this repository.
- Production environment variables have not been injected into a verified Vercel project through this repository setup.
- No Supabase Auth user currently exists for AMC, so no real production membership has been granted.
- Authenticated production smoke testing has therefore not been performed.
- Live external campaign publication is disabled until a concrete provider adapter is installed and reviewed.
- Paid-media execution is disabled until a concrete provider adapter, approval policy, budget controls, and execution tests exist.
- The UI/UX compiler produces specifications and prompt packages only; it does not generate, render, or publish interfaces, and it runs no browser or assistive-technology verification.
- Initial agency execution remains synchronous; persisted SSE events provide replay/tailing but do not fabricate pre-node start timing.

See [`docs/production-activation.md`](docs/production-activation.md) for the exact activation gate.

## Repository layout

- `services/langgraph/` — FastAPI API, LangGraph workflow, persistence, security, analytics, evaluation, integrations, tests.
- `apps/web/` — Next.js Mission Control frontend and production authentication UI.
- `apps/web/e2e/agency-smoke.spec.ts` — browser release smoke test.
- `packages/shared/` — shared runtime contracts and canonical OpenAPI artifact.
- `supabase/migrations/` — production schema migrations.
- `scripts/verify_repository_invariants.py` — repository/contract drift checks.
- `scripts/verify_production_readiness.py` — fail-closed production-configuration and capability checks.
- `scripts/verify_manifest.py` + `manifest.json` — critical-runtime integrity verification.
- `docs/production-activation.md` — external activation and production smoke-test runbook.

## Local setup

### Prerequisites

- Node.js **20.9+**
- pnpm version pinned by the root `packageManager` field
- Python 3.11 recommended for CI parity

### 1. Configure environment

Copy `.env.example` into your local environment. Never commit secrets.

Minimum local configuration:

```text
AMC_ENV=local
AMC_AUTH_MODE=local
AMC_DATABASE_BACKEND=sqlite
AMC_LOCAL_USER_ID=local-operator
AMC_LOCAL_TENANT_ID=tenant_1
AMC_LOCAL_PROJECT_IDS=proj_1
AMC_LOCAL_ROLE=operator
AMC_DB_PATH=amc_local.db
AMC_CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_AUTH_MODE=local
```

Set `OPENAI_API_KEY` only if real provider generation is desired. Without it, generation is explicitly degraded and delivery remains blocked.

### 2. Install

```bash
pnpm install --frozen-lockfile
pnpm --filter @amc/shared build
python -m pip install -e "./services/langgraph[dev]"
```

### 3. Run backend

```bash
python -m uvicorn services.langgraph.app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 4. Run frontend

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 pnpm --filter @amc/web dev --hostname 127.0.0.1 --port 3000
```

## Validation

```bash
python scripts/verify_repository_invariants.py
python scripts/verify_production_readiness.py
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

### Browser E2E release gate

With the local backend/frontend running:

```bash
pnpm --filter @amc/web exec playwright install chromium
E2E_BASE_URL=http://127.0.0.1:3000 pnpm --filter @amc/web test:e2e
```

CI starts the real local stack, installs Chromium, executes the browser gate, and uploads traces/screenshots/video on failure. The test intentionally runs without a model-provider key so it proves provider absence is reported as degraded rather than falsely treated as successful delivery.

## Production activation

Production startup fails closed unless the required Supabase/Postgres/CORS configuration is valid. Publication must remain `disabled` or `dry_run`, and paid-media execution must remain `disabled`, until reviewed adapters are installed.

Do not expose `AMC_AUTH_MODE=local` to a network. Production activation must use Supabase authentication, explicit membership assignment, a verified deployment binding, deployment-secret injection, and authenticated smoke tests as defined in the production activation runbook.
