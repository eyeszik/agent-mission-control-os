# VNEXUS creative directions

Brand-aware concept generation or import, evidence-based visual review, human direction selection, conditional
vector reconstruction and master freeze, on top of the existing VNEXUS genome, Project OS storage, media fabric and
approval route. Code: `services/langgraph/agency/vnexus/directions/`, routes in `api/routes/vnexus.py` (creative
directions section), Zod twins in `packages/shared/src/schemas/vnexusDirections.ts`, UI in
`apps/web/components/mission-control/vnexus/DirectionsArea.tsx` (VNEXUS Studio → Creative Directions).

The 14 review seats, six modes and eight stages are **PROPOSED** definitions. The original board specification was
not supplied, so nothing here claims to reproduce it.

## Authority

- The approved genome (plus assets it pins by hash) is authority. Intents, candidates, reviews, reconstructions and
  brand books are derived artifacts.
- Generated content never changes brand rules. A master enters the genome only as a **DRAFT** that goes through the
  existing genome review (`submit_version` → `/approvals/{id}/decide` → settle).
- A review **recommends** and writes **work orders**. It cannot regenerate, spend, approve, mutate a master or publish.
  Every session carries `effects` fixed to `false`, and the Zod twin refuses any other value.
- Human direction selection is an `open_artifact_approval` on the candidate's exact bytes, decided only on
  `/approvals/{id}/decide`. The approver role and separation of duties are enforced there.
- No new table, migration, scheduler, approval store or canonical brand object is added. Every record is a Project OS
  artifact written through `foundry.studio.store`. The per-intent ledger is revised with a compare-and-set on its head
  hash.

## The eight stages

| Stage | Code | What it does |
|---|---|---|
| 1 Intake | `intent.intake` | Field decisions for each brief field: `VALUE`, `NONE` (`"@none"`) or `UNKNOWN` (missing), each with its consequence. Instruction-like text, external-effect requests and third-party marks are PROHIBITED and block the intent; the filters are reused from AVIC intent. |
| 2 Compile | `intent.compile_intent` | One shared `CreativeIntent` per (genome resolution, brief, compiler version). It runs through the **existing** prompt compiler via `prompt_genome.compile_genome_prompt` and must reach `PROMPT_PACKAGE_READY`. It emits separate image instructions (bounded, distinct direction slots; default 3, max 4) and vector instructions. **Exact identity text is kept out of raster prompts** and set later from the approved face. |
| 3 Generate / import | `service.generate`, `service.import_candidate` | `generate` runs only the pinned, authorized route (`local.foundry_compose`, or `mock.simulated` in tests) through `fabric_service`. A disabled or priced route calls nothing and returns the manual handoff package. `import_candidate` stores operator results with `USER_REPORTED` provenance. |
| 4 Record | `records.GenerationCandidate` | Server-observed facts (`observed`: bytes, sha256, read-back sha256, mime, dimensions, artifact version, format class) are kept apart from reported metadata (`reported`: provider, model, version, seed, parameters, time, job and receipt refs, reported cost, rights basis, reference ids). `cost_measured_minor` is set only by an adapter that measured it. Near-duplicates are flagged by perceptual hash. |
| 5 Review | `review.review` | 14 lenses, six modes, evidence-linked findings, criterion assessments, non-compensatory gates, verdicts, an emotional map, brand memory and work orders. See below. |
| 6 Select | `service.request_selection` | Opens the existing approval for one candidate. It is refused for SIMULATED output, BLOCKED or REVISE candidates, other bytes, or a changed genome. |
| 7 Reconstruct | `reconstruct`, `service.reconstruct_candidate` | Runs only when the role needs editable paths and only after an approved selection. See below. |
| 8 Freeze | `service.freeze` | Needs an approved selection, a PASSED reconstruction where one is required, and a RELEASE review that is `READY_FOR_APPROVAL` on the master's exact bytes. It then creates and submits a genome draft pinning `visual.logo.master_artifact` and `visual.logo.master_sha256` (logo roles; other roles use `visual.assets.<role>.*`). |

