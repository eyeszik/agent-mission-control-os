# VNEXUS ACE — persistent brand genome and creative intelligence

`services/langgraph/agency/vnexus/` + `persistence/vnexus.py` + `api/routes/vnexus.py` (prefix `/vnexus`) +
the **VNEXUS Studio** mode in Mission Control. It turns the v9 foundation (`docs/vnexus-ace-v9-integration.md`,
the pure TypeScript resolver in `apps/web/lib/design/brand-genome.ts`) into a persisted, governed system.

It extends existing owners and does not replace them:

| Concern | Decision | Where |
|---|---|---|
| Hashing | **Reuse** AMC-CANON-1 `canonical_hash` for every content, resolution, change-set, audit and node hash | `agency/execution/canonical.py` |
| Approval | **Reuse** `open_artifact_approval` and `/approvals/{id}/decide` (approver role, separation of duties); VNEXUS only *settles* a decision that route made | `service.settle_version`, `fabric_service.authorize` |
| Artifact storage, versions, read-back | **Reuse** Project OS through the foundry `studio.store` / `observe` | `production.py` |
| Tokens | **Reuse** the one DTCG compiler (foundry `compile_tokens` → `design_tokens`) | `production.produce_experience` |
| Composition, experience twin, motion | **Reuse** the foundry (`compose`, `experience`, `motion`), driven by a genome projection | `bridge.py` |
| UI/UX spec | **Reuse** `compile_uiux` with a genome-derived `BrandContext` | `experience.py` |
| Rendering and verification | **Reuse** `agency.visual` (Chromium raster/frames/experience, new PDF mode, FFmpeg encode, `verify_media`) and fabric verifiers (`svg_safety`, palette conformance, ΔE76) | `media_fabric.py`, `identity.py`, `immune.py` |
| Prompt compilation | **Reuse** the five-pass compiler unchanged; terminal state stays `PROMPT_PACKAGE_READY` | `prompt_genome.py` |
| New persistence | **Create** migration 15 (eleven `amc.vnexus_*` tables) — no existing table fits versioned genome layers, a bitemporal graph or provider jobs | `sqlite_db._MIGRATIONS`, `supabase/migrations/20261011_amc_vnexus_v1.sql` |
| A second orchestrator, a second token compiler, a second approval store | **Reject** | — |

Nothing here publishes, spends, sends or calls a hosted model. Every hosted provider is registered **DISABLED**.

## M2 Brand Genome

`genome.py` (pure) + `service.py` + `persistence/vnexus.py`.

- **Model.** `Brand` → `GenomeVersion` (one per scope and revision) holding a `GenomeDocument`: five chromosomes
  (`strategy`, `visual`, `verbal`, `experience`, `production`) of dotted keys, typed `GenomeConstraint`s
  (`IMMUTABLE`, `REQUIRED`, `ALLOWED_VALUES`, `RANGE`, `HEX_COLOR`, `MIN_CONTRAST`; severity
  INFO/WARNING/ERROR/BLOCKING) and `GenomeProvenance`. `content_hash` covers the whole document and is re-checked on
  every read (`GenomeIntegrityError`).
- **Scopes.** `brand → project → page → component → asset`; a `scope_ref` has exactly one more segment per level.
  `resolve(layers)` walks the approved ancestors, applies values, refuses descendant overrides of `IMMUTABLE` keys
  (reported as `GenomeConflict`, never applied) and evaluates every constraint. A resolution carries
  `resolution_hash` and `trace` (which layer set each key).
- **Lifecycle.** `DRAFT → IN_REVIEW → APPROVED | REJECTED | WITHDRAWN`, `APPROVED → SUPERSEDED`. Only `DRAFT` is
  editable (compare-and-set on `revision`). An APPROVED version is immutable; a partial unique index permits one
  APPROVED version per scope. Submit refuses (`409 VNEXUS_BLOCKED`) when the would-be resolution has BLOCKING
  findings; the report lists them.
- **Approval binding.** Submit opens an approval whose subject hash is `canonical_hash({content_hash,
  ancestor approved hashes})`. Settlement applies the decision only when the subject hash and ref match, the
  reviewer is neither the author nor the submitter, and the ancestors are unchanged; otherwise nothing changes.
- **Revert** creates a new DRAFT from an older version's document; history is never rewritten.
- **Audit.** Every mutation appends to a per-brand hash chain (`vnexus_audit_log`); `GET /brands/{id}/audit`
  returns the entries and `verify_audit_chain`'s verdict.

## M3 Temporal knowledge graph

`graph.py` (pure) + `creative_service.py`. Sixteen node kinds (Brand, GenomeVersion, Asset, Experience, Campaign,
Audience, Channel, ProviderJob, Prompt, Evidence, …) and ten edge kinds with an allow-list of (source kind, target
kind) pairs. Nodes and edges are bitemporal (`valid_from`/`valid_to`); superseding closes the old node and keeps it
queryable. `DERIVED_FROM` / `DEPENDS_ON` / `SUPERSEDES` must stay acyclic (checked inside a locked transaction).

