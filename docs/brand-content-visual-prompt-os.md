# Brand / content / visual prompt OS (v10 integration)

The user-supplied `L100.UNIVERSAL_BRAND_CONTENT_VISUAL_PROMPT_OS v10.0`
specification is integrated by **decomposition**, not injection. The verbatim
text is kept as provenance in
[`docs/imported-specs/universal-brand-content-visual-prompt-os-v10.md`](imported-specs/universal-brand-content-visual-prompt-os-v10.md)
(`USER_SUPPLIED`, `ADVISORY_SPECIFICATION`). No prompt ever receives it
wholesale, and it grants no runtime authority.

Every capability was mapped onto what already exists. Methodology became
selectively routed guidance. Executable behaviour the repository lacked became
narrowly typed code. Everything that would touch the outside world stayed
specification-only.

## What was reused, extended, and added

| Layer | Status | Where |
| --- | --- | --- |
| Claims, gap hunt, research backfill, validation, firewall | **reused** | `agency/prompt_compiler.py` (five passes, `PROMPT_PACKAGE_READY`) |
| PromptIR | **extended** (additive, default-empty) | `exact_text`, `references` (typed `ReferenceRole`), `render_stages`, `series` (`SeriesBinding`), `evidence_directives` |
| Evidence model | **extended** | `SourceEvidence.query`, `SourceEvidence.freshness_class`; new `ComputationEvidence` and `ComputationAssessment` |
| Comparative claims | **extended** | "faster than", "#1" and "industry-leading" style claims are market claims and need substantiation |
| Copy, content, editing, SEO, UX writing, localization | **guidance** | `pg.copy_content.v1` (COPY family; sections gated by request terms) |
| Attention / hooks | **guidance (evidence-bound)** | `pg.attention.hooks.v1` (social, ads, video openings, thumbnails, OOH, subject lines only) |
| Image/graphic prompt ordering, exact-text reliability, reference roles, series and surface frameworks | **guidance** | `pg.visual_prompting.v1` |
| Print, signage, packaging, merch production | **reused + extended** | `pg.production_design_system.v1` gains `pds.merch_artwork_vs_product` and a vendor-spec-or-UNKNOWN rule |
| Prompt families, SeriesEngine, ConceptLedger, CampaignAnchor, hook lifecycle, paid-media creative spec | **new typed module** | `agency/prompt_families/` |
| Video prompt IR, shots, storyboard, continuity, camera, references | **reused** | `agency/cinematic/` (unchanged except below) |
| Motion identity | **extended** | `cinematic.schemas.BrandMotion.reduced_motion_variant` |
| Design tokens, UI/UX, WCAG | **reused** | `agency/design_tokens.py`, `agency/ui_ux/` |
| Roles | **reused** (mapping only) | `prompt_families/roles.py` maps 26 functional roles to sealed RoleOS skills |

## Authority

Precedence is unchanged. The order is repository security, then runtime
contracts, then N1–N4 and RoleOS, then canonical `BrandCore` and verified
evidence, then explicit project constraints, then guidance (including
everything derived from v10).

- Guidance packs are `ADVISORY` or `EVIDENCE_BOUND_ADVISORY`. They are
  serialized as advisory sections and cannot change claims status,
  `BrandCore`, provider capability truth or terminal states.
- Series invariants are copied from the family spec into every instance's
  `SeriesBinding`. They describe the family and do not override `BrandCore`.
- Functional roles ("copywriter", "brand_guardian" and so on) map to existing
  RoleOS skills by exact or nearest-equivalent name. Role identity grants no
  publication, spend, secret or approval authority.
- Imported text is data. The spec, the hook methodology, retrieved text,
  plugin output and generated prompts cannot promote themselves to
  instructions.

## Routing: minimum sufficient activation

Routing stays in the deterministic guidance router. No LLM decides which pack
applies.

| Request | Packs selected |
| --- | --- |
| one-off homepage hero image | `pg.branding.core` only (unchanged) |
| simple copy rewrite | `pg.copy_content.v1` → `copy.rules` + `copy.rewrite_preservation` |
| landing page copy | copy rules + framework router + messaging system |
| SEO article | copy rules + long-form pipeline + SEO (evidence-bound) |
| UX microcopy | copy rules + UX writing |
| social series card | `pg.visual_prompting.v1` + `pg.attention.hooks.v1` |
| typographic poster | visual prompting + production design system |
| short-form video ad | attention hooks (short-form opening) |
| brand film | unchanged; the cinematic capability owns video |