## Routes (providers)

`directions/providers.py`. Each route records: provider/model, tasks, formats, credential reference (env var
**name**, presence only), model pin, quota scope/reset, price, pricing source and checked-at, data-policy
eligibility, request limits, timeout/reconciliation, approved fallback routes and live health.

| Route | Task | State |
|---|---|---|
| `local.foundry_compose` | deterministic vector concepts from the approved genome (marks, icons) | AVAILABLE, zero cost |
| `manual.handoff` | prompt package export, result import | AVAILABLE; imports stay USER_REPORTED |
| `local.measure` | deterministic measurements on stored bytes | AVAILABLE |
| `local.trace` | controlled trace (AVIC H1 region split) + Chromium fidelity | AVAILABLE; fidelity needs Chromium |
| `cloudflare.workers_ai.text_to_image` | text-to-image concepts | **DISABLED**: no adapter, entitlement unverified |
| `gemini.image_critique` | rendered-image critique | **DISABLED**: the model router has no image-input path |
| `exa.research` / `tavily.research` | source-linked research (one, not both) | **DISABLED** |
| `groq.text` | optional text/transcription | **DISABLED** |
| `mock.simulated` | lifecycle tests | only with `AMC_VNEXUS_MOCK_PROVIDERS=1` outside production; output is SIMULATED |

- **Spend.** `AMC_VNEXUS_SPEND_MODE` defaults to `zero`. A route whose price is unknown or non-zero is refused and
  the manual handoff is offered.
- **No silent substitution.** A request names one route. A refusal never falls through to another model.
- **What research is not.** Earlier provider research is discovery evidence, not account entitlement. A connection
  manager (e.g. Nango) is not generation rights, a chat subscription is not API usage, and free-credit directories
  are not pooled balances.
- **Not implemented.** There is no browser automation and no quota circumvention.
- **Enabling a hosted route** means writing and verifying a real adapter. Before that, recheck current official
  capabilities, quotas, pricing, terms and data handling for the account. Setting a credential enables nothing.

## Review board

**Lenses (PROPOSED).**

| Seat | Lens |
|---|---|
| 01 | Brand strategist |
| 02 | Creative director |
| 03 | Identity designer |
| 04 | Typography |
| 05 | Composition |
| 06 | Color |
| 07 | Accessibility |
| 08 | Imagery/art direction |
| 09 | Emotional response |
| 10 | Brand memory |
| 11 | Production/vector |
| 12 | Application/UX |
| 13 | Brand safety/rights |
| 14 | Evidence/QA |

Each lens has named criteria (`review.LENSES`). Seats are perspectives in one schema, not separate calls. Seats that
share one assessor are labelled as correlated.

**Assessors.**

- `LOCAL_MEASUREMENT` produces findings and gate evidence from the stored bytes, and **never creative scores**. It
  measures:
  - dominant colours and off-palette share (ΔE76 against the approved roles);
  - dominant-pair WCAG contrast;
  - luminance retention at 32 and 16 px, labelled INFERRED;
  - SVG geometry, safety, raster embedding, editable text and PII-like text.
- `HUMAN` is a named reviewer supplying findings, 0–10 rubric scores and gate attestations (OBSERVED only).
- No vision model route is enabled. A lens that needs perception and has no human input is **NOT_REVIEWED**, with the
  reason `VISION_CRITIQUE_ROUTE_DISABLED`. Scores are `null`, never zero and never synthesised.

**Modes.**

| Mode | Lenses | Rule |
|---|---|---|
| QUICK | 04, 06, 07, 13, 14 | Triage only. It never yields `READY_FOR_APPROVAL`. |
| FULL | All applicable | Missing required lenses → BLOCKED. |
| COMPARE | 01, 02, 03, 04, 05, 06, 10, 13, 14 | Blinded labels (A, B, … by content hash). Recommends only with coverage ≥ 50% of creative criteria scored for every eligible candidate and a lead ≥ 1.0 rubric point. Equal weights, disclosed, with the missing criteria listed. |
| REFINE | 14 plus the base work orders' seats | Checks each base work order (MET / NOT_MET / NOT_VERIFIED) and detects metric and gate regressions. |
| VECTOR | 03, 04, 06, 07, 11, 13, 14 | — |
| RELEASE | 04, 06, 07, 11, 12, 13, 14 | An UNKNOWN gate → BLOCKED. Readiness only; never approval. |

