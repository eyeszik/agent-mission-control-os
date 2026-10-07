# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Agent Mission Control OS is the execution and governance layer for an autonomous AI branding/marketing agency: LangGraph + FastAPI backend, Next.js frontend, durable state, human-in-the-loop approval gates, event replay, first-party lifecycle analytics, multi-tenant authorization, and fail-closed external-action controls (publication/paid-media stay disabled until real provider adapters exist).

Read `README.md` first — it is current and states the real implementation status (implemented / prepared / deliberately not claimed as active) more precisely than a summary here would. `docs/production-activation.md` is the exact production activation gate. `docs/agency-role-contracts.md` and `docs/agency-cli.md` document the kernel and its CLI in depth.

## Commands

### Install

```bash
pnpm install --frozen-lockfile
pnpm --filter @amc/shared build      # must run before typecheck/build elsewhere — apps/web imports @amc/shared's dist output
pnpm --filter "./packages/*" build   # also builds the tier-1 packages (@amc/errors, config, logger, constants, db, testing) in dependency order
python -m pip install -e "./services/langgraph[dev]"
```

### Run locally

```bash
python -m uvicorn services.langgraph.app.main:app --host 127.0.0.1 --port 8000 --reload
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 pnpm --filter @amc/web dev --hostname 127.0.0.1 --port 3000
```

Copy `.env.example`; minimum local config uses `AMC_ENV=local`, `AMC_AUTH_MODE=local`, `AMC_DATABASE_BACKEND=sqlite`. Without `OPENAI_API_KEY`, agency generation is explicitly `FALLBACK_DEGRADED` and delivery is blocked — that's intended behavior, not a bug, when testing without a key.

### Test

```bash
python -m pytest services/langgraph/tests -q                      # full backend suite
python -m pytest services/langgraph/tests/test_agency_cli.py -q   # single file
python -m pytest services/langgraph/tests -q -k test_name         # single test by name

pnpm --filter @amc/shared test                                    # vitest, packages/shared
pnpm --filter @amc/web test                                       # vitest, apps/web
pnpm --filter @amc/web exec playwright install chromium
E2E_BASE_URL=http://127.0.0.1:3000 pnpm --filter @amc/web test:e2e  # needs backend+frontend running; runs deliberately without a model key to prove degraded-mode reporting
```

### Lint / typecheck / build

```bash
ruff check <path>                          # no ruff.toml — defaults
python -m compileall -q services/langgraph scripts
pnpm --filter @amc/shared typecheck
pnpm --filter @amc/web typecheck
pnpm --filter @amc/shared build
pnpm --filter @amc/web build
```

### CI verifier gates (all seven must pass; CI runs them in this order)

```bash
python scripts/verify_repository_invariants.py
python scripts/verify_production_readiness.py
python scripts/verify_auth_bindings.py
python scripts/verify_ontology_parity.py
python scripts/verify_design_tokens.py
python scripts/verify_manifest.py
python scripts/verify_guidance_registry.py
```

`make gates` runs all seven. These are **text-scanning gates in places**, not just behavioral: `verify_auth_bindings.py` and `verify_production_readiness.py` grep tracked file source for specific literal substrings (e.g. `"AMC_AUTH_MODE must be supabase"` must appear verbatim somewhere in `app/config.py`). If you refactor wording in a file those gates check, re-run them before pushing — a semantically-equivalent rewrite can still fail a literal-substring check.

### Critical-file integrity manifest

`manifest.json` (schema `amc-integrity/v2`) pins git-blob SHAs for the security/authorization-boundary files (count them in `manifest.json`; 136 as of the creative runtime change) (auth, config, persistence, the N1–N4 kernel modules, CI workflow, verifier scripts themselves, etc.). Editing any tracked file drifts its hash and fails `verify_manifest.py`. Regenerate deliberately, never by copying a printed hash by hand:

