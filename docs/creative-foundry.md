# Generative Creative Foundry

`services/langgraph/agency/foundry/` turns a plain-language brief into a connected, verified brand family, rendered
entirely on the host. It extends the existing owners and does not replace them:

| Owner | Role |
|---|---|
| Project OS | Stores every artifact. |
| `agency.design_tokens` | Compiles the tokens. |
| `agency.visual` | Renders and verifies. |
| `agency.intake.release` | Binds approvals. |
| The approvals route | Decides approvals. |

No hosted image or video model is used, and nothing is published, purchased, deployed, sent, or written to a
third-party account.

```
BusinessObjective → HumanNeed → ExperienceIntent → BrandStrategy → CreativeGenome → VisualGrammar
  → CompositionIR / ExperienceIR / SceneIR / MotionIR → local renderer → Project OS artifact → independent proof
```

## Reuse / extend / create / reject ledger

| Concern | Decision | Where |
|---|---|---|
| Artifact store, versions, lineage, invalidation | **Reuse** Project OS: `create/revise_project_artifact`, `depends_on`, `variant_of`, edit requests | `studio.store` |
| Design tokens | **Reuse** the one DTCG compiler; the foundry only authors the document | `tokens.py` → `design_tokens.compile_css` |
| Approval and release | **Reuse** `open_artifact_approval` / `artifact_release_verdict` and `/approvals/{id}/decide` (separation of duties) | `studio.request_approval` |
| Search caps | **Reuse** `agency.creative.ir.ResourceBudget` (population ≤ 4, generations ≤ 2), enforced | `variants.py` |
| Rendering, verification | **Extend** `agency.visual`: browser raster/frames/experience modes, generic Blender spec runner, package scene, configurable flat-graphic colour floor | `visual/` |
| Contrast maths | **Reuse** `ui_ux.tokens.wcag_contrast_ratio` | `genome.py` |
| Uploads, rights | **Reuse** `POST /projects/{id}/uploads` and rights records | UI reference upload |
| FreeVideoForge | **Rejected for brand motion**: it is a narrated-explainer pipeline with no keyframed vector stage. It stays listed as a capability. | `motion.py` docstring |
| Paper.js, SVG.js, Rough.js, p5, Pixi, React Three Fiber, Remotion, Motion Canvas | **Not installed.** Reported MISSING; the shipped routes do not need them | `capabilities.py` |
| Runway, OpenArt, Lovable, Printify, Webflow, Product Design, Superdesign, 3Min API | **Rejected as runtime dependencies** (workflow references only) | — |
| New | CreativeGenome, VisualGrammar ×12, CompositionIR, ExperienceIR, MotionIR, SceneIR, MaterialIR, RenderJob/Manifest, CapabilityManifest, ArtifactProof + state machine, routing, discovery declarations, studio orchestration, `/foundry` API, Creative Foundry UI mode | `foundry/` |

## Modules

- **`contracts.py`.** Strict, frozen, hashable models. `UserBrief` carries no authority: a brief whose
  `existing_project_id` differs from the authorized project is refused.
- **`genome.py`.** `compile_genome` is deterministic. Missing optional fields become `Assumption` records. The palette
  is seeded with contrast floors: ink/paper ≥ 7:1 and accents ≥ 3:1. Invariants are the brand name, the mark, a
  locked palette and stated constraints.
- **`grammars.py`.** Twelve grammars: Swiss editorial, Bauhaus, Constructivist, Art Deco, minimalism, retro
  computing, tactile paper, dimensional glass, synthetic futurism, cinematic typography, collage and spatial
  interface. Each has operators, proportions, grid, type, palette and texture logic, primitives, motion, variation
  axes and anti-patterns. Lineage is stated as *influence*; copying known artwork or marks is an anti-pattern.
  Blending is weighted and deterministic.
- **`compose.py`.** CompositionIR (palette *roles*, never literal colours) → SVG. Text stays live `<text>` and is kept
  out of the art zone, and every string is escaped. Outputs: the mark, light and dark lockups, a 6-pictogram icon
  family, and the poster.
- **`variants.py`.**
  - Operations: seed, mutate (12 dimensions), crossbreed, fork from human edits, render, compare, and lineage.
  - Candidates are overrides, so invariants are untouchable.
  - Diversity is *computed*: parameter, grammar and shape-Jaccard distances.
  - `record_feedback` only accepts a named human and their words.
