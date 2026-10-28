# VNEXUS brand book — approved genome to a governed, incremental 24-page book

`services/langgraph/agency/vnexus/brandbook/` + the brand book routes in `api/routes/vnexus.py` + `components/mission-control/vnexus/BrandBookArea.tsx` (VNEXUS Studio → Brand Book).

The brand book is a **readable projection** of the approved genome. It is never an authority:

| Authority | Projection | Derived |
|---|---|---|
| Approved genome versions (resolved per scope by `vnexus.service.resolve_scope`) and explicitly referenced approved assets (`visual.logo.master_artifact`) | The book (HTML, PDF in production) | Page packages, readable prompts, raster previews, check records |

Intake evidence and proposals never change the genome directly: `propose_draft` turns them into a genome **DRAFT**, which goes through the existing submit → `/approvals/{id}/decide` → settle flow. Production builds read approved versions only.

## Workflow

```
intake (evidence + proposals) ──► open decisions (gap report) ──► genome draft ──► existing review/approval
        │                                                                              │
        └──────────── PREVIEW build (proposals labelled) ◄───────────── approved genome ┘
                                                                              │
PROMPTS_ONLY compile (24 self-contained prompts, no side effects) ◄───────────┤
                                                                              ▼
                          PRODUCTION build ──► request approval ──► /approvals/{id}/decide ──► local release
                                │                                                            (no external effect)
                                └─► downstream assets (identity, experience, video …) pin the same genome version
```

1. **Intake.** `PUT /vnexus/brands/{b}/brandbook/intake` stores evidence records (locator, class, observations, inferences, unknowns, contradictions, reuse, privacy) and proposals, compare-and-set on the head the caller read. Text is data; `[PII]` stays redacted.
2. **Decisions.** `GET …/brandbook/gaps` groups field-level gaps by key with severity, consequence, the pages they block and the next action, ordered blocking first. Only unanswered consequential questions appear.
3. **Draft and approval.** `POST …/brandbook/intake/propose` writes the proposals into a genome draft at a scope. Approval is unchanged VNEXUS governance.
4. **Compile.** `POST …/brandbook/compile` returns the package and 24 standalone prompts. Nothing is rendered, stored, generated or sent.
5. **Build.** `POST …/brandbook/builds` (operator write, `Idempotency-Key`) renders, measures and stores the book incrementally (below).
6. **Approve and release.** `POST …/brandbook/approval` opens an approval bound to the production book's bytes, decided only on `/approvals/{id}/decide` by someone else. `POST …/brandbook/release` writes a local release record through `artifact_release_verdict` and a freshness check. `external_effects` is always `none`.

## Modes and states

| Mode | Uses | Output |
|---|---|---|
| `SYSTEM_SPEC_ONLY` | approved + proposals | field states and gaps, no pages |
| `PROMPTS_ONLY` | approved + proposals (labelled) | page packages and prompts, nothing rendered or stored |
| `PREVIEW` | approved + proposals (labelled `data-proposed`) | rendered, measured, stored; gaps labelled; raster previews per page |
| `PRODUCTION` | approved only | refuses unresolved required keys and template tokens; PDF printed; eligible for approval |

The build record keeps the states separate: `prompt`, `rendered`, `validated` (`PASSED`/`FAILED`/`NOT_RUN`) and `released` (`NOT_RELEASED` until the release record). Prompt-ready is not rendered, rendered is not validated, and validated is not released.

## The template

`manifest.py` holds a versioned, typed 24-page template (`amc-brandbook/default 1.0.0`). It is a proposed implementation template, not recovered source material, and it names no brand: no INTERVAL MATTER / APRES STATIC names, palettes, slogans, geometry or compositions. Each page declares `required_paths`/`optional_paths` (its genome keys, which are also its dependency set), template `exact_copy`, `asset_refs`, layout, prohibitions, checks, output modes and `gap_behavior`:

* `BLOCK` (premise, voice, logo pages, colour, type): production refuses the page; drafts label the gap (`MAJOR`).
* `LABEL` (cover, clear space, scale …): drafts label it (`MINOR`); production refuses it.
* `DECIDE` (layout, graphics, imagery, editorial, digital, motion): a conditional section needs an applicability decision, `production.brandbook.applicability.<page>` = `"@not_applicable: <reason>"`, or its own keys. Content is never invented.

Contents (p02), handoff (p23) and release (p24) read every page and are rebuilt whenever any page changes.

## Field states and evidence

`FieldState.status` is `VALUE`, `NONE` (explicit `"@none"` in the genome), `NOT_APPLICABLE` (`"@not_applicable: reason"`), `PROPOSED` (draft or intake, never approved) or `UNKNOWN`. `approved` is separate governance status. `NONE` and `NOT_APPLICABLE` print as labelled decisions, never as copy.

`EvidenceClass` (`OBSERVED`, `USER_REPORTED`, `INFERRED`, `UNKNOWN`, `PROPOSED`) sits alongside the genome's `ProvenanceKind`. A user-reported statement is not independent inspection.

## Canonical assets

`assets.resolve_mark` resolves one master per build and every page places it by hash. The order of preference is:

1. An approved master artifact (`visual.logo.master_artifact`), read through Project OS after authorization.
2. A deterministic vector composed from the approved `visual.logo.mark`.
3. A proposed concept, in drafts only, labelled.

A master that cannot be read, or fails SVG safety, is `MISSING`; it is never silently substituted. An SVG embedding a raster is `RASTER_IN_SVG`, never `VECTOR`. A missing master routes the logo pages to identity review, and nothing is drawn in its place. Misuse specimens (p14) are CSS views of the master marked `data-misuse`, and are never stored or used as masters. The composed mark reads only the keys that shape it (palette, grammar weights, mark id, wordmark, the two faces). A voice or clear-space edit therefore leaves its bytes, and every logo page, untouched.

## Rendering and checks

`render.py` is deterministic HTML. The page format comes from `production.output.page_format` (A4/Letter portrait or landscape, 16:9, square); without it the default is labelled provisional. Colours come from the approved palette; without one, neutral rendering colours are labelled as such. There is no `overflow:hidden`. Pages are paginated by estimate first (continuation pages keep the page id), then measured in local Chromium through the new `layout` mode of `visual/browser_runner.cjs`.

`checks.py` turns the measurements into per-page checks:

* `no_overflow`, `exact_copy` (rendered `textContent` against the package), `min_font`, `no_overlap`
* `mark_continuity` (every placement is the canonical sha), `status_labelled` (no colour-only meaning), `footer`
* `text_contrast` (WCAG 2.2 AA), `no_unresolved_tokens`

A check that could not run is `NOT_RUN`, never `PASSED`, and production treats it as blocking. The overflow ladder is:

1. Hide decoration.
2. Hide optional annotations.
3. Continue the page.
4. Report the failure.

Required content is never dropped or shrunk below 10 px.

The identity system's `brand_guidelines` deliverable is now rendered by the same compiler from the approved projection. The old five-section template, with its invented "a quarter of the mark" clear space, 24 px minimum size, fixed A4 page and `overflow:hidden`, is gone. Without approved values those pages now say so.

## Incremental build, cache and recovery