```python
import hashlib, json
from pathlib import Path
ROOT = Path(".")
def sha(b): return hashlib.sha1(f"blob {len(b)}\0".encode() + b).hexdigest()
p = json.loads((ROOT / "manifest.json").read_text())
for e in p["files"]:
    e["git_blob_sha"] = sha((ROOT / e["path"]).read_bytes())
(ROOT / "manifest.json").write_text(json.dumps(p, indent=2) + "\n")
```
Then re-run `verify_manifest.py`. New security-boundary files should generally be added to the tracked set; pure content schemas / pure-math modules (e.g. `agency/artifacts/brand.py`, `agency/cli.py`) are deliberately left untracked, matching existing precedent — a hash pin is for authorization boundaries, not for every file.

### Agency CLI

```bash
python3 orchestrate_brand_pipeline.py plan --input sample_brief.json                            # or: make brand-plan
python3 orchestrate_brand_pipeline.py roles --department brand                                  # or: make brand-roles DEPT=brand
python3 orchestrate_brand_pipeline.py validate                                                  # or: make brand-validate
python3 orchestrate_brand_pipeline.py compile-prompts --input sample_prompt_request.json --json  # or: make prompt-compile
python3 orchestrate_brand_pipeline.py ui-ux --input sample_ui_ux_request.json                     # or: make ui-ux-compile
python3 orchestrate_brand_pipeline.py creative-run --input sample_creative_mission.json --compare  # or: make creative-run
```
`plan` **plans against the governance kernel only** — it resolves artifacts to roles, checks evidence floors, and walks the lifecycle guards. `compile-prompts` runs the claims-audit prompt compiler (see Architecture). Neither calls an LLM, and neither touches the real execution pipeline. `plan` exits 0 = clear, 1 = blocked (kernel guard failed), 2 = brief couldn't be interpreted; `compile-prompts` exits 0 only when `final_state == PROMPT_PACKAGE_READY`.

## Architecture

### Two layers that are not fully wired together — know which one you're in

This is the one thing that isn't obvious from browsing individual files, and it matters for almost any nontrivial change here.

**Layer 1 — the real, running execution pipeline** (`services/langgraph/graph/agency/`). `build.py` compiles a LangGraph `StateGraph`: `brief_intake → brand_strategy → creative_concepting → copywriting → design_brief → campaign_assembly → brand_safety_qa → hitl_gate → delivery`, compiled with `interrupt_before=["delivery"]` so every run pauses for human approval. Each node calls `llm.py`'s `generate_structured()`, which hits `OPENAI_API_KEY` (`gpt-4o-mini` by default) and returns a `GenerationOutcome` carrying `mode`; no key means `mode="FALLBACK_DEGRADED"`, and degraded output is not an error to catch downstream — it's a durable fact the lifecycle guards check before allowing release. This is what `api/routes/agency.py` actually invokes for a real run, checkpointed via `persistence/checkpoints.py` (SQLite locally, Postgres in production).

**Layer 2 — the governance kernel** (`services/langgraph/agency/kernel/`: `ontology.py` N1, `lifecycle.py` N2, `roles.py` N3, `registry.py` N4). A closed, typed vocabulary: 28 `ArtifactType`s owned by `Department`s (N1; `media_asset` was added for rendered/uploaded media); a transition matrix per entity (`engagement`/`workstream`/`artifact`) with guarded, fail-closed release states (N2); 13 `RoleContract`s declaring `produces`/`consumes`/`min_evidence`/`requires_human_approval`/`external_side_effect` per role (N3); an artifact registry with branch/merge semantics (N4). Every Pydantic model here has a Zod twin in `packages/shared/src/schemas/` and `verify_ontology_parity.py` enforces they agree.