- **`experience.py`.** ExperienceIR → a working HTML/CSS/JS section, built from three style layers: tokens,
  structure and skin. Real Chromium runs 12 scenarios: first use, keyboard-only, invalid input, returning user,
  network interruption with retry, permission denied, empty data, long content, 320 px, 200 % text, reduced motion
  and font fallback. It also runs page audits for computed contrast, labels and reflow. `counterfactual_skins`
  re-runs the identical scenarios unstyled and under an alternate grammar, and rejects any skin that regresses.
- **`scene.py`.** `package_on_plinth` in Blender Cycles, with the generated poster as the box label. Other scene
  kinds return `SCENE_NOT_IMPLEMENTED`. A missing artwork input fails with `SCENE_INPUT` before rendering. Renders are
  labelled synthetic.
- **`motion.py`.** MotionIR keyframes → SVG frames → Chromium → `encode_video` (FFmpeg) → ffprobe verification. The
  reduced-motion alternative is the final frame as a still.
- **`proof.py`.** SPECIFIED → COMPILED → EXECUTED → OUTPUT_OBSERVED → VERIFIED → APPROVAL_PENDING → APPROVED →
  RELEASE_ELIGIBLE. The state is computed from evidence, and `blocked_at` names the first missing proof.
- **`routing.py`.** Local-first order: reuse → owned assets → procedural → local scene → licensed retrieval
  (disabled) → local model → typed gap. A hosted model is a forbidden route, and each decision records its rejected
  routes and evidence.
- **`capabilities.py`.** Discovers CapabilityManifests from what is installed, and installs nothing.
- **`discovery.py`.** Openverse, Wikimedia Commons, Pexels, Unsplash and Google Fonts declarations: auth, licence,
  attribution, provenance, download and caching. All are `DISABLED`; enabling one without a reviewed adapter gives
  `NOT_IMPLEMENTED`, and no request is ever sent.
- **`studio.py`.** `Mission.run()` persists every deliverable with `depends_on=genome`, then reads each artifact back,
  validates it and builds its proof. When a genome revision invalidates its dependents, the existing invalidation
  queues scoped edit requests (the Brand Universe rule). `create_variant` forks a direction from the stored genome.

## API and UI

`api/routes/foundry.py`. Every route is authenticated, and the project's recorded tenant is resolved first.

| Route | Purpose |
|---|---|
| `GET /foundry/capabilities` | Capabilities, grammars and discovery adapters. |
| `POST /foundry/projects/{id}/missions` | Runs a mission. `Idempotency-Key` required; replays return the first result. |
| `POST /foundry/projects/{id}/variants` | Mutate or fork a direction. |
| `GET /foundry/projects/{id}/artifacts` | List the project's foundry artifacts. |
| `GET /foundry/projects/{id}/artifacts/{aid}/content` | The stored bytes, served with `CSP: sandbox` and `nosniff`. |
| `POST /foundry/projects/{id}/artifacts/{aid}/approval` | Opens an approval bound to the exact head bytes. |

Mission Control gains a **Creative Foundry** mode (`CreativeFoundryPanel.tsx`) with:
- a plain-language brief editor: deliverables, a grammar plus a blend, intensity, quality, reference upload;
- a capability inventory;
- a pan/zoom artboard, keyboard operable;
- preview sizes and accessibility previews (no colour, high contrast, blur);
- a proof and checks inspector;
- a live sandboxed preview of the website section;
- "fork a new direction";
- download;
- an approval request showing the subject hash.

The decision itself stays in the existing Approval inbox.

## Demonstration

`python scripts/render_foundry_demo.py` renders **Halden & Fen**, a clearly labelled *fictional* brand, into
`runtime/foundry/demo/`. It produces:
- the genome JSON;
- a logo family (mark, lockups, a 512 px app icon) and an icon family;
- the poster as SVG and PNG;
- DTCG tokens (JSON and CSS);
- a working website section and its evaluation report;
- three directions with lineage;
- a Blender package scene;
- an MP4 logo reveal and its reduced-motion still;
- the mission manifest, `provenance.json` and `index.html`.