* **Dependency hash per page.** The page's declared keys' states, the style keys, the canonical mark's hash (asset pages), evidence (p05), template/compiler versions, mode and locale.
* **Stored page records.** One versioned Project OS artifact per page (`vbb-<digest>-<page>`) holds the rendered sections and the checks measured on exactly those sections. A page whose stored record has the same dependency hash and renderer version is reused without compiling, rendering or measuring. Its checks are reused only for the same validator version, and only if they were measured whenever measuring is possible now.
* **Resume.** Page records are written page by page and the build record last, so an interrupted build resumes from the pages already stored.
* **Provenance rebinding.** The build record (`vbb-<digest>-build`) always binds the current genome version and resolution hash, even when every page's bytes were reused. An identical rebuild leaves it `reused_unchanged`.
* **Process cache.** Compiled page packages are cached in memory, keyed `(tenant, project, dependency hash)` and read only after authorization; at most 2,048 entries. It holds pure compiler output, never approvals or release decisions.
* **Freshness.** `GET …/builds/current` re-resolves the genome. A changed genome (`GENOME_CHANGED`) or changed book bytes block approval and release until the book is rebuilt. An old approval can never release new bytes.
* **Key length.** Artifact keys are short digests because Project OS slugs keys to 64 characters. Long keys collided during development, and `_put` now refuses any key that would be truncated.

Concurrent identical requests are deduplicated by the existing `Idempotency-Key` reservation. There is no second scheduler: a build runs synchronously in its request with one batched Chromium run for the body pages and one for contents, handoff and release.

## API

| Route | Who | What |
|---|---|---|
| `GET /vnexus/brandbook/template` | any principal | the manifest, its hash, the modes |
| `GET`/`PUT /vnexus/brands/{b}/brandbook/intake` | reader / writer | intake record with its sha; CAS on `expected_sha256` |
| `POST …/brandbook/intake/propose` | writer | proposals → genome DRAFT |
| `GET …/brandbook/gaps` | reader | decisions |
| `POST …/brandbook/compile` | reader | package and prompts; no side effects |
| `POST …/brandbook/builds` | writer + `Idempotency-Key` | incremental build |
| `GET …/brandbook/builds/current`, `book.html`, `book.pdf`, `pages/{p}/preview.png` | reader | stored outputs; HTML served with `default-src 'none'; img-src data:; sandbox` |
| `POST …/brandbook/approval`, `…/release` | writer | approval request; local release |

`test_vnexus_security.py` sweeps every route as another tenant, a viewer and unauthenticated. Requests reject unknown fields, so a client cannot send a tenant, approver or brand value. Zod twins are in `packages/shared/src/schemas/vnexusBrandbook.ts`, checked against `packages/shared/tests/fixtures/vnexus-brandbook.json` (regenerate with `AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_vnexus_brandbook_contracts.py`; needs Chromium).

## Measurements

`python scripts/bench_brandbook.py --samples 3 --label <label>` writes `runtime/brandbook/benchmark.json`. Setup: PREVIEW mode, the fictional `FULL_DOC` brand, 24 pages, local filesystem + SQLite, Chromium 141 on this container, 3 samples per scenario. Medians are reported with min–max; percentiles are not reported because 3 samples are too few.

| Scenario | Before (separate sections + checks artifacts) | After (one page record) | Pages rendered / reused | Browser runs |
|---|---|---|---|---|
| Cold build | 11.4 s (9.7–13.1) | 8.7 s (7.6–8.9) | 24 / 0 | 2 |
| Warm identical build | 178 ms (175–188) | 122 ms (121–123) | 0 / 24 | 0 |
| One-page copy edit (voice) | 3.5 s (3.2–3.8) | 3.1 s (2.8–3.2) | 4 / 20 | 2 |
| Global palette edit | 10.8 s (10.0–12.1) | 8.3 s (7.9–9.1) | 24 / 0 | 2 |
| Resume after interruption | 7.5 s (7.3–8.9) | 6.1 s (5.8–6.4) | 15–16 / 8–9 | 2 |

Profiling the cold build showed storage dominating, about 7.1 s of 11.4 s: three Project OS writes per page. Folding each page's sections and checks into one record cut storage to about 4.1 s. The remaining cold time is roughly half storage and half Chromium measurement (about 3.9 s). Compilation is about 12 ms for 24 pages, and no model is called.

Two brands in two tenants built concurrently stayed isolated: each book carries only its own name. Wall time rose to about 20 s each, because writes serialize on SQLite and Chromium runs share the host.

