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

Copy `.env.example`; minimum local config uses `AMC_ENV=local`, `AMC_AUTH_MODE=local`, `AMC_DATABASE_BACKEND=sqlite`. Without a usable credential for the selected provider (`OPENAI_API_KEY` by default), agency generation is explicitly `FALLBACK_DEGRADED` and delivery is blocked — that's intended behavior, not a bug, when testing without a key.

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

- **Postgres CI.** CI runs the whole backend suite on SQLite *and* on PostgreSQL, so a test that passes locally can still fail there (see the row-access rule under Coding standards).
- **Excluding a file.** To leave out one file locally (e.g. `test_ucpo_build.py` when its pinned Chromium is absent), use `--ignore=<path>`; `--deselect` takes test ids and does not exclude a file.
- **E2E local principal.** For e2e, start the backend with the local-principal env from the "Start local stack" step in `.github/workflows/ci.yml` (`AMC_LOCAL_USER_ID`, `AMC_LOCAL_TENANT_ID`, `AMC_LOCAL_PROJECT_IDS`, `AMC_LOCAL_ROLE`). Without it, `POST /projects` returns 503 and the specs fail in `beforeAll`.
- **Stopping servers.** Kill local servers by explicit PID from `ps -eo pid=,args=` filtered on the exact argv. Never use `pkill -f` or a grep pattern that also appears in your own command line; it kills the shell running it.

### Lint / typecheck / build