Copy guidance excludes the IMAGE, PRINT, UI_UX, VIDEO, MOTION and STORYBOARD
families. Visual-prompting guidance excludes the COPY, UI_UX and temporal
families. Hook guidance never activates for brand guidelines, UX microcopy,
error messages or legal copy.

## Exact text and render stages

`AssetRequirement.exact_text` is reproduced verbatim (JSON-quoted) in the
serialized prompt. A missing string is a **blocking** validation failure
(`required-text corruption`). For visual families the compiler emits two
stages:

1. `GENERATIVE_VISUAL`: imagery with copy-safe zones and no rendered lettering.
2. `DETERMINISTIC_LAYOUT`: exact text, logos, prices and disclosures are
   typeset in a layout tool and checked character by character.

Temporal families get `GENERATIVE_MOTION` followed by `EDIT_COMPOSITING`.
COPY gets `VERBATIM_COPY`.

## Evidence ceiling

Each package's prompt lists what may be stated and what may not:

- supported claims, with evidence ids;
- derived claims, with the computation that produced them;
- material claims that are not verified, marked "do not state as fact".

A fabricated statistic or an unsubstantiated comparative claim still blocks
synthesis (`RESEARCH_INCOMPLETE`) until evidence arrives.

**Computation is a separate provenance class.** `ComputationEvidence` records
the question, operation, inputs, units, assumptions, engine, result,
precision and provenance. A derived claim becomes `DERIVED` only when every
empirical input claim is verified. A computation over unverified inputs is
`PREMISES_UNVERIFIED` and never upgrades anything to `VERIFIED`.

## Prompt families

`agency/prompt_families/` runs the source spec's series engine:

1. Freeze the `InvariantSet`.
2. Select a variation combination deterministically. Instance *i* takes
   option *i* on each axis, cycling through the options.
3. Write the concept thesis before any styling.
4. Compare against the `ConceptLedger`:
   - The signature is the SHA-256 of metaphor + composition + subject +
     graphic device.
   - Repeating the full signature is a duplicate.
   - Repeating 3 of those 4 fields is duplicate-risk.
5. Repair a duplicate by changing the **highest-level** axis first, for at
   most 3 passes. If every pass fails, the instance is `REJECTED_DUPLICATE`.
6. Compile each accepted instance through `compile_prompt_packages`, so every
   claim, exact-text and firewall gate applies.
7. Return a new ledger value that includes the accepted and rejected
   signatures.

`series_consistency=0.70` and `novelty_budget=0.30` are configurable advisory
weights, not probabilities. The evaluation reports `varied_axis_fraction`
beside them. The hard gates are invariants held, exact text preserved, and no
duplicate signature.

**Hooks** follow an evidence-gated lifecycle:

- `CANDIDATE` needs nothing.
- `APPROVED_FOR_TEST` needs a human approval ref.
- `MEASURED` needs an approval ref and at least one observation with metric,
  value and window.
- `WINNER_BY_METRIC` also needs the declared comparison metric to have been
  observed.
- `SATURATED` and `RETIRED` need nothing.

A creative score is never observed performance.

`PaidMediaCreativeSpec` is `execution: SPEC_ONLY` and
`platform_mutation: false`. `PAID_MEDIA_MUTATION_PRECONDITIONS` lists the 13
steps a future provider path would need: resolve account, campaign, ad group,
creative type and artwork; preview; show the exact mutation; get explicit human
confirmation; idempotent write; read-back; reconcile; preserve ids; safe retry.
None are performed. `integrations/paid_media.py` is untouched and fail-closed.

**Merch and print.** A `ProductionTarget` always separates `EDITABLE_MASTER`
from `PRODUCTION_EXPORT`. For print, signage and merch, vendor-controlled
fields that were not supplied are emitted as `UNKNOWN`, never as defaults. Merch
artwork is flat and product-independent, and the negative constraints forbid
mockups. Nothing creates, lists or orders a product.