## Requirement → test evidence

| Requirement | Test |
|---|---|
| Template complete, ordered, brandless | `test_manifest_is_a_complete_ordered_brandless_template` |
| Two unrelated brands: no leakage of names, colours, voice, assets or example defaults | `test_two_unrelated_brands_do_not_leak_names_colours_voice_or_assets`, benchmark concurrent isolation |
| Unicode exact text, NONE/UNKNOWN, `[PII]`, injection stays copy | `test_exact_unicode_copy_decisions_unknowns_pii_and_injection` |
| Production refuses gaps and proposals; drafts label them | `test_production_refuses_unresolved_keys_and_never_prints_proposals` |
| Deterministic packages; dependency closure | `test_packages_are_deterministic_and_rebuild_only_the_dependency_closure`, `test_build_is_incremental_cached_and_rebinds_provenance` |
| Canonical mark reuse; misuse never master; no clipping CSS | `test_canonical_mark_is_reused_and_misuse_specimens_are_never_masters` |
| Asset preference; raster-in-SVG ≠ vector; missing master → identity review | `test_asset_preference_raster_in_svg_proposals_and_missing_masters` |
| Page format from the genome; pagination never drops content | `test_page_format_comes_from_the_genome_and_defaults_are_labelled` |
| Identity guidelines without invented rules | `test_identity_guidelines_no_longer_invent_clear_space_or_minimum_size`, `test_identity_production_end_to_end` |
| Interrupted build resumes | `test_interrupted_build_resumes_from_stored_pages` |
| Cache scoped to tenant/project; authorization before cache | `test_cache_entries_are_scoped_to_tenant_and_project` |
| Intake CAS; proposals only become drafts | `test_intake_is_cas_protected_and_proposals_only_become_drafts` |
| Decision-focused gap report | `test_gap_report_groups_decisions_by_consequence` |
| Production approval, separation of duties, release, staleness, version-pinned downstream asset, selective rebuild | `test_production_book_approval_release_and_freshness` |
| Measured checks pass; inert HTML; previews | `test_preview_pages_pass_measured_checks_and_serve_inert_html` |
| Tenant / viewer / unauthenticated isolation, client authority rejected | `test_vnexus_security.py` (sweeps the new routes automatically) |
| Python ↔ Zod parity | `test_vnexus_brandbook_contracts.py`, `packages/shared/tests/vnexusBrandbook.test.ts` |
| Operator path in the browser | `apps/web/e2e/vnexus-studio.spec.ts` (decisions, production refusal, 24-page preview) |

Sample outputs for a fictional brand: `python scripts/render_brandbook_demo.py` writes `runtime/brandbook/demo/` (book.html, prompts.json, package.json, checks.json with 216 measured checks passing, six page previews).

## Not done (named, not claimed)

* **Cancellation and backpressure.** There is no cancellation endpoint or bounded queue; a build runs synchronously in its request. Interruption is recovered by resume, not cancelled.
* **Second-person flows in the browser test.** The E2E test runs as one operator. Approval by a second person is covered by the backend tests.
* **Fonts.** Font files are not embedded and licences are not verified; previews use the installed face or a fallback, and p16 says so.
* **Physical print.** Physical-size print tests and print colour management (ICC) are `NOT_RUN`.
* **Construction.** Construction (p08) shows the canvas boundary and centre axes; optical construction is printed only when `visual.logo.construction` is recorded.
* **Locale.** Only `en` is compiled; the locale is part of every dependency hash, so others can be added without stale reuse.
* **Old page versions.** Stored page records keep their version history in Project OS. There is one head per page, but old versions are not pruned.
* **Generated artwork.** No AI image or model generation: original artwork (imagery, illustration) stays a provider gap. The compiler emits prompts and never calls a provider.
* **External tools.** Exa, Wolfram, gstack, Datadog, OGENIC and Codex Tasks were not used. Nothing here depended on them, and no account, telemetry or remote task was created.