Lenses not applicable to the role are recorded as such:

- 04 when there is no identity text;
- 08 for vector roles;
- 11 for photography and texture.

**Non-compensatory gates.**

| Gate | Rule |
|---|---|
| `EXACT_IDENTITY_TEXT` | Strings must be present verbatim as editable text in the master. At concept stage it is not applicable, because the text is set in vector production. A raster master without OCR is UNKNOWN. |
| `ACCESSIBILITY` | ICON: WCAG 2.2 1.4.11 at 3:1 on the measured figure/ground. Logotypes are exempt from 1.4.3. Hero text overlays are checked downstream. |
| `SAFETY_PRIVACY_RIGHTS` | Unsafe SVG, PII-like text or a prohibited brief → FAIL. An import with no rights basis, or only the importer's statement, is UNKNOWN until seat 13 attests an OBSERVED inspection. |
| `CANONICAL_INTEGRITY` | Bound to the current approved genome. Masters must also be palette-only. |
| `OUTPUT_PROVENANCE` | Stored bytes re-hash. SIMULATED output → FAIL. |

A failed gate gives REVISE; aesthetics cannot offset it. Unknown critical evidence blocks readiness; it is never
turned into a fabricated failure.

**Verdicts.**

- `BLOCKED`: critical dependency or evidence missing.
- `REVISE`: observed defects.
- `RECOMMENDED_DIRECTION`: COMPARE favourite; not an approval.
- `READY_FOR_APPROVAL`: checks satisfied; the human decision is pending.
- `INCONCLUSIVE`: evidence insufficient.

**Emotional map.** Target traits come from the brief, or else from `verbal.voice.tone`. Each entry records the
visible cue, the reviewer's interpretation and any possible mismatch. It is labelled as reviewer interpretation, not
audience emotion.

**Brand memory.**

- Observed cues (dominant colours, figure share, aspect).
- Category overlap and predicted memorability come only from reviewers, labelled PREDICTION.
- `measured_recall` is always `HUMAN_RECALL_NOT_TESTED`. There is no participant or recall protocol, and review
  input that tries to carry recall numbers is rejected (422).
- Trademark clearance is `NOT_ASSESSED` and never claimed.

**Work orders.** These are `PROPOSAL_ONLY`. Each one names:

- the change;
- why it is needed, with its finding;
- the protected invariants (IMMUTABLE keys, approved palette roles, exact identity text);
- its dependencies (asset sha256, intent, genome);
- how it is verified.

Vague directives ("make it more premium") are not turned into work orders. Execution is a separate, authorized path
that rechecks identity, permissions, budget and current versions.

## Vector reconstruction

`reconstruct.decide` returns one of:

| Decision | When |
|---|---|
| `RECONSTRUCT` | logo, wordmark, lockup or icon from a raster |
| `NOT_REQUIRED` | the candidate is already native vector |
| `KEEP_RASTER` | photography or texture |
| `OPTIONAL` | illustration or hero image; runs only on explicit request |

Requests outside `RECONSTRUCT`/`OPTIONAL` return 409 with the decision.

**Methods.**

- `controlled_trace`: the AVIC H1 region split on the selected PNG.
  - Gradients are flattened, then every fill is snapped to the nearest approved palette role.
  - Identity text is **never traced**. The operator marks the generated lettering's region; it is masked and the exact
    strings are set as editable `<text>` in the approved display face.
  - Wordmarks and lockups with exact text refuse to trace without that region.
- `native_path_import`: a designer's SVG, validated and measured the same way.

**Validation.**