**Layer 1 now enforces the N2/N3 governance seams directly.** `api/routes/agency.py` uses N2 `TransitionContext`/`release_guard_failures` for release gating. `graph/agency/nodes.py` declares `LIVE_STAGE_ROLE_BINDINGS`; every live stage resolves its N3 role with `get_role()`, and every artifact-producing stage calls `assert_role_may_produce()` before emitting its canonical artifact type. Campaign exports are still persisted through the N1/N4-backed artifact binding layer. This does **not** mean the generic skill dispatcher is automatically used for every stage: `agency/skills/dispatcher.py` remains a separate capability-gated execution surface, and role identity never grants external publish/spend authority. The CLI remains useful for isolated kernel planning, but N3 output authorization is no longer planner-only.

### Workspace packages and the backend core — same semantics, no cross-language imports

`packages/{errors,config,logger,constants,db,testing}` (TypeScript, built from root `tsconfig.base.json`, Node16 resolution, CommonJS output except the ESM-only test helper `@amc/testing`) and `services/langgraph/core/{constants,errors,config}.py` are sibling implementations of the same vocabularies, error envelope (`{detail, error: {code, message, status, details?}}`) and config/logging conventions; `tests/test_core.py` reads `packages/constants/src/index.ts` to keep the vocabularies in step. `apps/web/lib/config.ts` must keep reading each `NEXT_PUBLIC_*` variable as a literal `process.env` expression (Next.js only inlines literal references into browser bundles); `@amc/config` loaders take that explicit record and never read `process.env` themselves. `app/config.py` is still the single owner of runtime configuration and the production gates — `core.config` is a typed view that imports it lazily (it imports `core.constants`, so an eager import would cycle). `@amc/db` is a driver-agnostic contract only; the web app has no database access. Details: `docs/workspace-packages.md`.

### Skill dispatcher — capability gating, not a plugin system yet

`agency/skills/dispatcher.py`: a `Skill` is registered once with the N3 `Capability` it requires; `dispatch_skill(role_id, skill_id, payload)` raises before the handler ever runs if the role's contract doesn't hold that capability. Authorization failures raise (`RoleContractError`/`SkillDispatchError`); handler-execution failures come back as a `SkillOutcome(status="FAILED")` rather than propagating, mirroring `GenerationOutcome`'s degraded-mode convention. Currently exactly one skill is registered (`zo_ask`, read-only, via `integrations/zo.py`). There is no AI image/audio *generation* in this codebase — `agency/assets.py`'s `render_logo_svg`/`render_background_pattern_svg`/`render_hero_svg` are fixed, deterministic SVG templates parameterized by brand color tokens. The one renderer is `services/freevideoforge/` (local, zero paid API, needs Pillow + FFmpeg), which the Project OS bridges by file contract rather than import (see below).

### Guidance registry + prompt compiler — stops deliberately short of generation

`agency/guidance/` (models/registry/router) and `agency/prompt_compiler.py` are a second, newer subsystem alongside the kernel, reachable via `orchestrate_brand_pipeline.py compile-prompts`. Two parts:

- **Guidance registry** (`agency/guidance/packs/*.yaml`, e.g. `pg.branding.core`, `pg.studio_identity.v4`): hash-verified (`content_hash` per pack, `registry_hash` over all packs), YAML-as-JSON-1.2 (rejects duplicate keys, no custom tags/aliases — deterministic stdlib parsing). Every pack is `authority_class: ADVISORY` or `EVIDENCE_BOUND_ADVISORY` — guidance can shape how a prompt is compiled, it can never redefine runtime policy, permissions, or canonical `BrandCore` state (`guidance/models.py`'s module docstring is explicit about this). `router.py`'s `route_guidance()` selects packs/sections by a deterministic weighted-overlap score against the request (asset family/type, channel, brand domains, capabilities, task tags) — **no LLM call in routing**, so identical inputs always select identically.
- **Prompt compiler** (`prompt_compiler.py`, ~1300 lines): five explicit audit passes — `intake_claims → hunt_gaps → build_research_backfill → validate_claims → synthesize_report` — before it will compile a prompt package, so retrieval can't silently rewrite source material and every unresolved premise stays visible. Its own module docstring states the boundary plainly: *"intentionally stops at validated prompt packages. It never invokes a media provider, writes a generated asset, publishes content, or performs any other external creative side effect."* `CompilerState`'s terminal success value is `PROMPT_PACKAGE_READY` (`GENERATION_FIREWALL` in the module) — there is deliberately no `ASSETS_GENERATED` state in this enum.

Read together: this is the validated, evidence-grounded input a real image/video generation skill would consume — it is not that skill. Wiring an actual provider behind `PROMPT_PACKAGE_READY` output is still open work, same as the rest of the kernel-to-Layer-1 integration gap above.

### Project OS — PROJECT is the durable unit

`services/langgraph/agency/project_os/` (pure contracts/policies) + `persistence/{projects,project_ops,project_knowledge,project_media,portfolio}.py` + `api/routes/{projects,project_ops,portfolio}.py`. Runs execute inside projects (a run appends `WORK_STARTED`/`APPROVAL_REQUIRED` to `project_events` and is dual-materialized into `<export>/projects/<tenant>/<project>/`); chats are project activity; the filesystem mirror is never authority. It **extends** existing primitives instead of adding parallel ones: artifacts are N4 `agency_artifacts` rows (v2 metadata in `metadata.v2`, history in `artifact_versions`, compare-and-set via `record_artifact_revision(expected_version=)`); content approval reuses `approval_authority.assert_may_decide`; the single scheduler (`scheduled_jobs` + `run_scheduler_tick`) delivers through the trust-kernel outbox and `OutboxDispatcher`; receipts reuse `DispatchPermit`/`ExecutionReceipt`/`ObservationReceipt`; learning reuses `LearningLedger`, persisted per tenant. Vocabulary parity with `packages/shared/src/schemas/projectOs.ts` is part of `verify_ontology_parity.py`; object parity is the generated fixture `packages/shared/tests/fixtures/project-os.json` (regenerate with `AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_project_os_contracts.py`). Publication is dry-run only (live registry ships empty), paid media is planning-only, R2 fails closed. Details: `docs/project-os.md` and its companions.

### Delivery contracts and the release handshake — proof, not authority

`services/langgraph/agency/delivery/` adds what "done" means for a run without adding an authority. `AMC_CONTRACT_MODE` (`off` default / `shadow` / `enforce`) picks the topology a *new* run is pinned to (`metadata.workflow`: `workflow_version`, `contract_mode`, `graph_fingerprint`); GET/resume/contract-view rebuild from that pin, never from the env, and a fingerprint mismatch refuses to resume. `agency/v2-contract` inserts `contract_check` (deterministic `critic.py`, no model) between `brand_safety_qa` and `hitl_gate`; the static `interrupt_before=["delivery"]` is unchanged and both topologies are defined once in `workflow.py`. In shadow/enforce the API seals a `ReleaseCandidateManifest` (exact artifact versions incl. the protected run artifact, contract + re-evaluated result hash, dependency snapshot, `amc-release/v1`) *before* the approval can be decided; enforce binds the approval's `subject_hash` to `canonical_hash({candidate_manifest_hash, contract_hash, policy_version})` and resume runs `evaluate_release_predicate` (N2 ∧ contract dod ∧ approved non-stale ∧ subject match ∧ artifacts match ∧ dependencies match ∧ compile gate), then seals a `ReleaseReceipt` from the final payload before completing. Shadow keeps the legacy approval subject and only records a `release_gate` verdict event. The CRG (`crg.py`) and `BlastRadiusCertificate` (`blast_radius.py`, returned by `record_artifact_revision`) are derived projections with no persistence imports (tested). PATTERN requirements are rejected until a linear-time regex engine is pinned. The v4 MethodRouter/ProblemSignature/MethodPlan layer was never provided and is not implemented. Details: `docs/unified-delivery.md`.

### Method routing and delegation — a compiler, not an orchestrator

`agency/compiled/method_{models,catalog,router,mission}.py` + `data/method_catalog.v1.json` (18 families, 128 methods, provenance `DESCRIPTION_UNVERIFIED`). `compile_method_plan(ObjectiveRequest)` normalizes the request, selects problem families **only from structural facts** (keywords are corroboration and yield ≤3 clarification gates), derives slot-tagged needs (MACRO/DIAGNOSE/DECIDE/EXECUTE/CONTROL/LEARN), picks methods by greedy set cover, prunes counterfactually (every survivor has a `MinimalityCertificate`), runs a ≤2-stack planning-only shadow duel on exact ties, and emits a hash-chained `DelegationEnvelope` DAG (empty authority/approval refs; context hashes chain, so `verify_context_chain`/`causal_closure` invalidate exactly the stale closure). `compile_method_mission` projects it to the canonical mission payload with an explicit `phase_map`, runs the **existing** `MissionWorkOrderAdapter`/`WorkOrderCompiler`/`RoleResolver`, checks hard eligibility gates and a `ProofOfNonAuthority` (delta must be 0), and schedules with the existing `CausalWorkGraph`/`build_cell`/`schedule_waves`. `compile_method_mission` itself still reports `EXECUTOR_GAP` (it is plan-only); the execution fabric below consumes its waves and reports method cells truthfully (they hold no N3 contract and need a drafting provider, so they stay blocked). CLI: `orchestrate_brand_pipeline.py method-plan --input sample_method_request.json`. Details: `docs/method-routing-delegation.md`.

### Execution fabric — the governed execution plane

`services/langgraph/agency/execution_fabric/` consumes the waves both compiled planners emit (`schedule.from_compiled_agency_plan` / `from_method_mission`; the planners are unchanged) and replaces blanket `EXECUTOR_GAP` with truthful per-cell `ExecutionState`s (SUCCEEDED, FAILED, BLOCKED_{AUTHORITY,TOOL,PROVIDER,DEPENDENCY,CONTRACT,POLICY}, NEEDS_HUMAN, PROVIDER_GAP). `consumer.execute_mission` recomputes the wave plan to prove freshness, checks eligibility (server-issued authority only — `ExecutionContext.from_server` rejects client-injected authority and any mode but LOCAL/SANDBOX; N3 role + skill capability; provider/sandbox availability; injection scan of every payload string), splits colliding cells into sub-waves, and runs a two-phase write-ahead per cell: idempotency reservation keyed `hash(tenant, project, mission, work_order, contract_hash, input_hash)` in a tenant scope + a `DispatchPermit` recording the target's pre-image version, then `dispatch_skill` → validators → ProjectOS `create/revise_project_artifact` (OCC, `provenance_ref=execution:<key>`) → `ExecutionReceipt` → storage read-back `ObservationReceipt` → complete. A stale uncommitted reservation is reconciled against the permit pre-image (retry / adopt / halt `RECONCILE_DIVERGENT`). Consequential side effects are never dispatched (NEEDS_HUMAN without approval, `LIVE_GATED` with one), and deliverables stop at the N2 release boundary as NEEDS_HUMAN. Skills are registered in the canonical dispatcher (`Skill` gained `side_effect_class`/`sandbox_requirement`/`provider_requirement`/`validator_ids`/`timeout_class`; `register_skill` refuses redefinition); domain adapters cover deterministic SVG + DTCG, a stdlib-DOM WCAG 2.2 audit, a Python-only code sandbox (temp copy, segment-checked paths, AST diff, `py_compile` allowlist, scrubbed env, rlimits, `unshare -rn`), FreeVideoForge ingest + `ffprobe` verification, and local SEO checks. Text/T2I/AI-video/search-demand have no provider adapter and are `PROVIDER_GAP` — never simulated. Read models in `coverage.py` (coverage graph, autonomy envelopes ≤ canonical, cross-modal ΔE witness). CLI: `orchestrate_brand_pipeline.py fabric-run --input sample_fabric_mission.json` (writes to the configured DB). Details: `docs/execution-fabric.md`.

### Cinematic capability — routed, not global

`services/langgraph/agency/cinematic/` is a lazily-loaded domain capability that compiles ideas/scripts/storyboards/images into T2I/T2V/I2V/storyboard/brand-motion prompts, with canonical `ProjectIR`/`ShotIR`, source-authority resolution, continuity handshakes, camera/lighting/physics reasoning, an evaluator, and a bounded repair loop. It routes via its own deterministic trigger metadata (`cinematic.route_request`) and honours the same firewall — it terminates at prompts and never invokes a media provider. It is a native module (real schemas/compilers/evaluator, not advisory prose) and its full specification is deliberately kept out of this file; see `docs/cinematic-capability.md` and invoke via `orchestrate_brand_pipeline.py cinematic`.

### Creative search runtime — bounded search, human-gated

`services/langgraph/agency/creative/` runs a brief through `MissionIR → ExecutionPlan → context portfolio → candidates → hard gate → blind critics → Pareto front → HUMAN → ≤1 correction + TriDiff → approval → delivery gate`. It is deterministic: there are no model calls, and model-backed types (image, video, social, brand identity) plan `BLOCKED` as `provider_gap`.

- **Capability registry.** `knowledge/creative-capabilities/registry.json` (hash-pinned guides, dispositions) is loaded by `capabilities.py`.
- **Topology.** `organization.py` picks the smallest topology (T0–T4). T4 search runs only when the brief asks for exploration and `max_candidates > 1`. The caps are schema-enforced: population ≤ 4, generations ≤ 2, corrections ≤ 1.
- **Context.** `context.py` reads the design corpus only through `load_validated_corpus`. References contribute abstract principles only; unknown rights are excluded. `derive_requirements` maps the owned accessibility contract into renderer requirements.
- **Critics.** They see a lineage-free `BlindView`. `ConstraintValidator` is non-compensable.
- **HITL.** It reuses `create_approval_request(subject_hash=<ArtifactIR hash>)`: no graph change, no migration. `delivery_gate` fails closed on pending, rejected, stale or hash-mismatched approvals and never performs delivery.
- **Recorder.** `recorder.py` refuses free text and secrets.

CLI: `creative-run`. Details: `docs/creative-runtime.md`.

### Prompt families and v10 prompt OS — decomposed, not injected

`agency/prompt_families/` compiles reusable prompt families through the existing prompt compiler. It freezes an `InvariantSet`, varies declared axes, rejects concepts whose SHA-256 signature repeats the `ConceptLedger` (repairing the highest-level axis first, at most 3 passes), and terminates at `PROMPT_PACKAGE_READY`. `AssetRequirement` gained additive `exact_text` (blocking if not preserved verbatim), typed `references` and `series`. `ComputationEvidence` never upgrades a premise to VERIFIED. Methodology lives in the `pg.copy_content.v1`, `pg.attention.hooks.v1` and `pg.visual_prompting.v1` packs. The supplied spec is provenance only (`docs/imported-specs/`). CLI: `prompt-family`. Details: `docs/brand-content-visual-prompt-os.md`.

### Compiled Agency planner — plans over the kernel, never executes

`services/langgraph/agency/compiled/` compiles `DeliverableSpec`s into a Causal Work Graph (expanded from N3 `produces`/`consumes`), binds each work node to a sealed RoleOS specialist *and* an N3 contract (ceiling = intersection; RoleOS is DENY_CONSEQUENTIAL_BY_DEFAULT), wraps `WorkOrderCompiler` output as proof-carrying work orders, and schedules mission cells into waves; release readiness delegates to N2 `release_guard_failures`. Pure and deterministic (`as_of` is an input). The RoleOS source archive is dispositioned in `agency/compiled/data/source_disposition.json` (1,177 records, hash-sealed); SKILL bodies are not vendored and load JIT only from a verified archive. `/compiled-agency/v1/plan` discards client-supplied approvals/grants/provider status, so external actions always plan blocked. Layer 1 enforces N2/N3 seams directly but does not consume compiled plans; that wiring is open integration work. Details: `docs/compiled-agency.md`.

### Design Mode — style catalog composed by dimension

`packages/shared/style-library/design-styles.json` is the canonical style catalog (contract: `packages/shared/src/schemas/styleLibrary.ts`, mirrored by `services/langgraph/agency/design/style_registry.py`). Styles are composed **by dimension**, never by concatenating prompts: each selection layer claims dimensions (default: the style's own `design_dimensions`), and each dimension resolves to one style — a locked layer wins, then strength, then the primary (`style_composer.py`); `prompt_compiler.py` emits one prompt line per resolved dimension. Declared incompatibility, a disabled style, or two locks on one dimension are *blocking*. Catalog references to styles not yet migrated (`pending_references`) are allowed but must be well-formed ids — never invent those styles. The UI (`DesignStyleComposerPanel`, behind Mission Control's Design Mode toggle) attaches a selection via `lib/stores/designStore.ts`; the Campaign Terminal sends it as `CampaignBrief.style_selection`; `brief_intake` carries it and `design_brief` **recomposes it server-side** into `DesignBrief.style_direction` (applied to generation only when non-blocking), exported as `branding/raw/style-direction.md` and surfaced to the reviewer as a QA advisory. API: `GET /design/styles`, `POST /design/styles/compose` (`api/routes/design.py`, auth-required).

### UI/UX design compiler and DTCG tokens

`services/langgraph/agency/ui_ux/` compiles product/brand/audience state into a strict `UIUXDesignIR` (IA, flows, genome, tiered DTCG tokens, screens, the full 29-state matrix, responsive transforms, WCAG 2.2 requirements, AI-trust rules, implementation map) — pure, deterministic, terminal `UIUX_SPEC_READY`, never generates UI. It runs as a deterministic subprocess of `design_brief` for digital-product briefs (`DesignBrief.ui_ux`; non-UI briefs get `null`) and inside the prompt compiler for `PromptFamily.UI_UX` (`PromptPackage.ui_ux_design`); other families are byte-identical. WCAG 2.2 is normative for every contrast verdict; APCA is advisory only and never merged with it; vendor design systems are reference-only. `agency/design_tokens.py` is the **only** DTCG 2025.10 compiler (frontend `compile_tokens.py`, runtime `_build_design_system`, UI/UX) — don't add a second. Frontend tokens: edit `apps/web/tokens/amc.tokens.json`, run `pnpm tokens:build`; `apps/web/app/tokens.css` is generated and checked for freshness by `verify_design_tokens.py`; `pnpm --filter @amc/web verify:ui` is a TS-AST gate. `UIUXDesignIR` has a strict Zod twin (`packages/shared/src/schemas/uiux.ts`) whose parity is proven by a compiler-generated fixture — if you change the Pydantic models, regenerate `packages/shared/tests/fixtures/uiux-design-ir.json`. Details: `docs/ui-ux-design-compiler.md`.

### The fail-closed integration pattern

`integrations/publication.py`, `integrations/paid_media.py`, `integrations/zo.py` all follow the same shape: a mode env switch (`AMC_PUBLICATION_MODE`, `AMC_PAID_MEDIA_MODE`, `AMC_ZO_MODE`) defaults to `"disabled"`, and anything beyond `disabled`/`dry_run` for publication or beyond `disabled` for paid-media fails `verify_production_readiness.py`. There is no live executor for either — extending one means installing a real provider adapter deliberately, not flipping the switch.

### Config, health, and CORS

`app/config.py` is the single source of runtime configuration — `load_runtime_config()` returns frozen dataclasses (`CorsConfig`, `DatabaseConfig`, `AuthConfig`, `ProviderConfig`, `PublicationConfig`, `PaidMediaConfig`) composed into `RuntimeConfig`, parsed fresh from `os.environ` on every call (cheap, no I/O) so tests that `monkeypatch.setenv` see immediate effects. None of these dataclasses ever hold a raw secret — only presence booleans or already-public identifiers — so the whole struct is safe to return from an endpoint. `production_config_errors()`/`assert_runtime_configuration()` are the stable public entry points other modules and the verifier scripts depend on; CORS origin validation rejects wildcards, non-`http(s)` schemes, embedded credentials, paths/queries/fragments, and (production only) loopback hosts and post-normalization duplicates.

Three endpoints, deliberately separated: `/health` is pure liveness (no config/DB check — a misconfigured instance should still report alive so it isn't killed for something a config change could fix). `/ready` is real: 200 only when config is valid *and* `ping_database()` succeeds, 503 with a secret-free `errors` list otherwise. `/version` reports the app version plus `commit_sha`/`build_timestamp` when the deploy platform injects them (null, not fabricated, otherwise).

### Auth and persistence

`security/auth.py`: `AMC_AUTH_MODE=local` (loopback dev only — never expose to a network) vs `supabase` (production bearer-token verification). Tenant/project authorization is resolved server-side via `amc.tenant_memberships` — client-supplied tenant/reviewer values are never authoritative. `persistence/database.py`: dual-mode SQLite (local/CI, default) / PostgreSQL (production, `AMC_DATABASE_BACKEND=postgres` + `DATABASE_URL`), with `ping_database()` doing a real connectivity check. All external mutation and idempotency machinery (`persistence/idempotency.py`, `agency/reliability/outbox.py`) exists whether or not a real external write is installed, since the reliability substrate and the adapter are separate concerns here.

### Frontend state (Zustand)

`apps/web/lib/stores/` uses Zustand; `.jules/bolt.md` (an automated perf-bot's running log, not a person) documents the house convention worth following: select the smallest primitive or stable reference a component needs rather than a whole object/derived array from the store (`Object.values(state.x)` inside a selector reallocates every render and can loop with React 19's `useSyncExternalStore`); extract list items into their own components subscribing to their own key rather than having a parent re-render on any item's change.

### Governance planning artifacts (not runtime code)

`AGENTS.md`, `constraint_ledger.yaml`, `risk_register.json`, `governance_decisions.json`, `validation_report.json` at the repo root are a **pre-implementation architecture-planning bundle** (own `status: "draft_until_verified"` / `"not_release_ready_without_repo_audit"`), not a description of runtime components. There is no "Orchestrator Agent" or "Execution Agent (Codex)" dispatching a task DAG anywhere in this codebase — don't go looking for it. `constraint_ledger.yaml`'s `agency_pipeline_decisions` section is the one part that reflects real, still-true decisions: `spend_authority: no_spend_mvp` and `analytics_metrics_source: deferred` match Layer 1's actual fail-closed publication/paid-media/analytics state today.

## Notes

- Design token discipline: `brand_core` (Pydantic in `agency/artifacts/brand.py`, Zod in `packages/shared/src/schemas/brand.ts`) is strictly qualitative — voice, color story, typography direction, motion character as prose, not hex/duration values. `design_token_set` is the role contract responsible for compiling `brand_core` into literal tokens; don't add literal color/motion values to `brand_core` itself. `scripts/verify_design_tokens.py` enforces the frontend side of this split: `apps/web/tailwind.config.ts` and CSS custom-property declarations may hold raw color values (they define the palette); components/pages/lib may not (an `amc-allow-hex` pragma comment is the deliberate-exception escape hatch).
- `services/langgraph/agency/kernel/lifecycle.py`'s `TransitionContext` fields are fail-closed by absence — an unstated fact (e.g. `approval_exists` unset) means "unproven," not "assume false is fine to skip." When adding a new guard or a new fact, follow that direction.
- Foreign-agent configs are present but unimported: `.codex/config.toml` (OpenAI Codex) and `GEMINI.md` (Gemini CLI). Don't read or act on them directly — if the user wants them imported, point them at `/import`.