- `impact(node)` returns every downstream node with the path that reaches it.
- `evidence_for(node)` follows `SUPPORTED_BY`.
- `snapshot(at)` / `diff_snapshots` give time travel.

Approving a genome version records a GenomeVersion node that supersedes its predecessor, so outputs derived from the
old one show as stale.

## M4 Creative multiverse

`multiverse.py` (pure) + `creative_service.py`. A branch forks from an **APPROVED** version (or another branch) and
holds a `ChangeSet` (`set`, `unset`, `add_constraints`, `remove_constraints`). `compare_with_base` separates
added / removed / modified / unchanged-inherited keys and reports invariant violations (`IMMUTABLE_OVERRIDE`,
`INVARIANT_CHANGED`, `INVARIANT_REMOVED`); a branch with any is not promotable.

- Evaluations are labelled `DETERMINISTIC` (computed) or `HUMAN` (verbatim feedback: prefer / reject / revise).
- `merge` combines two branches' change sets and refuses (`409 VNEXUS_MERGE_CONFLICT`) on any conflicting key.
- `rebase` moves a branch onto the current approved base.
- Nothing merges into the genome autonomously: `submit` creates a `BRANCH_PROMOTION` draft and sends it through the
  same approval path as any other version, and it requires a current base and a promotable branch.

## M5–M8 Production from an approved genome

`production.approved_projection` refuses (`no approved genome`) unless the scope has approved layers and no blocking
findings. Every output is a Project OS artifact, read back and verified, linked in the graph with `DERIVED_FROM` the
GenomeVersion and `GENERATED_BY` the ProviderJob.

- **Experience compiler** (`experience.py`). It produces nine hashed stages: genome context, objectives, audience
  intent, content architecture, token bindings, component tree, interaction states, responsive spec, accessibility
  tests. `MARKETING_SITE`, `LANDING_PAGE`, `BRAND_MICROSITE` and `CAMPAIGN_EXPERIENCE` render working HTML and run
  the foundry's twelve Chromium scenarios. `SAAS_DASHBOARD` and `WEB_APPLICATION` are `SPEC_ONLY`, and verification is `NOT_RUN` without a
  browser.
- **Art director** (`art_director.py`). It compiles a brief with every statement classed `VERIFIED` (from the
  genome), `INFERRED`, `EXPERIMENTAL` or `UNSUPPORTED`. References with unknown rights are excluded. The rubric
  splits `MEASURED` criteria from `HUMAN_REQUIRED` ones, and scores are explicitly "not an objective quality
  measure".
- **Identity** (`identity.py`). It produces eleven deliverables: logo mark, logo lockup, monogram, icon family,
  colour system, typography specimen, poster, social graphics, presentation title slide, editorial layout and brand
  guidelines, as SVG with PNG, WEBP and PDF renditions. Encoders are used only where present (Chromium for PNG and
  PDF, Pillow for WEBP). Deterministic validators cover contrast, safe area, crop behaviour,
  stroke consistency, palette conformance (ΔE76), raster metrics, transparency, optical centre and minimum
  reproduction size.
- **Video** (`video.py`). Path A is procedural: a script of copy and placeholders only, a shot list, SVG frames,
  then Chromium, then FFmpeg, with WebVTT captions and a reduced-motion still. Audio is muxed only with a recorded
  licence and a same-project artifact. Path B shots (AI video) are planned against the disabled hosted providers and
  stay `BLOCKED`.

## Provider-neutral media fabric

`media_fabric.py` + `fabric_service.py`. Every `MediaProvider` implements `identify`, `capabilities`, `estimate`,
`validate`, `submit`, `status` and `retrieve`.

**Providers**

| Provider | Kind | State |
|---|---|---|
| `local.svg`, `local.chromium_raster`, `local.pillow_webp`, `local.chromium_pdf`, `local.svg_motion` | Local | Enabled when the dependency is present |
| `hosted.text_to_image`, `hosted.text_to_video`, `hosted.image_to_video` | Hosted | `DISABLED` with `ADAPTER_NOT_IMPLEMENTED`, `NO_CREDENTIALS`, `PAID_CALLS_NOT_AUTHORIZED`; there is no network code |
| `mock.simulated` | Mock | Only with `AMC_VNEXUS_MOCK_PROVIDERS=1` outside production; its outputs are `simulated` and can never be claimed as generated |

**Job lifecycle.** `PLANNED → VALIDATED → AUTHORIZED → QUEUED → RUNNING → ARTIFACT_RECEIVED → QC_PASSED`, plus
`FAILED` and `CANCELED`. Every transition is compare-and-set on version and state and is recorded.

**Rules**

- Zero-cost jobs are authorized by the requester. A job with a cost opens a spend approval, decided under
  separation of duties.
- Budget is checked at validation (`BUDGET_EXCEEDED`).
- Creation is idempotent per tenant and `Idempotency-Key`.
- Each provider has a rate limit (`429`).
- Transient failures are retried, bounded. Permanent ones fail the job alone.
- Received bytes must match the provider's hash, are stored, read back and quality-checked.
- `can_claim_generated` is true only for a `QC_PASSED`, non-simulated job with a 64-hex content hash. A prompt or
  job specification is never reported as a generated asset.