## External capabilities (integration-session discovery)

| Capability | Status | Surface |
| --- | --- | --- |
| Search | evidence interface | `ResearchRequest` → `SourceEvidence(query, freshness_class)` |
| Wolfram | contract only | `ComputationEvidence`; no tool was discoverable |
| Ads Manager | pattern only | `PaidMediaCreativeSpec` |
| Printify | pattern only | `ProductionTarget(MERCH)` + `pds.merch_artwork_vs_product` |
| OGENIC GOD TOOLKIT | **NOT_AVAILABLE** | nothing; no endpoint, schema or command was inferred |

`prompt_families.external_capability_status(name)` returns this record, and
`NOT_AVAILABLE` for any unknown name. The record is provenance, not runtime
truth: provider capability must still arrive as `ProviderCapability` evidence.

## CLI

```bash
python3 orchestrate_brand_pipeline.py prompt-family --input sample_prompt_family_request.json --json
make prompt-family
python3 orchestrate_brand_pipeline.py compile-prompts --input <PromptCompilerRequest.json> --json
```

`prompt-family` exits 0 only at `PROMPT_PACKAGE_READY`. It generates no media,
creates no ads or products, publishes nothing and spends nothing.

## Fixtures and tests

All fixtures in `services/langgraph/tests/fixtures/prompt_os/` are
**synthetic**:

- copy landing page;
- social series;
- typographic poster with exact copy;
- cinematic storyboard/T2V;
- merch artwork;
- paid-media creative;
- research + computation.

```bash
python -m pytest services/langgraph/tests/test_prompt_os.py -q
```

## Capability disposition (source spec areas)

