# Capability gap register

**Baseline:** `master` at `c6b5a700`. Each gap links to evidence in `docs/system_audit.md` (F-xx) or the generated inventory.

- **Priority:** P0 is reliability, security, truthfulness and the core pipeline. P1 is the production suite and integrations. P2 is optimisation and scale.
- **Complexity:** S, M, L, XL. **Risk:** L, M, H.
- **Provider choice:** where a gap needs an external provider, the provider is the owner's decision. This register names none and claims no integration.
- **Standard controls:** every gap that adds an external effect also gets the standard controls (§0). They are not repeated in each row.

## 0. Standard controls for any external effect

| Control | Requirement |
|---|---|
| Dispatch | Through the ACE v12 gateway only. |
| Approval | One approval bound to the exact binding hash. Separation of duties in production. |
| Budget | Reserved before dispatch. |
| Credentials | Per-tenant reference, never in payloads or logs. |
| Retries | Timeout and retry policy with a shared budget. |
| Unknown outcomes | Become UNKNOWN, then reconcile. No blind retry. |
| Compensation | Defined where possible; COMPENSATION_UNCONFIRMED is recorded when unsure. |
| Rate limiting | Per route and per provider. |
| Kill switches | Freeze and kill switch available. |
| Live activation | Per-operation activation record. No global live switch. |

## P0

> **M0 status (this increment):** G-01 to G-04 are implemented. Residuals are stated under each gap and in `docs/production_completion_plan.md`.

**G-01 · governance/QA · Constant completion scores (F-01)**
- **Status:** IMPLEMENTED for evidence and quality (`NOT_MEASURED`), and for coverage (computed from the criteria). **Residual:** `confidence` is still caller-supplied, because the column is `NOT NULL` and no calibrated estimator exists. F-13: the criteria passed by the runtime remediation paths are hard-coded `SATISFIED`, so the coverage they record reflects those constants.
- **Current:** `CompletionEvaluation.evidence_score` and `quality_score` are set to `proof_coverage` literals (0.25, 0.67, 1.0).
- **Required:** a score is either computed from a named, recorded measurement or reported as `NOT_MEASURED`.
- **Inputs → outputs:** criteria results → evaluation where every score names its source.
- **Tools:** none.
- **Schema:** Pydantic and Zod `quality_score`/`evidence_score` become `number | "NOT_MEASURED"`, plus a parity fixture.
- **Controls:** none new.
- **Tests:** no constant score survives; existing proof tests still pass; Zod parity.
- **Complexity / risk:** S / L (contract change behind backward-compatible readers).

**G-02 · contracts · Provenance Zod parity (F-05)**
- **Status:** IMPLEMENTED. The Zod twin carries `route`, `profile_hash`, `usage`, `usage_reported` and `unreported_token_estimate`, with defaults for older rows. A parity test fails if the backend writes a field the twin lacks.
- **Current:** Zod `GenerationProvenanceSchema` strips `route`, `profile_hash`, `usage_reported` and `unreported_token_estimate`.
- **Required:** the twin carries them, and the UI shows unknown usage and fallback routes.
- **Schema:** Zod only.
- **Tests:** a fixture recorded from a real run parses with all fields present.
- **Complexity / risk:** S / L.

**G-03 · deployment · Environment and dependency hygiene (F-06, F-10)**
- **Status:** IMPLEMENTED for documentation: all 19 variables are in `.env.example`, blank by default, and a test fails on any new undocumented variable. Blank values are now tolerated at the three call sites that would have failed on `int('')`. **Residual:** `opentelemetry` is still not declared as a dependency; the test that needs it still depends on CI's transitive install.
- **Current:** 19 environment variables are read but undocumented, including secrets and safety switches. `opentelemetry` is undeclared.
- **Required:** every variable is in `.env.example` with its purpose and secret status, and the inventory's undocumented list is empty or justified. Optional dependencies are declared as extras, and tests skip cleanly when an extra is absent.
- **Tests:** an inventory check (documented ⊇ read, minus a justified allowlist); a fresh install passes the suite.
- **Complexity / risk:** S / L.

**G-04 · QA · Non-hermetic test (F-09)**
- **Status:** IMPLEMENTED. The test uses a unique name per run and passes on a database that already holds the earlier run's rows.
- **Current:** a fixed display name collides on re-run against the same SQLite file.
- **Required:** unique names so re-runs pass.
- **Tests:** run the file twice against one database; both runs pass.
- **Complexity / risk:** S / L.