- SVG safety: no scripts, external references or active content.
- Native geometry: an embedded raster is classified `RASTER_IN_SVG`, never vector.
- viewBox present.
- Palette-only fills.
- Editable exact text.
- Clipping.
- Self-intersections and curve quality are `NOT_VERIFIED` (no geometry kernel; a designer must inspect them).

**Fidelity.** It is measured only from a Chromium render compared pixel by pixel with the selected candidate (mean
ΔE76 ≤ 8, with the text region excluded on both sides). Without Chromium the result is `NOT_VERIFIED`. Neither a parse
nor a path count is evidence of a better design.

**Current method state: PARTIAL.** The trace produces rectangle regions on a 96-px working grid, so curved edges are
visibly stair-stepped. Bezier contour fitting, DiffVG and LIVE are PROPOSED. For a production master, prefer
`native_path_import` of designer geometry, measured the same way.

## Downstream binding and invalidation

- **Brand book.** It resolves the master through `visual.logo.master_artifact`. When the genome pins
  `visual.logo.master_sha256`, any other bytes give `MISSING` ("no longer matches the pinned sha256"); nothing is
  substituted.
- **Identity production.** `production.produce_identity` uses the pinned master for the guidelines deliverable and
  reports `master_binding` as `BOUND`, `MISMATCH`, `UNREADABLE` or `NONE`. A mismatch is a failed ERROR validation.
- **Genome changes.** A new approved genome makes the intent, its candidates and sessions `stale`. Selection and
  freeze then refuse with `GENOME_CHANGED`, and the brand book build is stale through its own freshness check.
- **Changed artifacts.** A revised candidate or master marks pending approvals on the old hash stale
  (`open_artifact_approval`). `artifact_release_verdict` refuses a head that changed after approval.

## API (under `/vnexus`)

| Method | Path | Notes |
|---|---|---|
| GET | `/directions/routes` | route registry and health (no tenant data) |
| GET/POST | `/brands/{b}/directions/intents` | list; create (Idempotency-Key) |
| GET | `/brands/{b}/directions/intents/{i}` | full state with staleness and live binding status |
| GET | `…/{i}/handoff` | manual prompt package |
| POST | `…/{i}/generate` | pinned route (Idempotency-Key); refused routes offer the handoff |
| POST | `…/{i}/candidates` | import (Idempotency-Key); PNG or SVG ≤ 12 MB |
| GET | `…/{i}/candidates/{c}/content` | stored bytes, `default-src 'none'` CSP |
| POST/GET | `…/{i}/reviews`, `…/{i}/reviews/{s}` | create (Idempotency-Key); read |
| POST | `…/{i}/selection` | opens the existing approval |
| POST | `…/{i}/reconstructions` | Idempotency-Key |
| POST | `…/{i}/freeze` | genome draft + submit |

- **Authorization.** All routes take `project_id`; tenant and role come from the principal. Writes need write access
  (viewers get 403).
- **Client authority fields** (`approved_by`, `provenance`, …) are rejected with 422.
- **Security sweep.** `test_vnexus_security.py` covers every route as another tenant, a viewer and unauthenticated.

## Performance and recovery

- **Pure work is reused.** The intent is compiled once per dependency hash; an identical request returns the stored
  intent (`COMPLETE_UNCHANGED`). Canonical assets and tokens come from the genome; review and trace are pure functions
  of the stored bytes.
- **Idempotency.** Writes use the existing scoped idempotency (`vnexus.directions.*`, per tenant and user, with a
  payload hash). Generation jobs use the media-job idempotency key `vdx:<intent>:<run>:<slot>`. A replay adopts a
  finished job. A job found `RUNNING`/`QUEUED` is reported `RECONCILE_REQUIRED` and is never regenerated.
- **Retry safety.** Import and reconstruction are content-addressed; the same bytes give the same candidate.
- **Ledger concurrency.** Ledger writes are compare-and-set, with at most 4 retries.
- **Telemetry.** The ledger keeps the last 200 events. Each holds the operation, ids/hashes, status, duration, error
  code and measured cost only. No bytes, prompts or secrets are recorded, and no external telemetry is sent (Datadog
  is not wired; it would need separate authorization).