| # | Area | Status | Implementation |
| --- | --- | --- | --- |
| 1 | BrandCore | EXISTS_REUSE | `artifacts/brand.py` (kept qualitative; UNKNOWN/PROPOSED live in claims) |
| 2 | Verbal identity | EXISTS_EXTEND | `brand.verbal_identity` + `pg.copy_content.v1` |
| 3 | Messaging system | GUIDANCE_ONLY | `copy.messaging_system` |
| 4 | Copy engine | GUIDANCE_ONLY | COPY family + `copy.rules`, `copy.framework_router` |
| 5 | Natural writing (Hemingway) | GUIDANCE_ONLY | `copy.rewrite_preservation` |
| 6 | Content intelligence | GUIDANCE_ONLY | `copy.long_form_pipeline` |
| 7 | Reader model | GUIDANCE_ONLY | long-form pipeline + `brand.strategy` audience model |
| 8 | Research grounding | EXISTS_EXTEND | `SourceEvidence.query/freshness_class` |
| 9 | SEO | GUIDANCE_ONLY | `copy.seo` (evidence-bound) |
| 10 | Ideation | EXISTS_REUSE | `brand.creative_direction`, `pds.metaphor_engine` |
| 11 | Headline/hook creation | GUIDANCE_ONLY | `pg.attention.hooks.v1` |
| 12 | Outline | GUIDANCE_ONLY | `copy.long_form_pipeline` |
| 13 | Topical gap | OUT_OF_SCOPE | needs measured search data; no topic-cluster engine added |
| 14 | Editing stack | GUIDANCE_ONLY | `copy.rewrite_preservation` |
| 15 | Repurposing | GUIDANCE_ONLY | `copy.repurpose_localize` |
| 16 | Localization | GUIDANCE_ONLY | `copy.repurpose_localize` |
| 17 | Collaborative authoring | OUT_OF_SCOPE | no multi-author surface; HITL approvals unchanged |
| 18 | Content operations | OUT_OF_SCOPE | editorial calendars/refresh ops not modeled |
| 19 | Creative territories | EXISTS_REUSE | `brand.creative_direction` |
| 20 | VisualDNA | EXISTS_EXTEND | BrandCore visual fields + `InvariantSet` |
| 21 | Design tokens | EXISTS_REUSE | `agency/design_tokens.py` (the only DTCG compiler) |
| 22 | PromptIR | EXISTS_EXTEND | additive fields listed above |
| 23 | Prompt families | NEW_TYPED_MODULE | `prompt_families/models.py`, `compiler.py` |
| 24 | SeriesEngine | NEW_TYPED_MODULE | `prompt_families/compiler.py` |
| 25 | ConceptLedger | NEW_TYPED_MODULE | `prompt_families/ledger.py` |
| 26 | CampaignAnchor | NEW_TYPED_MODULE | `prompt_families/models.py` |
| 27 | Image prompts | EXISTS_EXTEND | IMAGE family + `vis.prompt_order` + reference roles |
| 28 | Graphic prompts | EXISTS_EXTEND | exact text + render stages |
| 29 | Poster framework | GUIDANCE_ONLY | `vis.surface_frameworks` |
| 30 | Social-series framework | GUIDANCE_ONLY | `vis.series_system` (+ typed families) |
| 31 | Carousel framework | GUIDANCE_ONLY | `vis.surface_frameworks` |
| 32 | OOH | GUIDANCE_ONLY | `vis.surface_frameworks` |
| 33 | Infographic | GUIDANCE_ONLY | `vis.surface_frameworks` (verified dataset required) |
| 34 | Packaging | EXISTS_REUSE | `pds.application_family_hierarchy` |
| 35 | Signage | EXISTS_REUSE | `pds.signage_environmental_production` |
| 36 | Web hero | EXISTS_REUSE | UI/UX compiler + `pg.branding.core` |
| 37 | Storyboards | EXISTS_REUSE | `cinematic/storyboard.py` |
| 38 | Video prompts | EXISTS_REUSE | `cinematic/compilers.py` (T2V/I2V) |
| 39 | Continuity | EXISTS_REUSE | `cinematic/continuity.py`, `Canon`, `MemoryPacket` |
| 40 | Motion | EXISTS_EXTEND | `BrandMotion.reduced_motion_variant` |
| 41 | Print production | EXISTS_EXTEND | `pds.print_preflight` vendor-or-UNKNOWN; `ProductionTarget` |
| 42 | Digital production | EXISTS_REUSE | `ProductionSpec`, `pds.email_html_production` |
| 43 | Asset lineage | EXISTS_REUSE | N4 registry, provenance refs + concept signature |
| 44 | Trends | EXISTS_REUSE | `TREND_INTELLIGENCE` packs, `studio.trend_intelligence` |
| 45 | Originality | EXISTS_REUSE | `pds.anti_generic` + genericity test in `vis.series_system` |
| 46 | Research | EXISTS_REUSE | `ResearchRequest` / RESEARCH_BACKFILL |
| 47 | Data | OUT_OF_SCOPE | no dataset/analytics engine; infographics need verified evidence |
| 48 | Computation | EXISTS_EXTEND | `ComputationEvidence`, `assess_computations` |
| 49 | Paid media | ADAPTER_ONLY | `PaidMediaCreativeSpec` (spec only) |
| 50 | Merchandise | EXISTS_EXTEND | `pds.merch_artwork_vs_product`, `ProductionTarget(MERCH)` |
| 51 | Accessibility | EXISTS_REUSE | UI/UX WCAG 2.2 + `vis.accessibility` |
| 52 | Rights | EXISTS_REUSE | legal/market claim gating; `pds` verification flags |
| 53 | Observability | EXISTS_REUSE | run events/analytics; missing telemetry stays NOT_MEASURED |
| 54 | Experiments | NEW_TYPED_MODULE | `HookCandidate` lifecycle |
| 55 | QA | EXISTS_EXTEND | EXACT_TEXT / REFERENCE_ROLES checks + `PromptFamilyEvaluation` |

Summary: 55 areas reviewed.

| Status | Count |
| --- | --- |
| EXISTS_REUSE | 18 |
| EXISTS_EXTEND | 11 |
| GUIDANCE_ONLY | 16 |
| NEW_TYPED_MODULE | 5 |
| ADAPTER_ONLY | 1 |
| OUT_OF_SCOPE | 4 |
| BLOCKED | 0 |

**Hook Point source note.** The attention pack encodes the generalized
principles listed in the project owner's integration directive. The book
itself was not supplied in the integrating session, so the principles were
not checked against it. The pack reproduces no book text.