```bash
ruff check --select E4,E7,E9,F <paths>    # no ruff config; recent ruff defaults are much broader and existing code doesn't pass them (CI doesn't run ruff)
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

`manifest.json` (schema `amc-integrity/v2`) pins git-blob SHAs for the security/authorization-boundary files (count them in `manifest.json`; 288 as of the VNEXUS creative-directions change) (auth, config, persistence, the N1–N4 kernel modules, CI workflow, verifier scripts themselves, etc.). Editing any tracked file drifts its hash and fails `verify_manifest.py`. Regenerate deliberately, never by copying a printed hash by hand:

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

Subcommands (`plan`, `roles`, `validate`, `compile-prompts`, `ui-ux`, `creative-run`, and the per-subsystem ones in `docs/agency-cli.md`) are listed by `python3 orchestrate_brand_pipeline.py --help`; the Makefile wraps them (`make brand-plan`, `make prompt-compile`, …).
`plan` **plans against the governance kernel only** — it resolves artifacts to roles, checks evidence floors, and walks the lifecycle guards. `compile-prompts` runs the claims-audit prompt compiler (see Architecture). Neither calls an LLM, and neither touches the real execution pipeline. `plan` exits 0 = clear, 1 = blocked (kernel guard failed), 2 = brief couldn't be interpreted; `compile-prompts` exits 0 only when `final_state == PROMPT_PACKAGE_READY`.

## Architecture

### Two layers that are not fully wired together — know which one you're in

This is the one thing that isn't obvious from browsing individual files, and it matters for almost any nontrivial change here.

**Layer 1 — the real, running execution pipeline** (`services/langgraph/graph/agency/`). `build.py` compiles a LangGraph `StateGraph`: `brief_intake → brand_strategy → creative_concepting → copywriting → design_brief → campaign_assembly → brand_safety_qa → hitl_gate → delivery`, compiled with `interrupt_before=["delivery"]` so every run pauses for human approval. Each node calls `llm.py`'s `generate_structured()`, which goes through the canonical `agency/model_router.py` using the run's pinned model profile (`agency/model_profiles.py`, `metadata.model_profile`; OpenAI `gpt-4o-mini` by default, or Anthropic, Gemini or Ollama via `AMC_LLM_PROVIDER`; see `docs/amc-i03-model-profiles.md`) and returns a `GenerationOutcome` carrying `mode`; no usable credential or an invalid selection means `mode="FALLBACK_DEGRADED"`, and degraded output is not an error to catch downstream — it's a durable fact the lifecycle guards check before allowing release. This is what `api/routes/agency.py` actually invokes for a real run, checkpointed via `persistence/checkpoints.py` (SQLite locally, Postgres in production).

**Layer 2 — the governance kernel** (`services/langgraph/agency/kernel/`: `ontology.py` N1, `lifecycle.py` N2, `roles.py` N3, `registry.py` N4). A closed, typed vocabulary: 28 `ArtifactType`s owned by `Department`s (N1; `media_asset` was added for rendered/uploaded media); a transition matrix per entity (`engagement`/`workstream`/`artifact`) with guarded, fail-closed release states (N2); 13 `RoleContract`s declaring `produces`/`consumes`/`min_evidence`/`requires_human_approval`/`external_side_effect` per role (N3); an artifact registry with branch/merge semantics (N4). Every Pydantic model here has a Zod twin in `packages/shared/src/schemas/` and `verify_ontology_parity.py` enforces they agree.

**Layer 1 now enforces the N2/N3 governance seams directly.** `api/routes/agency.py` uses N2 `TransitionContext`/`release_guard_failures` for release gating. `graph/agency/nodes.py` declares `LIVE_STAGE_ROLE_BINDINGS`; every live stage resolves its N3 role with `get_role()`, and every artifact-producing stage calls `assert_role_may_produce()` before emitting its canonical artifact type. Campaign exports are still persisted through the N1/N4-backed artifact binding layer. This does **not** mean the generic skill dispatcher is automatically used for every stage: `agency/skills/dispatcher.py` remains a separate capability-gated execution surface, and role identity never grants external publish/spend authority. The CLI remains useful for isolated kernel planning, but N3 output authorization is no longer planner-only.

### Workspace packages and the backend core — same semantics, no cross-language imports

`packages/{errors,config,logger,constants,db,testing}` (TypeScript, built from root `tsconfig.base.json`, Node16 resolution, CommonJS output except the ESM-only test helper `@amc/testing`) and `services/langgraph/core/{constants,errors,config}.py` are sibling implementations of the same vocabularies, error envelope (`{detail, error: {code, message, status, details?}}`) and config/logging conventions; `tests/test_core.py` reads `packages/constants/src/index.ts` to keep the vocabularies in step. `apps/web/lib/config.ts` must keep reading each `NEXT_PUBLIC_*` variable as a literal `process.env` expression (Next.js only inlines literal references into browser bundles); `@amc/config` loaders take that explicit record and never read `process.env` themselves. `app/config.py` is still the single owner of runtime configuration and the production gates — `core.config` is a typed view that imports it lazily (it imports `core.constants`, so an eager import would cycle). `@amc/db` is a driver-agnostic contract only; the web app has no database access. Details: `docs/workspace-packages.md`.

### Web pages and motion — design skill first

The project skill `.claude/skills/premium-web-design/SKILL.md` is the workflow for building, restyling or animating web pages (landing pages, heroes, navbars, pricing, 21st.dev blocks).

- **Tokens.** The type scale (major third, `text-caption`…`text-display-lg`) and 8px-grid section spacing (`py-block`/`py-section`/`py-section-lg`) are DTCG tokens in `apps/web/tokens/amc.tokens.json`, mapped in `tailwind.config.ts`.
- **Motion.** Animations use Framer Motion through `apps/web/components/motion/Motion.tsx` (`Reveal`, `Stagger`/`StaggerItem`, `HoverLift`): `LazyMotion` + `domAnimation`, `reducedMotion="user"`, and never on above-the-fold/LCP content. Its numbers mirror the motion tokens in `lib/design/motion.ts`; `tests/motion-tokens.test.ts` fails on drift.
- **Agency side.** The same methodology is the advisory guidance pack `pg.web_experience.v1`. It routes only for `UI_UX` web requests and is excluded for image/video/print families.
- **Performance.** A Lighthouse 90+ claim needs a measured mobile run on a production build: `npx -y lighthouse@13.5.0` with `CHROME_PATH` set to the Playwright Chromium.

### Subsystem guidance (loads on demand)

Per-subsystem rules live in a `CLAUDE.md` inside each directory and load only when a session works under it. Read the nested file before changing that subsystem; the `docs/` pages have the long form.

- `services/langgraph/agency/skills/` — Skill dispatcher — capability gating, not a plugin system yet
- `services/langgraph/agency/guidance/` — Guidance registry + prompt compiler — stops deliberately short of generation
- `services/langgraph/agency/project_os/` — Project OS — PROJECT is the durable unit
- `services/langgraph/agency/delivery/` — Delivery contracts and the release handshake — proof, not authority
- `services/langgraph/agency/compiled/` — Method routing and delegation — a compiler, not an orchestrator
- `services/langgraph/agency/execution_fabric/` — Execution fabric — the governed execution plane
- `services/langgraph/agency/cinematic/` — Cinematic capability — routed, not global
- `services/langgraph/agency/creative/` — Creative search runtime — bounded search, human-gated
- `services/langgraph/agency/intake/` — Governed intake mission — words to a release decision
- `services/langgraph/agency/visual/` — Local visual engine (R1–R5 renderers, verification)
- `services/langgraph/agency/durable/` — Durable runtime (run FSM, ticks, ABC manifests)
- `services/langgraph/agency/foundry/` — Generative Creative Foundry — brief to verified brand family, locally
- `services/langgraph/agency/ucpo/` — Website production line (UCPO) — brief to verified site, never deployed
- `services/langgraph/agency/avic/` — ACE × AVIC — brief to verified native SVG
- `services/langgraph/agency/vnexus/` — VNEXUS ACE — persisted brand genome and the layers on it
- `services/langgraph/agency/vnexus/brandbook/` — VNEXUS brand book — a projection of the approved genome, built incrementally
- `services/langgraph/agency/vnexus/directions/` — VNEXUS creative directions — recommend, select by approval, rebuild only when needed
- `services/langgraph/agency/actions/` — ACE v12 action plane and Agency OS — one gateway, sandbox only
- `services/langgraph/agency/council/` — Mission Council — three engines, one gate
- `services/langgraph/agency/operating_framework/` — Agency Operating Framework — a ledger over existing owners
- `services/langgraph/agency/prompt_families/` — Prompt families and v10 prompt OS — decomposed, not injected
- `services/langgraph/agency/compiled/` — Compiled Agency planner — plans over the kernel, never executes
- `services/langgraph/agency/design/` — Design Mode — style catalog composed by dimension
- `services/langgraph/agency/ui_ux/` — UI/UX design compiler and DTCG tokens

### Cross-cutting rules (always apply)

These hold across every subsystem; the nested files add detail but never relax them.

- **One approval path.** Release and content approvals are `open_artifact_approval` (or the existing `approvals` rows) decided only on `/approvals/{id}/decide`. Don't add another approval store or decision route.
- **One artifact store.** Derived artifacts are Project OS artifacts written through `foundry.studio.store` (N4 `agency_artifacts`) with `depends_on`. Don't add a parallel store, table or migration for them.
- **Fail closed on external effects.** Publish, spend and send are never dispatched; LIVE enablement stays disabled. Hosted generation, critique and research providers are declared DISABLED until a verified adapter, credentials and an entitlement/pricing/terms recheck exist. Never simulate provider output; `NOT_RUN`, `NOT_VERIFIED`, `BLOCKED` and `PROVIDER_GAP` are never a pass.
- **Don't invent missing sources.** Reserved ids (EXT-001…090 / ART-001…012) are `VOID_DETECTED`; the 14 original VNEXUS prompts and any unsupplied board/spec definitions are absent; unmigrated style references stay pending.
- **Contracts and sweeps.** An API-visible Pydantic model needs a Zod twin and a recorded fixture (regenerate with `AMC_REGENERATE_FIXTURES=1` and the matching `pytest` file named in the subsystem's nested guidance). New `/vnexus` and `/avic` routes are covered by their route-security sweeps automatically and must pass.
- **Proof, not authority.** Hashes, verifier gates and read-backs prove identity and integrity; they never grant approval or release.

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

## Coding standards

These apply to new and changed code. Existing code predates some of them; don't mass-refactor it unprompted.

- **Function length.** Aim for at most 20 lines per function. When a function must be longer (a pipeline stage, a route that maps many fields), split out named helpers before going past it. About a fifth of the existing Python functions are longer.
- **Error handling.** Handle errors explicitly, with `try`/`catch` in TypeScript and `try`/`except` in Python, at the layer that can act on them.
  - Never swallow an exception silently.
  - Catch specific types, or contain a provider fault and record it (`# noqa: BLE001` with a reason, as the media fabric does).
  - For FastAPI routes, the explicit handler is the error-mapping decorator (`vnexus_errors`, `domain_errors`). Don't wrap every handler body in its own try.
