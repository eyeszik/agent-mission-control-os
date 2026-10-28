# Agent Mission Control OS

Agent Mission Control OS is the execution and governance layer for an autonomous AI branding, marketing, product, and digital-delivery agency. The current production foundation combines LangGraph + FastAPI + Next.js with durable state, human approval gates, event replay, first-party lifecycle analytics, multi-tenant authorization, and fail-closed external-action controls.

## Product boundary

The user-facing product is intended to operate as an **autonomous full-service digital agency**. Agent Mission Control is the internal agency operating system that coordinates research, strategy, brand development, creative production, product/design workflows, engineering, launch, marketing, analytics, approvals, and governance.

The currently implemented agency workflow is:

`brief_intake → brand_strategy → creative_concepting → copywriting → design_brief → campaign_assembly → brand_safety_qa → hitl_gate → delivery`

Runs execute *inside* durable **projects** (the Project OS, [`docs/project-os.md`](docs/project-os.md)): every run, conversation, artifact version, content item, schedule, publication attempt and memory record is scoped to `tenant → project`. Product-development, creative-studio, content, search, social, growth, CRM and web/app work are represented as governed workstreams over the same artifact graph; publication is dry-run only and paid media is planning-only until reviewed provider adapters exist.

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
- Next.js `16.3.8` (exact pin; patched for GHSA-vcvr-r3jv-pc5j) with an audited lockfile-pinned production dependency graph.
- **Browser E2E release gate** using pinned Playwright/Chromium against the real local Next.js + FastAPI stack.
- CI production-readiness and critical-file integrity gates.
- Deterministic **UI/UX design compiler** (`agency/ui_ux`) producing governed specs and `UI_UX` prompt packages, with one DTCG 2025.10 token compiler and frontend token gates — see [`docs/ui-ux-design-compiler.md`](docs/ui-ux-design-compiler.md).
- Deterministic **prompt families** (`agency/prompt_families`) and selectively routed copy, attention-hook and visual-prompting guidance built from the v10 brand/content/visual prompt spec: series invariants, variation axes, concept ledger, exact-text render stages, evidence ceiling and computation provenance. Compiles prompts only; no media, ads, products, publication or spend. See [`docs/brand-content-visual-prompt-os.md`](docs/brand-content-visual-prompt-os.md).
- **Method routing and delegation** — a deterministic compiler from an objective to the minimal justified stack of established methods (18 families, 128 methods), a proof-carrying delegation DAG and canonical RoleOS work orders and waves; the compiler itself is planning only — see [`docs/method-routing-delegation.md`](docs/method-routing-delegation.md).
- **Workspace packages and backend core** — tier-1 TypeScript packages (`@amc/errors`, `@amc/config`, `@amc/logger`, `@amc/constants`, `@amc/db`, `@amc/testing`) used by `apps/web`, and a Python-native `services/langgraph/core` with the same vocabularies, error envelope and config/logging conventions; the stacks share semantics, not code — see [`docs/workspace-packages.md`](docs/workspace-packages.md).
- **Execution fabric** — a governed execution plane over the compiled planners' waves: truthful per-cell states instead of `EXECUTOR_GAP`, server-only authority, a two-phase write-ahead with tenant-scoped idempotency and crash reconciliation, ProjectOS artifact versions with permits, receipts and read-back observations, and deterministic domain skills (DTCG tokens, SVG marks, WCAG 2.2 DOM audit, network-isolated code sandbox, FreeVideoForge verification, local SEO checks). LOCAL/SANDBOX only; text/image/video generation and search demand are reported as provider gaps, external publication and spend stay live-gated, and every deliverable stops at the human approval boundary — see [`docs/execution-fabric.md`](docs/execution-fabric.md).
- **Creative search runtime** — a bounded, deterministic creative runtime (`agency/creative`) with MissionIR/ArtifactIR contracts, a hash-pinned capability registry with reuse dispositions, T0–T4 topology selection, a rights-safe budgeted context portfolio, bounded concept search (population ≤ 4, generations ≤ 2) with an uncertainty-aware Pareto front, a non-compensable hard gate plus lineage-blind critics, ≤ 1 correction checked by TriDiff, and HITL through the existing approvals table bound to the artifact hash. No model, publication or spend; model-backed capabilities are provider gaps — see [`docs/creative-runtime.md`](docs/creative-runtime.md).
- **Governed intake mission** — one path from a raw request to a release decision (`agency/intake`). It compiles the intent deterministically, binds the request to exactly one accessible project (hard access filters first; ambiguity pauses), and builds a hashed context capsule from Project OS memory under the existing authority rules. It executes through the existing execution fabric, verifies the persisted bytes independently, requests approval bound to the exact content hash through the existing approvals route, and applies a fail-closed release gate. Simulation is explicit and never release-eligible; missing providers stay blocked; publish, spend and send are never dispatched — see [`docs/intake-mission.md`](docs/intake-mission.md).
- **Local visual engine and durable runtime** — real local production with no hosted image/video API (`agency/visual`): Blender Cycles stills (R1), FFmpeg turntables from rendered frames (R5) and the deterministic SVG mark (R4), each persisted as a Project OS `media_asset`, reopened by an independent Q0–Q4 verifier (Q5–Q7 stay human) and released only through the shared hash-bound approval gate. Offline diffusion (R2) and Three.js (R3) are probed and reported as blocked when their dependencies are absent. Recurring work runs as bounded ticks over a persisted 20-state run FSM (`agency/durable`) with fenced leases, write-ahead intents keyed by a stable idempotency identity, pre-image crash reconciliation, negative knowledge and per-tick telemetry; G0–G4 governance, the build DAG and a command-backed verification seal are generated from code — see [`docs/local-visual-engine.md`](docs/local-visual-engine.md), [`docs/durable-runtime.md`](docs/durable-runtime.md) and [`docs/abc-v6-traceability.md`](docs/abc-v6-traceability.md).
- **Generative Creative Foundry** — a plain-language brief becomes a connected brand family rendered entirely on the host (`agency/foundry`): a deterministic CreativeGenome and thirteen visual grammars (including PSEM editorial); SVG logo family, icon family and poster with Chromium-rendered PNGs; DTCG tokens through the one token compiler; seeded variants with lineage within the creative caps; a working website section exercised in real Chromium across 12 interaction scenarios and counterfactual skins; a Blender package scene; and an FFmpeg logo reveal with a reduced-motion still. Every output is a Project OS artifact that is read back and verified, carries a proof state machine, depends on the genome (so genome changes invalidate it), and is approved only through the existing route. It has a Creative Foundry mode in Mission Control — see [`docs/creative-foundry.md`](docs/creative-foundry.md).
- **Website production line (UCPO)** — a WebsiteBrief becomes a verified, approval-gated static website (`agency/ucpo`, `/ucpo`, the Website Production section of `/agency`, CLI `website`). Every promise in the brief becomes a requirement with a structural id; a PSEM genome and DTCG tokens, a SiteArchitecture and WebsiteIR, and a Next.js static-export source tree (per-file SHA-256 manifest, `data-req` lineage, forbidden-construct scan, human-edit preservation) are stored as Project OS artifacts under their N3 roles. The generated source is untrusted: it is built only inside a verified sandbox (user/mount/network namespaces, read-only repository, scrubbed environment, resource caps, timeouts; otherwise `BLOCKED_ISOLATION`) and checked in real Chromium (axe-core, reflow at 320/768/1280, 200% text, reduced motion, keyboard focus, PSEM colour pairings, console, external requests, screenshots). Semantic coverage traces each requirement through IR → source → DOM with a debt ledger and an Intent Linker; a release proof binds every revision and is approved only through the existing route. Approval never deploys. Fifteen discipline routers, five presentation systems and sixteen prompt modules are registered; hosted image/video generation is a capability gap — see [`docs/ucpo/README.md`](docs/ucpo/README.md).
- **VNEXUS brand book** — the approved brand genome compiles into a versioned, brandless 24-page template, deterministic page prompts and a locally rendered book whose every page is measured in Chromium (overflow, exact copy, contrast, canonical-mark continuity). Intake evidence and proposals become genome drafts for the existing review; production refuses unresolved values; approval binds the book's bytes and release is a local record. Unchanged pages are reused by dependency hash, so a copy edit rebuilds 4 of 24 pages — see [`docs/vnexus-brandbook.md`](docs/vnexus-brandbook.md).
- **ACE × AVIC visual compiler** — a PromptIR brief, optional raster references and a selected style profile compile into a typed SceneIR and a native SVG (`agency/avic`, CLI `avic`). Brief text is data: instruction-like content, external effects and third-party marks are refused, unsupported capabilities are named, never approximated. Every SVG passes an allowlist validator on top of `svg_safety`, renders through the existing network-isolated Chromium rasterizer, and is checked by an independent evaluator that reads the bytes (exact text, palette ΔE, single accent, WCAG contrast, rendered ink). H3 causal repair fixes failed checks with bounded, rollback-safe proposals; H1 reconstructs raster references as native SVG with measured fidelity; H2/H4 govern brand mutations and reproducible variants; H5 adds material shading with provenance and no physical claim. Stages are Project OS artifacts under N3 roles; approval binds the SVG's content hash and release is a local record with no external effect. Operators reach it through `/avic` and the Visual Compiler section of `/agency`, where a stale edit is a 409 conflict, never an overwrite — see [`docs/avic.md`](docs/avic.md).
- **VNEXUS ACE** — a persisted, governed brand genome and the creative layers built on it (`agency/vnexus`, `/vnexus`, the VNEXUS Studio mode). Versioned genome layers inherit brand → project → page → component → asset with immutable constraints, are approved only through the existing approvals route (bound to the content and ancestor hashes, separation of duties) and are never edited once approved; a hash-chained audit log, a bitemporal knowledge graph with impact and evidence queries, and a creative multiverse whose branches are compared against their base and can only be promoted through review. From an approved genome it compiles experiences (rendered and exercised in Chromium where a renderer exists), art-direction briefs with every claim classified, identity systems and procedural video with deterministic validators, all through a provider-neutral media fabric whose hosted providers are disabled. Campaign planning never invents metrics, a prompt genome feeds the unchanged five-pass compiler, and a design immune system and digital twin report and simulate without touching approved decisions — see [`docs/vnexus-ace.md`](docs/vnexus-ace.md).
- **ACE v12 governed Agency OS** — one gateway for every external action (`agency/actions`, `/actions`). It has a descriptive catalogue of all capabilities with truthful statuses; EXT-/ART- ids are reserved as `VOID_DETECTED`. A deterministic R0–R6 risk engine applies the union of class controls. Exact approval binding (payload, target, tenant, environment, policy version, dependency hashes, expiry) uses the existing approvals route, with separate owner/admin approval for money and governance. Every action runs a hash-chained, compare-and-set state machine, from proposal through reserved, dispatching, observing and verified, with `UNKNOWN → RECONCILING` by read-back. Spend is reserved atomically against ceilings per action, project, client, day and month. Freezes, an autonomy dial and a policy simulator are included. Sandbox fakes stand in for CMS, email, ads, storage deletion and role grants. A client-facing `/agency` app (`agency/agency_os`, `/agency-os`) covers clients, brief → plan preview → local work, exact approvals, evidence, revisions, a deliverable vault and verified delivery manifests. LIVE execution is disabled and has no enabling switch — see [`docs/ace-v12/README.md`](docs/ace-v12/README.md).
- **Delivery contracts** — an optional per-run `DeliveryContract` checked by a deterministic critic, a release candidate sealed *before* approval and bound to the approval subject, a release predicate over N2 / contract / approval / artifacts / dependencies / invalidation, a post-release receipt, and per-run workflow-version pinning (`AMC_CONTRACT_MODE=off|shadow|enforce`, default `off`) — see [`docs/unified-delivery.md`](docs/unified-delivery.md).
- **Project OS** — durable project workspaces (idempotent initializer, lifecycle, activity stream), artifact graph v2 over the N4 registry (compare-and-set versions, compare/restore/branch/merge, one-master-many-derivatives, dependency invalidation with a remediation queue), content-addressed local object storage, a hash-verified `projects/<tenant>/<project>/` workspace mirror that dual-materializes legacy run exports, project conversations, a prompt ledger, ContentAtoms with claim-lineage-preserving derivatives, a months-ahead calendar and **one** outbox-driven scheduler (publish, refresh, CRM journeys), scoped memory with an explicit authority order, KnowledgeOps, a persisted learning ledger with governed promotion, DAM with rights radar, a cinematic → FreeVideoForge bridge, workstream templates, brand drift reports, paid-media planning, a cost × quality router and a portfolio view — see [`docs/project-os.md`](docs/project-os.md).
- **Mission Council** — an idea runs through three seats on your choice of engine: LangGraph (native interrupt and `Command` resume), CrewAI (a sequential crew) or AutoGen (a bounded round-robin team with no code executor). George plans, Fable/Cipher runs a policy-first security audit, a person approves at the Sentinel gate through the existing approvals route, and Arty builds a validated UI scaffold. Missions are durable `runs` with hash-chained checkpoints, leases, retry, recovery and SSE timelines. Tools go through one deny-by-default gateway: least-privilege seat scopes, approval binding, single-use decisions, redacted audits and an allowlisted MCP stdio client. Blueprints extract the best parts of completed missions, and promotion re-verifies their timelines. Seats use a deterministic offline mock model unless `ENABLE_REAL_MODELS=true`; CrewAI, AutoGen and MCP are the optional `council` extra. UI at `/missions` — see [`docs/mission-council.md`](docs/mission-council.md).
- **Agency Operating Framework** — the version-pinned 24-module, 295-task agency catalog (SHA-256 pinned, schema- and semantics-validated before import) instantiated per project as task instances with reasoned applicability, compare-and-set state, and evidence refs resolved against their owning stores (Project OS knowledge, N4 evidence/decisions/artifacts with byte read-back, VNEXUS approved genomes). Verification is a server re-check by a second person; approval goes through the existing approvals route bound to the task's proof hash; five stage gates pass in order through approvals bound to their evaluation and go stale when evidence drifts. Meaning, Mutation, Probe, Renewal and Review are immutable, hash-sealed, non-authoritative assurance records. 13 KPIs are computed only from recorded measurements (`NOT_MEASURED` otherwise; synthetic inputs labelled). A new plan starts at 0 verified; release stays with delivery and no external effect is dispatched. UI at `/framework` — see [`docs/agency-operating-framework.md`](docs/agency-operating-framework.md).
- Deterministic **Compiled Agency planner** (`agency/compiled`) — deliverable backchain, RoleOS×N3 authority bridge, proof-carrying work orders, decision spine, mission cells/waves, causal invalidation and delta approval, S1–S13 digital twin; plans only, never executes — see [`docs/compiled-agency.md`](docs/compiled-agency.md).

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
- Project OS external execution: publication runs only through the dry-run provider (no live publisher is registered), CRM journeys never send, paid media plans but never mutates or spends, R2 object storage is an unverified binding that fails closed, knowledge *fetching* has no adapter, and video rendering needs Pillow + FFmpeg on the host (`LOCAL_ONLY`). No always-on scheduler worker is deployed; ticks run via `POST /projects/{id}/scheduler/tick` or `run_scheduler_tick`.
- The durable run runtime has no deployed worker: ticks are invoked explicitly, so it is not "always on". Local rendering is CPU-only on the reference host; renders are clean product renders, not certified photographs; offline diffusion and Three.js scenes are blocked until a licensed local model and the `three` dependency are installed; OpenTelemetry export is not configured.
- Creative Foundry: missions run synchronously and locally; React component generation, print/press contracts, extra scene kinds and motion templates are declared but not implemented; asset-discovery adapters are disabled; no human usability validation has been performed.
- VNEXUS ACE: no hosted media adapter exists (AI image/video shots stay blocked), provider jobs run synchronously, dashboard and web-application experiences are specification only, and the 14 original source prompts have not been supplied (the prompt inventory reports `SOURCE_REQUIRED`).
- ACE v12: every action provider is a sandbox fake; no real CMS, email, ad, storage or identity provider is bound, and LIVE stays refused. Step-up authentication does not exist, so R5 actions (e.g. deletion) are always blocked. Budget ceilings are operator-set in the database (no API). Delivery manifests are unsigned unless `AMC_DELIVERY_SIGNING_KEY` is configured. The new routes have no request rate limiter.
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
- `services/langgraph/agency/project_os/` — Project OS contracts and policies (workspace, storage, content, calendar, publishing, memory, knowledge, video bridge, routing, brand drift, workstreams); persistence in `persistence/project*.py` + `persistence/portfolio.py`; routes in `api/routes/{projects,project_ops,portfolio}.py`.
- `services/langgraph/agency/council/` — Mission Council engines, Sentinel policy and tool gateway; persistence in `persistence/council.py`, routes in `api/routes/missions.py`, UI in `apps/web/components/missions/`.
- `services/langgraph/agency/operating_framework/` — Agency Operating Framework catalog, bindings, task engine, ref resolution, assurance records and KPIs; persistence in `persistence/operating_framework.py`, routes in `api/routes/agency_framework.py`, UI in `apps/web/components/framework/`.
- `services/freevideoforge/` — local, zero-paid-API video renderer, bridged into projects (not imported) by `agency/project_os/video.py`.
- `scripts/export_to_drive.py` + `services/langgraph/integrations/drive_export/` — operator export of a project folder to Google Drive (service account or signed-in user, verified read-back) with a Notion record; dry run by default, runnable from `.github/workflows/export-to-drive.yml` — see `docs/drive-export.md`.

## Local setup

### Prerequisites

- Node.js **22.12+**
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

Set `OPENAI_API_KEY` (or select another provider with `AMC_LLM_PROVIDER`; see `docs/amc-i03-model-profiles.md`) only if real provider generation is desired. Without it, generation is explicitly degraded and delivery remains blocked.

Approvals are role-gated and separated from authorship: only `AMC_APPROVER_ROLES` (default `reviewer,approver,admin,owner`) may decide an approval, and the user who started a run cannot approve it. To approve your own runs in single-user local development, set `AMC_LOCAL_ROLE=admin` and `AMC_ALLOW_SELF_APPROVAL=true`; production configuration rejects the self-approval switch.

Every provider call has a timeout (`AMC_LLM_TIMEOUT_SECONDS`) and output cap (`AMC_LLM_MAX_OUTPUT_TOKENS`), token usage is recorded per call, and each run has a token budget (`AMC_MAX_TOKENS_PER_RUN`) that retries also draw from; an exhausted budget degrades generation, which blocks release. Run creation is limited per tenant (`AMC_MAX_RUNS_PER_TENANT_PER_HOUR`, `AMC_MAX_ACTIVE_RUNS_PER_TENANT`) and returns `429` with `Retry-After` when exceeded.

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