- **Cancellation.** Completed outputs are kept; nothing deletes candidates.

## Data and migration implications

There is no schema migration. All records are Project OS artifacts:

| Record | N1 type | N3 role |
|---|---|---|
| intent, ledger, candidate record | `creative_concept` | creative_director |
| candidate and reconstruction bytes | `media_asset` | creative_director |
| review session, reconstruction record | `qa_report` | brand_safety_reviewer |

Two genome keys are now meaningful: `visual.logo.master_sha256` and `visual.assets.<role>.master_{artifact,sha256}`.
Existing genomes without them behave as before.

## Demo (synthetic)

`python scripts/render_directions_demo.py` writes `runtime/directions/demo/` for the FICTIONAL brand "Halden & Fen". It
contains the intent, the refused hosted route, the local compositions, two synthetic imports, the COMPARE and RELEASE
reviews, the selection, the reconstruction (`master.svg`), the freeze and `summary.json`.

Measured on this run:

- reconstruction mean ΔE76 1.53 and PSNR 22.1 dB against the selected candidate at 96 px;
- the brand book mark resolved as `VECTOR` with the master's sha256;
- 0 provider calls.

## Tests

`services/langgraph/tests/test_vnexus_directions.py`:

| Test | Proves |
|---|---|
| `test_hosted_routes_are_declared_disabled_and_never_substituted` | no secret values, handoff offered, zero spend |
| `test_intent_keeps_exact_text_out_of_raster_and_preserves_pii_and_isolation` | exact text out of raster prompts, [PII] preserved, no cross-brand leakage |
| `test_instruction_like_brief_text_blocks_the_intent` | injection and third-party marks block the intent |
| `test_disabled_route_refuses_and_offers_handoff_while_local_compose_records` | bytes, receipts, measured cost and idempotent intent are stored |
| `test_manual_import_stays_user_reported_and_review_without_vision_is_not_scored` | NOT_REVIEWED/BLOCKED with null scores; the review has no side effects (no job, approval or version) |
| `test_human_scores_recommend_a_direction_but_gates_are_non_compensatory` | an accessibility FAIL defeats perfect scores |
| `test_review_inputs_cannot_claim_recall_or_skip_evidence` | recall numbers rejected; gate attestations must be OBSERVED; vague directives dropped; QUICK never ready |
| `test_work_orders_are_proposals_and_refine_detects_met_and_regressed` | — |
| `test_vector_route_only_when_required_and_unsafe_or_raster_svg_is_refused` | — |
| `test_simulated_output_is_never_selectable` | — |
| `test_viewer_and_other_tenant_cannot_create_or_read` | — |
| `test_ledger_writes_are_compare_and_set` | — |
| `test_end_to_end_brief_to_version_pinned_brand_book` | brief → generation/import → review → human selection → reconstruction → RELEASE review → freeze → genome approval → brand book and identity production bound by hash → a tampered master is refused |

Parity: `test_vnexus_directions_contracts.py` checks the enums and the recorded fixture
`packages/shared/tests/fixtures/vnexus-directions.json`. Regenerate it with
`AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_vnexus_directions_contracts.py` (needs Chromium).
`packages/shared/tests/vnexusDirections.test.ts` parses the same fixture.

## Not done (named, not claimed)

- **Hosted generation, critique and research adapters.** None is implemented. Blockers:
  - a verified adapter;
  - credentials;
  - an entitlement recheck against official terms and pricing;
  - spend authorization.
- **Vision critique.** Perceptual lenses need named human reviewers until a verified image-input route exists.
- **OCR.** Exact text in raster masters is UNKNOWN.
- **Curve fitting.** Bezier contour fitting, self-intersection and curve-quality checks are PROPOSED or NOT_VERIFIED.
- **Recall testing and trademark clearance.** Not performed.
- **Bounded work-order execution.** A work order is a proposal; acting on it is a new generation/import or
  reconstruction by an authorized person.