**G-45 · governance · Remediation paths record hard-coded criteria (F-13, new in M0)**
- **Current:** `api/routes/runtime.py` records completion with criteria that are always `SATISFIED`, including when the run did not complete.
- **Required:** each criterion status is derived from the observed state it names (for example, the remediated run's status, the recovery case's status, the regenerated approval's status). A criterion with no observation is `UNSATISFIED` or `STALE`, never `SATISFIED`.
- **Schema:** none.
- **Tests:** a non-completed remediation records a non-`COMPLETE` verdict; criteria match the observed status for each path.
- **Complexity / risk:** M / M (changes recorded verdicts on remediation paths).

**G-05 · reliability · Async agency runs (F-02)**
- **Current:** the graph runs inside the HTTP request.
- **Required:** create returns a job id. Progress comes from real start and completion events. SSE stream; cancellation; lease, heartbeat and fencing through the existing durable runtime; a worker restart resumes from the checkpoint.
- **Inputs → outputs:** brief → job id, then the event stream, then the run result.
- **Tools:** existing durable runtime and checkpoints.
- **Schema:** reuse `durable_runs`; a new job-type value, no new table expected.
- **Controls:** a cancel cannot cancel an approved delivery mid-write; approval binding is unchanged.
- **Tests:** crash between stages resumes; duplicate submit is idempotent; cancel; SSE ordering; stale-worker write rejected.
- **Complexity / risk:** L / M.

**G-06 · governance · Budget allocation API (F-07)**
- **Current:** `/actions/budget` offers GET and simulate only.
- **Required:** an authorized, audited allocation endpoint with compare-and-set; allocations are approval-bound for spend roles.
- **Schema:** possibly an allocation history table (migration).
- **Controls:** a governance role; separation of duties.
- **Tests:** a concurrent compare-and-set conflict; unauthorized role 403; cross-tenant 404; audit chain intact.
- **Complexity / risk:** M / M.

**G-07 · security · Shared rate limits (F-07)**
- **Current:** process-local spacing in `ModelRouter` only; no action limiter.
- **Required:** per-route and per-provider limits with `Retry-After`, shared through the database across workers.
- **Tests:** a limit holds across two processes; `Retry-After` is present; nothing is starved.
- **Complexity / risk:** M / M.

**G-08 · security · Step-up authentication (F-07)**
- **Current:** `STEP_UP_UNAVAILABLE` blocks R5 and step-up actions.
- **Required:** server-verified step-up bound to actor, session and action binding hash, with expiry and single use.
- **Tools:** the identity provider's MFA or re-auth capability. **Owner decision needed.**
- **Tests:** replay refused; expired refused; another actor's step-up refused; a different action refused.
- **Complexity / risk:** M / H.

**G-09 · integration · Per-operation live activation framework (F-12)**
- **Current:** `live_enablement()` returns DISABLED, with no switch.
- **Required:** an activation record per (operation, provider, tenant) holding credential reference, scopes, health check, test evidence and operator approval. LIVE dispatch is allowed only for an activated operation, and an absent record blocks only that operation.
- **Schema:** an activation-records table (migration).
- **Controls:** activation is itself an approval-bound governance action.
- **Tests:** activation without evidence refused; a revoked record blocks immediately; other operations unaffected.
- **Complexity / risk:** M / H.

**G-10 · integration · Model profile settings (I03 limit)**
- **Current:** only the deployment default is configurable.
- **Required:** project and tenant profiles via an authorized, audited API. Precedence is already implemented in `resolve_profile`.
- **Schema:** a profile settings table, or project metadata with compare-and-set.
- **Tests:** precedence end to end; a viewer cannot write; a pinned run is unaffected by a later change.
- **Complexity / risk:** M / L.

**G-11 · handoff · `HANDOFF_PACKAGE` contract (Phase 9)**
- **Current:** pieces exist (workspace export, artifact bindings, release receipt, the approval subject hash) but there is no single package contract.
- **Required:** a typed package covering the brief's 16 sections. It is generated from existing records only, and a section with no source data says so.
- **Schema:** a Pydantic and Zod contract plus a fixture. Probably no table: the package is assembled from existing records and itself persisted as an artifact.
- **Tests:** every listed hash re-reads to identical bytes; approval-binding mismatch detected; a missing section reported, never fabricated.
- **Complexity / risk:** M / M.

**G-36 · deployment · Production activation (external)**
- **Current:** no deployed environment has been verified.
- **Required:**
  - Postgres with migrations and a tested backup and restore.
  - Supabase Auth identities and explicit memberships.
  - Exact CORS origins.
  - Secrets configured.
  - Durable storage.
  - A worker with heartbeat.
  - Telemetry export.
  - An exact-revision smoke test: invalid-token denial, cross-tenant denial, replay, independent approval, stale-subject rejection, checkpoints, SSE and recovery.
- **Blocked on:** deployment accounts and authorization. **Owner action.**
- **Complexity / risk:** L / H.

**G-37 · security · Signing key custody**
- **Current:** deliverables are UNSIGNED without `AMC_DELIVERY_SIGNING_KEY`, and release evidence is unsigned.
- **Required:** an externally held key, key rotation, and verification of old manifests after rotation.
- **Blocked on:** key custody choice. **Owner.**
- **Tests:** signature verifies; tamper detected; rotated key verifies old manifests through its key id.
- **Complexity / risk:** M / H.

## P1

**G-12 · research · Semantic retrieval and research engine (F-08)**
- **Current:** KnowledgeOps stores claims with an evidence score, but has no embeddings, no vector retrieval and no search adapter.
- **Required:**
  - Search through an approved adapter.
  - Fetch with destination allowlist and SSRF protection.
  - Parse with size and format limits.
  - Every claim records source URL, retrieval date, confidence and corroboration.
  - Embeddings scoped by tenant and project.
  - Freshness and permissions on retrieval.
- **Tools:** a search provider and an embedding model. **Owner choice.**
- **Schema:** an embeddings table (pgvector or equivalent). Migration.
- **Tests:** cross-tenant retrieval returns nothing; SSRF to private ranges refused; injected instructions in fetched pages are treated as data; a stale source is flagged.
- **Complexity / risk:** L / H.

**G-13 · strategy · Universal brief compiler**
- **Current:** `intake/compile_intent` is deterministic and text-only; the creative runtime has its own `MissionIR`.
- **Required:**
  - One MissionIR from text, files, URLs, images and structured JSON.
  - Mission-type classification.
  - Unknowns recorded, never guessed.
  - Publish, spend and send stay `FORBIDDEN_TO_INFER`.
- **Tools:** file parsers; vision or OCR is optional and a provider gap.
- **Tests:** facts keep source spans; an injected "approve and publish" in an upload stays an untrusted claim.
- **Complexity / risk:** L / M.

**G-14 · brand · Brand knowledge graph extensions**
- **Current:** the VNEXUS genome and temporal graph exist.
- **Required:** node types for purpose, voice, lexicon, audience, JTBD, proof assets, legal constraints and so on. Every node versioned, hashed, permission-scoped and evidence-linked. Drift checks compare against the approved genome.
- **Schema:** VNEXUS graph node kinds (migration if new columns are needed).
- **Tests:** unauthorized change to an IMMUTABLE key refused; drift detector flags a seeded violation.
- **Complexity / risk:** L / M.

**G-15 · strategy · Prompt ledger outcomes**
- **Current:** `ConceptLedger` and the VNEXUS prompt genome exist; no outcome linkage.
- **Required:** link prompts to approval, rejection, QA and performance records.
- **Tests:** lineage from asset back to its prompt; no outcome recorded without a source.
- **Complexity / risk:** M / L.

**G-16 · brand · Naming checks**
- **Current:** none (F-11).
- **Required:** trademark pre-screen, domain and handle availability, pronunciation and linguistic checks. Results carry the source and date, and legal review is required before any claim of clearance.
- **Tools:** registry and availability providers. **Owner choice. PROVIDER_GAP.**
- **Tests:** a "clear" verdict is never emitted without a recorded source.
- **Complexity / risk:** M / H (legal).

**G-17 · print · Print production and preflight (F-11)**
- **Current:** no CMYK, dieline, bleed or preflight checks.
- **Required:** a print manifest (dimensions, bleed, colour mode, fonts outlined, resolution, linked assets) plus deterministic preflight. Anything not press-verified is labelled a pre-press draft needing vendor confirmation.
- **Tools:** local PDF and colour tooling. **The dependency must be chosen and licence-checked.**
- **Tests:** a seeded RGB-only, missing-bleed or low-resolution file fails preflight; a correct file passes.
- **Complexity / risk:** L / M.

**G-18 · motion · Motion export**
- **Current:** SVG frames and FFmpeg exist; no Lottie export and no motion tokens.
- **Required:** motion tokens in DTCG; optional Lottie JSON when a validated writer exists; a reduced-motion alternative for every animated asset.
- **Tests:** reduced-motion variant present; JSON validates against its schema.
- **Complexity / risk:** M / L.

**G-19 · sonic · Sonic identity**
- **Current:** none.
- **Required:** briefs and specifications only until an audio provider is reviewed.
- **Tools:** an audio provider. **PROVIDER_GAP.**
- **Complexity / risk:** S (specs) / M (rights).

**G-20 · web · Design-to-code generator**
- **Current:** `UIUX_SPEC_READY` and the Foundry experience twin produce HTML; no React or Next.js output for a client project.
- **Required:** components generated from the UI/UX IR and design tokens inside the Node sandbox (G-21), passing typecheck, lint, tests, axe/WCAG 2.2 AA, keyboard and reduced-motion checks.
- **Tests:** a generated page passes every check; an injected inaccessible component fails.
- **Complexity / risk:** XL / M.

**G-21 · engineering · Node sandbox**
- **Current:** the code sandbox is Python-only (`py_compile` allowlist).
- **Required:**
  - A Node adapter in the fabric.
  - Locked dependency acquisition kept separate from untrusted build execution.
  - No network, no secrets, scrubbed environment, resource limits.
  - Three build attempts per logical task, persisted.
  - The baseline is preserved when a candidate fails.
- **Tests:** network attempt blocked; secret not visible; fourth build refused; a failed candidate leaves the baseline intact.
- **Complexity / risk:** L / H.

**G-22 · image · Image generation adapters**
- **Current:** `t2i_image_generate` is PROVIDER_GAP; R2 diffusion BLOCKED; VNEXUS hosted media DISABLED.
- **Required:**
  - Local first, then reviewed hosted providers through the VNEXUS media fabric.
  - Every output records prompt hash, model and provider, seed, licence, safety result, parent concept and approval state.
  - Real-person likenesses and protected characters are refused.
- **Tools:** licensed local weights, or a hosted provider. **Owner choice.**
- **Tests:** bytes are re-read and their hash verified; a refusal path; `can_claim_generated` is false for mocks.
- **Complexity / risk:** L / H.

**G-23 · video · Video pipeline completion**
- **Current:** FreeVideoForge plus `ffprobe` verification and Blender turntables exist.
- **Required:** captions (VTT/SRT), cutdowns per platform, thumbnails, and a render manifest (resolution, fps, codec, duration, audio, captions, sources, provenance, verification).
- **Tests:** caption timing inside duration; manifest fields re-derived from `ffprobe`; AI-video steps stay PROVIDER_GAP.
- **Complexity / risk:** L / M.

**G-24 · content · Content engine claim lineage**
- **Current:** ContentAtoms exist.
- **Required:** every public-facing claim is evidence-linked or labelled opinion, hypothesis or creative concept; channel adaptations inherit lineage.
- **Tests:** an unlinked factual claim blocks approval.
- **Complexity / risk:** M / M.

**G-25 · SEO · SEO and GEO output (F-11)**
- **Current:** local SEO audit only; `seo_search_volume` is PROVIDER_GAP; no sitemap or schema.org output.
- **Required:** sitemap, robots and JSON-LD generation with validation; keyword data only from a reviewed provider, otherwise NOT_MEASURED.
- **Prohibited:** link schemes, spam and deceptive schema.
- **Tests:** JSON-LD validates; no invented search volumes.
- **Complexity / risk:** M / L.

**G-26 · integration · Publishing adapters (CMS and social)**
- **Current:** `SandboxCmsDraft` and `SandboxCmsPublish`; publication DRY_RUN_ONLY.
- **Required:** per-provider live adapters under §0 and G-09.
- **Blocked on:** provider choice, credentials, authorization.
- **Complexity / risk:** L each / H.

**G-27 · integration · Email and SMS**
- **Current:** `SandboxEmailSend` only.
- **Required:** live adapters under §0, plus consent, unsubscribe, suppression lists and recipient deduplication. A batch of 0 recipients is not sent.
- **Blocked on:** provider choice.
- **Complexity / risk:** L / H.

**G-28 · integration · Paid media**
- **Current:** `SandboxAdsSpend`; paid media PLANNING_ONLY (`no_spend_mvp`).
- **Required:** spend only with a spend-role approval, a budget reservation and reconciliation of reported spend.
- **Blocked on:** provider and spend authority.
- **Complexity / risk:** XL / H.

**G-29 · analytics · CRM and analytics ingest**
- **Current:** first-party lifecycle analytics; marketing rates only from MEASURED rows.
- **Required:** read adapters for analytics and CRM with source, time window and sampling recorded. Missing data stays NOT_MEASURED.
- **Tests:** an empty result is not reported as zero.
- **Complexity / risk:** L / M.

**G-30 · automation · Workflow builder (NL → DAG → simulate → live)**
- **Current:** the compiled planner and method router are PLANNING_ONLY, and Layer 1 does not consume their plans.
- **Required:** compile an operator outcome into a node DAG (inputs, outputs, tools, permissions, retries, cost ceiling, approval). Simulation is mandatory; live execution only through the fabric and gateway.
- **Tests:** a simulation causes no effects; a live node without activation is blocked.
- **Complexity / risk:** XL / H.

**G-31 · governance · LEG and ETH detectors (F-11)**
- **Current:** PII and secret redaction, a brand-safety evaluator, and a regulated-claim pre-filter in the prompt compiler.
- **Required:**
  - Detectors for dark patterns, fake urgency or scarcity, fake testimonials and undisclosed synthetic media.
  - An AI-disclosure requirement.
  - Regulated-claim escalation to human legal review.
- **Tests:** seeded violations are caught; benign controls pass. Detectors are deterministic where possible.
- **Complexity / risk:** M / M.

**G-32 · QA · Evaluation system**
- **Current:** heuristic evaluators; faithfulness and hallucination are NOT_MEASURED by design.
- **Required:** deterministic validators, golden datasets and regression suites. Model critics only with provenance, confidence and human escalation.
- **Tests:** an evaluator regression fails CI.
- **Complexity / risk:** L / M.

**G-33 · learning · Feedback loop**
- **Current:** a tenant-scoped `LearningLedger` exists.
- **Required:** ingest feedback; promote improvements only after evaluation and a governed approval; keep before/after comparisons and rollback. No training on customer data without tenant consent.
- **Tests:** an unapproved improvement never changes defaults; consent off blocks use.
- **Complexity / risk:** L / M.

**G-34 · code health · Legacy generic graph (F-03)**
- **Required:** remove `graph/build.py` and `graph/nodes/*`, or document and quarantine them, after confirming there are no external users.
- **Tests:** suite green; nothing imports them.
- **Complexity / risk:** S / L.

**G-35 · code health · Unwired modules (F-04)**
- **Required:** for each of `durable/proofs.py`, `creative/brand_production.py`, `quality/grounded_evaluator.py`, `quality/request_accut.py` and `reliability/api.py`, either wire it into a reachable path (with tests) or label it as library-only in its docs.
- **Complexity / risk:** M / L.

**G-38 · observability · Telemetry**
- **Current:** OTel is opt-in and nothing is exported.
- **Required:** export configured per environment, dashboards and alerts, verified as working in each target environment.
- **Blocked on:** collector or vendor credentials.
- **Complexity / risk:** M / M.

**G-39 · UI · Mission Control truthfulness surfaces**
- **Current:** the Agency OS Safety state, the debt row and existing panels.
- **Required:**
  - A readiness panel that separates code support, credentials, permissions, dependencies, verification, deployment, worker heartbeat and live eligibility.
  - A repair card for each capability: missing condition → smallest repair → test → owner.
  - An approval change preview: what changed since approval.
- **Tests:** a component per state; E2E that a disabled control always explains itself.
- **Complexity / risk:** M / L.

## P2

| Gap | Category | Required | Depends on | Complexity / risk |
|---|---|---|---|---|
| G-40 | agents | Multi-agent specialisation: specialists bound to N3 contracts, with bounded concurrency. | G-30 | L / M |
| G-41 | product | Marketplace-ready templates: versioned, rights-checked workflow and campaign templates. | G-30, G-11 | M / M |
| G-42 | strategy | Scenario models for plans and forecasts, always labelled SIMULATION with their assumptions. | G-29 | M / M |
| G-43 | operations | Enterprise scale: quotas, multi-region data residency, a tenant-level audit export. | G-36 | XL / H |
| G-44 | integration | Telephony, only after the owner selects a provider and a use case. Per-call consent and recording policy; unknown outcomes are reconciled; no automatic redial. | G-09 | L / H |