## M9–M11 Intelligence

- **Marketing** (`marketing.py`, `intelligence_service.plan_campaign`). Segments are `RESEARCHED` only with sources.
  A hypothesis baseline needs a source. Messages without proof are `NEEDS_PROOF`. The calendar is `PLANNED` with
  publishing `DISABLED`. `forecast` is labelled `SIMULATED` and stored nowhere as fact. `report` computes rates only
  from `MEASURED` rows recorded with a source; with none it says so instead of inventing numbers.
- **Prompt genome** (`prompt_genome.py`). Prompt documents are versioned per brand. `compile_genome_prompt` builds a
  `BrandCore` from the approved genome and runs the unchanged five-pass compiler. It reports `GENOME_INCOMPLETE`
  (lists the missing keys), `GENOME_REJECTED_BY_COMPILER` or `PROMPT_PACKAGE_READY`; nothing is defaulted.
  - The 14 original prompts are **not in the repository** and are not invented. `import` accepts only original
    source text, byte-preserved with a SHA-256, and the inventory reports `SOURCE_REQUIRED` until all 14 exist.
  - `adapt` and `regression` make no provider call. Similarity is labelled lexical.
- **Design immune system** (`immune.py`, `intelligence_service.scan/remediate`). Findings are typed
  INFO/WARNING/ERROR/BLOCKING with deterministic ids, for example `OFF_PALETTE_COLOUR`, `UNAPPROVED_TYPEFACE`,
  `TEXT_CONTRAST`, `ASSET_DIMENSIONS`, `MISSING_PROVENANCE`, `STALE_GENOME_SOURCE`, `BROKEN_REFERENCE`,
  `ARTIFACT_CHANGED` and `ACCESSIBILITY_REGRESSION`. Only deterministic, reversible fixes are automatic:
  - snapping an off-palette colour within ΔE ≤ 6, written as a **new** artifact revision;
  - linking provenance.

  Every remediation is audited. Nothing touches an approved genome.
- **Creative digital twin** (`twin.py`). `simulate_change` projects a change set onto a scope and reports the
  affected scopes, the outputs that would go stale, the projected drift and `WOULD_BLOCK` / `WOULD_BE_PROMOTABLE`.
  `simulate_provider_outage` reports which jobs and deliverables lose their route. Every result is labelled
  `SIMULATION` and nothing is written.

## M12 VNEXUS Studio

Mission Control → **VNEXUS Studio** has fourteen areas in a keyboard-navigable tablist: Overview, Brand Genome
(layers, inheritance and resolution), Versions, Knowledge Graph, Multiverse, Experience, Art Direction, Graphic
Design, Video & Motion, Marketing, Prompt Genome, Provider Jobs, Immune System, Governance. Requests go through `apps/web/lib/api/vnexus.ts`, are
parsed by strict Zod twins (`packages/shared/src/schemas/vnexus.ts`) and are stored in `lib/stores/vnexusStore.ts`.
Contract parity uses the backend-recorded fixture `packages/shared/tests/fixtures/vnexus.json`; regenerate it with
`AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_vnexus_contracts.py`. Governance applies only
decisions made at `/approvals/{id}/decide`.

## M13 Security

- Every route requires a principal, and the project is authorized server-side on every call.
- Viewer, read-only, guest and auditor roles cannot write.
- Another tenant gets `404` and learns nothing; listings are tenant-scoped.
- Request models forbid extra fields, so a client-supplied `tenant_id`, `approved_by`, `authorized_by` or `force`
  is a `422`.
- `test_vnexus_security.py` reads the route table from the application and sweeps **every** VNEXUS route as
  another tenant, as a viewer and unauthenticated under `AMC_AUTH_MODE=supabase`, so a route added later is covered
  automatically.

## Tests

```bash
python -m pytest services/langgraph/tests -q -k vnexus         # genome, graph/multiverse, production, intelligence, contracts, security
pnpm --filter @amc/shared test                                 # Zod twins against the recorded fixture
pnpm --filter @amc/web test                                    # editor helpers + v9 resolver parity
E2E_BASE_URL=http://127.0.0.1:3000 pnpm --filter @amc/web test:e2e  # e2e/vnexus-studio.spec.ts
```

Chromium, Pillow and FFmpeg tests are skipped, and verification reports `NOT_RUN`, when a dependency is absent.
`NOT_RUN` is never reported as passing.

## Known limitations

- The 14 original source prompts are absent; the inventory reports `SOURCE_REQUIRED`.
- No hosted provider adapter exists, so AI image and video shots stay `BLOCKED`. Adding one means implementing a
  `MediaProvider`, verifying it, and obtaining explicit spend authorization; flipping a flag is not enough.
- Provider jobs run synchronously in the request; no worker is deployed.
- `SAAS_DASHBOARD` and `WEB_APPLICATION` experiences are specification only.
- Graph read access is governed by the brand's owner project.
- Art-direction and immune checks are deterministic heuristics. They do not replace human creative review;
  approvals stay human.