- **TypeScript.** Use `const`/`let` only; there are no `var`s, keep it that way. Type everything explicitly, with no `any`: use `unknown` plus a Zod parse or a narrow type instead. The remaining `any`s come from the untyped listener signature in `apps/web/lib/events/bus.ts`. Don't add more; type the bus instead.
- **Database rows.** Read columns by name (`SELECT COUNT(*) AS n …` then `row["n"]`), never by position. `row[0]` works on SQLite rows but raises `KeyError: 0` on the PostgreSQL driver.
- **Python version.** CI runs 3.11 and `requires-python` is `>=3.10`. Don't reuse the enclosing quote character inside an f-string expression (`f"{d["k"]}"`); that is 3.12+ syntax and a SyntaxError here.
- **Pydantic field names.** Don't name a field after a `BaseModel` attribute (`copy`, `json`, `dict`, `schema`, `model_*`): it shadows the method. Use a specific name such as `copy_blocks`.
- **Project OS artifact keys.** `foundry.studio.store` keys become `foundry-<name>`, slugified and truncated to 64 characters, so two long names can silently collide. Use short digest-based names and refuse any name whose `foundry-` key would exceed 64 characters (as `brandbook/service.py` and `vnexus/directions/service.py` do).
- **Tailwind.** Don't use the `inline-block` class. The `block` spacing token makes Tailwind emit `.inline-block { inline-size: var(--amc-semantic-space-block) }`, which squeezes the element narrower than its content. Use `inline-flex` (or `inline-grid`). Check generated CSS for the same collision before using other `inline-<token>` or `block-<token>` utilities.
- **Build byproducts.** `next build` and Playwright write `apps/web/next-env.d.ts` changes, `apps/web/AGENTS.md` and `apps/web/test-results/`, and none of them is gitignored. Restore or delete them before `git add -A`.

## Notes

- Design token discipline: `brand_core` (Pydantic in `agency/artifacts/brand.py`, Zod in `packages/shared/src/schemas/brand.ts`) is strictly qualitative — voice, color story, typography direction, motion character as prose, not hex/duration values. `design_token_set` is the role contract responsible for compiling `brand_core` into literal tokens; don't add literal color/motion values to `brand_core` itself. `scripts/verify_design_tokens.py` enforces the frontend side of this split: `apps/web/tailwind.config.ts` and CSS custom-property declarations may hold raw color values (they define the palette); components/pages/lib may not (an `amc-allow-hex` pragma comment is the deliberate-exception escape hatch).
- `services/langgraph/agency/kernel/lifecycle.py`'s `TransitionContext` fields are fail-closed by absence — an unstated fact (e.g. `approval_exists` unset) means "unproven," not "assume false is fine to skip." When adding a new guard or a new fact, follow that direction.
- Foreign-agent configs are present but unimported: `.codex/config.toml` (OpenAI Codex) and `GEMINI.md` (Gemini CLI). Don't read or act on them directly — if the user wants them imported, point them at `/import`.