Every file is re-hashed against the stored bytes. No approval is decided by the script.

## Known gaps

| Gap | Status |
|---|---|
| React components | The twin is working HTML/CSS/vanilla JS. React component generation is **not implemented**. |
| Scene kinds | Only `package_on_plinth`. Product-on-plinth, device screen, apparel placement and editorial objects are declared and blocked. |
| Print contracts (bleed, safe area, colour profile) | **Not implemented**. No press-readiness is claimed. |
| Motion templates | Only `logo_reveal`. Kinetic typography, brand intro, social and UI demo are declared, not implemented. |
| Infinite artboard | A bounded pan/zoom board over Project OS artifacts; not an infinite canvas with in-place parameter editing. |
| Discovery adapters | Declared only and DISABLED. |
| Human validation | None. No participants, interviews or usability results exist; the scenarios are automated checks. |
| Determinism | SVG, IR and genome output are byte-deterministic for the same seed and configuration. Chromium rasters and Blender renders are declared nondeterministic across hosts. |

## Acceptance tests (A01–A24)

All tests are in `services/langgraph/tests/test_foundry.py` unless another path is given. Tests marked NOT_RUN-capable
skip with the reason when Chromium, Blender or FFmpeg is absent; a skip is never a pass.

| Id | Test | Needs |
|---|---|---|
| A01 no duplicate artifact store | `test_a01_no_second_artifact_store_or_scheduler` | — |
| A02 no duplicate token compiler | `test_a02_tokens_come_from_the_single_dtcg_compiler` | — |
| A03 same seed = same result | `test_a03_same_seed_and_configuration_gives_the_same_result` | — |
| A04 project isolation | `test_a04_projects_and_tenants_stay_isolated` | — |
| A05 SVG parses and renders | `test_a05_generated_svg_parses_safely_and_stays_on_palette`, `test_a05_a06_a07_*` | browser for the render |
| A06 raster has real pixels | `test_a05_a06_a07_*` | browser |
| A07 dimensions match | `test_a05_a06_a07_*` | browser |
| A08 lineage | `test_a08_variants_preserve_lineage_and_respect_creative_caps` | — |
| A09 unsupported capability blocked | `test_a09_unsupported_capability_is_blocked_not_substituted` | — |
| A10 invariants survive mutation | `test_a10_approved_invariants_survive_every_mutation` | — |
| A11 interface survives restyling | `test_a11_functional_interface_survives_visual_restyling` | browser |
| A12 keyboard-only task | `test_a12_a13_a14_keyboard_reduced_motion_and_font_fallback` | browser |
| A13 reduced motion | the same test, plus `test_a13_motion_has_a_reduced_motion_alternative` | browser |
| A14 font fallback | the same test (a canvas measurement proves the primary is missing and text still renders) | browser |
| A15 missing scene asset recoverable | `test_a15_missing_scene_asset_fails_recoverably` | bpy |
| A16 video has decodable frames | `test_a16_motion_file_has_decodable_frames` | browser + FFmpeg |
| A17 interrupted render, no false success | `test_a17_interrupted_render_leaves_no_false_success` | — |
| A18 change invalidates stale approval | `test_a18_genome_change_invalidates_dependents_and_stale_approval` | — |
| A19 output hash = storage bytes | `test_a19_a22_a23_outputs_are_editable_sources_and_independently_verified` | — |
| A20 publication disabled | `test_a20_external_publication_and_discovery_stay_disabled` | — |
| A21 no unauthorized network | `test_a21_generated_pages_cannot_contact_remote_hosts`; `test_abc_v6.py::test_t08_*` | browser |
| A22 editable source | `test_a19_a22_a23_*` | — |
| A23 independent verification recorded | `test_a19_a22_a23_*`, `test_proof_state_machine_needs_every_proof_in_order` | — |
| A24 existing regression suite | the full backend suite plus `pnpm --filter @amc/web test`, typecheck, build and the seven gates | — |

The UI was also driven in a real browser against a local backend and a production frontend build:
- create a project;
- write a brief and run a mission;
- inspect artifacts on the artboard and in the inspector;
- request an approval bound to the subject hash;
- submit the website section inside its sandboxed preview;
- fork a direction.

That browser script is not part of CI.
