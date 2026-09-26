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

`manifest.json` (schema `amc-integrity/v2`) pins git-blob SHAs for 78 security/authorization-boundary files (auth, config, persistence, the N1–N4 kernel modules, CI workflow, verifier scripts themselves, etc.). Editing any tracked file drifts its hash and fails `verify_manifest.py`. Regenerate deliberately, never by copying a printed hash by hand:

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
```
`plan` **plans against the governance kernel only** — it resolves artifacts to roles, checks evidence floors, and walks the lifecycle guards. `compile-prompts` runs the claims-audit prompt compiler (see Architecture). Neither calls an LLM, and neither touches the real execution pipeline. `plan` exits 0 = clear, 1 = blocked (kernel guard failed), 2 = brief couldn't be interpreted; `compile-prompts` exits 0 only when `final_state == PROMPT_PACKAGE_READY`.

## Architecture

### Two layers that are not fully wired together — know which one you're in

This is the one thing that isn't obvious from browsing individual files, and it matters for almost any nontrivial change here.

**Layer 1 — the real, running execution pipeline** (`services/langgraph/graph/agency/`). `build.py` compiles a LangGraph `StateGraph`: `brief_intake → brand_strategy → creative_concepting → copywriting → design_brief → campaign_assembly → brand_safety_qa → hitl_gate → delivery`, compiled with `interrupt_before=["delivery"]` so every run pauses for human approval. Each node calls `llm.py`'s `generate_structured()`, which hits `OPENAI_API_KEY` (`gpt-4o-mini` by default) and returns a `GenerationOutcome` carrying `mode`; no key means `mode="FALLBACK_DEGRADED"`, and degraded output is not an error to catch downstream — it's a durable fact the lifecycle guards check before allowing release. This is what `api/routes/agency.py` actually invokes for a real run, checkpointed via `persistence/checkpoints.py` (SQLite locally, Postgres in production).

**Layer 2 — the governance kernel** (`services/langgraph/agency/kernel/`: `ontology.py` N1, `lifecycle.py` N2, `roles.py` N3, `registry.py` N4). A closed, typed vocabulary: 27 `ArtifactType`s owned by `Department`s (N1); a transition matrix per entity (`engagement`/`workstream`/`artifact`) with guarded, fail-closed release states (N2); 13 `RoleContract`s declaring `produces`/`consumes`/`min_evidence`/`requires_human_approval`/`external_side_effect` per role (N3); an artifact registry with branch/merge semantics (N4). Every Pydantic model here has a Zod twin in `packages/shared/src/schemas/` and `verify_ontology_parity.py` enforces they agree.

**The connection between them is thin, and it's important not to assume otherwise.** `api/routes/agency.py` imports exactly `TransitionContext`/`release_guard_failures` from N2 for the release gate, and references `brand_core` as an artifact key in workspace-export bindings. Nothing in Layer 1's nodes calls `assert_role_may_produce`, dispatches through the capability-gated skill runtime (`agency/skills/dispatcher.py`), or resolves via `ROLE_REGISTRY`. The `agency/cli.py` planner (see Commands) drives Layer 2 in isolation — it can tell you what the kernel *would* permit for a hypothetical brief, but it cannot kick off or affect a real run. If you're asked to add kernel enforcement to the real pipeline, that's a deliberate integration task, not something already half-done that you're finishing.

### Skill dispatcher — capability gating, not a plugin system yet

`agency/skills/dispatcher.py`: a `Skill` is registered once with the N3 `Capability` it requires; `dispatch_skill(role_id, skill_id, payload)` raises before the handler ever runs if the role's contract doesn't hold that capability. Authorization failures raise (`RoleContractError`/`SkillDispatchError`); handler-execution failures come back as a `SkillOutcome(status="FAILED")` rather than propagating, mirroring `GenerationOutcome`'s degraded-mode convention. Currently exactly one skill is registered (`zo_ask`, read-only, via `integrations/zo.py`). There is still no image/video/audio *generation* anywhere in this codebase — `agency/assets.py`'s `render_logo_svg`/`render_background_pattern_svg`/`render_hero_svg` are fixed, deterministic SVG templates parameterized by brand color tokens, not AI-generated art — but see the prompt compiler below for the piece that would feed a real generation skill.

### Guidance registry + prompt compiler — stops deliberately short of generation

`agency/guidance/` (models/registry/router) and `agency/prompt_compiler.py` are a second, newer subsystem alongside the kernel, reachable via `orchestrate_brand_pipeline.py compile-prompts`. Two parts:

- **Guidance registry** (`agency/guidance/packs/*.yaml`, e.g. `pg.branding.core`, `pg.studio_identity.v4`): hash-verified (`content_hash` per pack, `registry_hash` over all packs), YAML-as-JSON-1.2 (rejects duplicate keys, no custom tags/aliases — deterministic stdlib parsing). Every pack is `authority_class: ADVISORY` or `EVIDENCE_BOUND_ADVISORY` — guidance can shape how a prompt is compiled, it can never redefine runtime policy, permissions, or canonical `BrandCore` state (`guidance/models.py`'s module docstring is explicit about this). `router.py`'s `route_guidance()` selects packs/sections by a deterministic weighted-overlap score against the request (asset family/type, channel, brand domains, capabilities, task tags) — **no LLM call in routing**, so identical inputs always select identically.
- **Prompt compiler** (`prompt_compiler.py`, ~1300 lines): five explicit audit passes — `intake_claims → hunt_gaps → build_research_backfill → validate_claims → synthesize_report` — before it will compile a prompt package, so retrieval can't silently rewrite source material and every unresolved premise stays visible. Its own module docstring states the boundary plainly: *"intentionally stops at validated prompt packages. It never invokes a media provider, writes a generated asset, publishes content, or performs any other external creative side effect."* `CompilerState`'s terminal success value is `PROMPT_PACKAGE_READY` (`GENERATION_FIREWALL` in the module) — there is deliberately no `ASSETS_GENERATED` state in this enum.

Read together: this is the validated, evidence-grounded input a real image/video generation skill would consume — it is not that skill. Wiring an actual provider behind `PROMPT_PACKAGE_READY` output is still open work, same as the rest of the kernel-to-Layer-1 integration gap above.

### Cinematic capability — routed, not global

`services/langgraph/agency/cinematic/` is a lazily-loaded domain capability that compiles ideas/scripts/storyboards/images into T2I/T2V/I2V/storyboard/brand-motion prompts, with canonical `ProjectIR`/`ShotIR`, source-authority resolution, continuity handshakes, camera/lighting/physics reasoning, an evaluator, and a bounded repair loop. It routes via its own deterministic trigger metadata (`cinematic.route_request`) and honours the same firewall — it terminates at prompts and never invokes a media provider. It is a native module (real schemas/compilers/evaluator, not advisory prose) and its full specification is deliberately kept out of this file; see `docs/cinematic-capability.md` and invoke via `orchestrate_brand_pipeline.py cinematic`.

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
