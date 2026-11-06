# UI/UX design compiler

`services/langgraph/agency/ui_ux/` compiles governed product, brand, and
audience state into a validated **UI/UX specification** — information
architecture, flows, a design genome, DTCG tokens, screens, components, a
complete state matrix, interactions, responsive transforms, accessibility,
performance budgets, AI-trust rules, an implementation map, and prompt inputs.

It stops there. The terminal success state is `UIUX_SPEC_READY`; there is no
`UI_GENERATED`, `ASSET_GENERATED`, or `DEPLOYED` state, and the compiler never
calls a model provider, renders UI, writes a generated asset, or publishes
anything. Downstream generation still needs an approved executor and a human
approval, exactly like the rest of the pipeline.

## Where it runs

| Entry point | Behaviour |
| --- | --- |
| `design_brief` node (`graph/agency/nodes.py`) | Deterministic subprocess. Runs only when the brief describes a digital product (product type / idea / channels mention app, website, dashboard, platform, …). Stores the spec on `DesignBrief.ui_ux` and records `agency.ui_ux_compilation`. Non-UI briefs get `ui_ux: null` and status `SKIPPED`. No new graph stage exists. |
| Prompt compiler, `PromptFamily.UI_UX` | Each UI_UX asset requirement is compiled to a spec; its directives enrich the `PromptIR` buckets, the serialized prompt gains a *UI/UX design specification* section carrying the `spec_hash`, and `PromptPackage.ui_ux_design` holds the full spec. A `BLOCKED` spec blocks the package; `REQUIRES_APPROVAL` marks it for repair. Other families are byte-identical to before. |
| CLI | `python3 orchestrate_brand_pipeline.py ui-ux --input sample_ui_ux_request.json` (or `make ui-ux-compile`). Prints a summary; writes only with `--output` / `--css`. Exit 0 = `UIUX_SPEC_READY`, 1 = needs approval/blocked, 2 = unreadable request. |

What does **not** change: degraded-provider semantics (a spec built from
fallback output lists that source, loses confidence, and does not un-degrade the
run), release guards, the HITL interrupt before `delivery`, auth, and tenancy.

## Framework authority

Each framework is applied only inside the concern it governs; when two appear
to conflict, first check they govern the same concern, then prefer the higher
row and record the conflict.

| Order | Framework | Authority | Used for |
| --- | --- | --- | --- |
| 1 | Repository security/governance contracts | Binding | Everything |
| 2 | WCAG 2.2 | **Normative** | Accessibility requirements and every pass/fail contrast verdict |
| 3 | DTCG 2025.10 | Technical specification | Token structure, aliases, serialization — not accessibility |
| 4 | Repository design conventions (Zinc/Emerald baseline, token tiers) | Binding locally | Frontend tokens |
| 5 | APCA (APCA-W3 0.0.98G constants) | **Advisory** | `apca_lc_advisory` beside each WCAG ratio; never substituted for it, never merged into one score |
| 6 | Carbon, Spectrum 2, Apple HIG, Porsche Design System | Reference only | Transferable patterns; nothing is installed and no conformance is claimed |

Accessibility claims carry a verification class: only token contrast is
`VERIFIED_STATIC`; name/role/value needs `REQUIRES_ASSISTIVE_TECH`; keyboard,
reflow, zoom, and forced colors need `REQUIRES_HUMAN_EVALUATION` or browser
runs. The compiler never claims full AAA conformance from a spec.

## Pipeline

```
REQUEST → PRODUCT → USER → TASK → IA → FLOW → PRINCIPLES → DIRECTION
→ DESIGN_GENOME → TOKENS → SCREENS → COMPONENTS → STATES → INTERACTIONS
→ RESPONSIVE → A11Y → PERFORMANCE → AI_TRUST → IMPLEMENTATION
→ evaluate + bounded repair (≤3) → UIUXDesignIR (spec_hash)
```

* **Surface** — explicit, or inferred from wording (`LANDING_PAGE`,
  `APPLICATION`, `DASHBOARD`, `AI_INTERFACE`, `FORM_FLOW`). Inference and every
  other gap become recorded `assumptions` / `unknowns`, never silent defaults.
* **Principles** (`principles.py`) — a catalog of usability, heuristic, Gestalt,
  cognitive, behavioral, visual, interaction, platform, and system principles.
  Each is data: trigger features plus concrete *effects* on the IR. A principle
  is recorded as applied only if an effect changed something (`changes` lists
  the IR paths). Routing is deterministic; no LLM.
* **Direction and genome** — candidate territories are scored against surface
  and brand tone; the rest are kept with a rejection reason. The design genome
  (hierarchy, density, geometry, typography, color, material, motion,
  interaction, signature) is hashed for cross-screen coherence.
* **Tokens** (`tokens.py`) — a tiered DTCG document (T1 primitive → T2 semantic
  → T3 component) derived from the brand palette and genome, compiled by the
  shared compiler, with WCAG 2.2 contrast checks per semantic pair. A palette
  that cannot reach 3:1 non-text contrast is replaced by the baseline accent
  *and reported*; a missing palette leaves the spec at `REQUIRES_APPROVAL` for
  the `design_token_set` role.
* **States** — all 29 states (`DEFAULT` … `UNAVAILABLE`) have a full contract:
  trigger, visual/content delta, semantics, keyboard, announcement, motion,
  recovery, persistence, and a non-color channel for every status-like state.
* **Metrics** — every budget carries a truth label. Nothing is `MEASURED`
  without a timestamp (schema-enforced); spec budgets are `NOT_MEASURED`.
* **AI trust** — one `AITrustEnvelope` scope per AI response; provider/model
  and sources only when the backend reports them; no numeric confidence
  without a calibrated backend contract (`confidence_display: NOT_MEASURED`).

### Quality engines (`evaluator.py`)

| Engine | Checks | Repair |
| --- | --- | --- |
| `ANTI_GENERIC` | Unjustified gradients/glows/glass/blobs/pills/AI badges; generic SaaS copy | Adds pattern/content rules; an explicit brand constraint justifies a motif |
| `SALIENCE_BUDGET` | P3 region never outweighs P0 | Demotes P3 emphasis |
| `INTERACTION_DEBT` | Nonstandard interaction needs justification + fallback | Adds a keyboard fallback; a missing *justification* is escalated (`DECISION:`), never invented |
| `STATE_ENTROPY` | Different states must not look identical | — (blocking) |
| `COUNTERFACTUAL_UX` | Color/motion removed, no pointer, halved viewport, +200% copy, empty data, denied permission, degraded network, AI unavailable | Adds the missing state/rule/input mode |
| `LAYOUT_GRAMMAR` | Region spacing tokens exist | Resets to `semantic.space.stack` |
| `TRACEABILITY` | Screens → components → tokens resolve | — (blocking) |
| `CONTRAST` | WCAG 2.2 pass/fail per pair | Escalated as a palette decision |

Terminal: unresolved blocking finding → `BLOCKED`; any `DECISION:` approval →
`REQUIRES_APPROVAL`; otherwise `UIUX_SPEC_READY`. Design-lead sign-off (HITL) is
always listed in `approval_required`.

## Tokens: one compiler

`services/langgraph/agency/design_tokens.py` is the only DTCG compiler:
READ → VALIDATE → RESOLVE_ALIASES → DETECT_CYCLES → TYPECHECK → NORMALIZE →
GENERATE_CSS. Cycles fail with the full chain, unknown aliases and type
mismatches fail with the token path, output is sorted and namespaced with a
generated-file header and source hash, and wide-gamut colors must carry an sRGB
`hex` fallback. It serves three consumers:

* the frontend — `apps/web/tokens/amc.tokens.json` → `apps/web/app/tokens.css`
  via `pnpm tokens:build` (`--check` is a dry run that writes nothing);
* the runtime brand design-system package (`tokens_json` is now real DTCG
  2025.10 — it previously claimed the DTCG `$schema` with legacy syntax);
* the UI/UX compiler.

Consumer code references T2/T3 tokens only. Gates:
`scripts/verify_design_tokens.py` (source exists and compiles, generated CSS is
fresh, every `var(--amc-*)` mapping resolves, no raw colors, no primitive
consumption) and `apps/web/scripts/verify-ui-ast.mjs` (TypeScript-AST: no visual
inline styles, no arbitrary class colors, one AI provenance root). Neither adds
a dependency.

## Contracts

`UIUXDesignIR` (Pydantic, `extra="forbid"`) has a strict Zod twin in
`packages/shared/src/schemas/uiux.ts`. Parity is proven, not asserted:
`test_shared_zod_fixture_matches_the_compiler` fails if the compiler output
drifts from `packages/shared/tests/fixtures/uiux-design-ir.json`, and the shared
vitest suite parses that fixture with the Zod schemas.

## How it was installed

The installation followed an explicit protocol, kept here because it governs
future extensions too:

* **Planning checkpoint before mutation** — repository identity, the real
  integration seams, the bounded file surface, tests, drift, dependency plan
  (none), and rollback were established by inspection before any file changed.
* **Missing-file behaviour** — every path the installer expected was located or
  classified (required-critical / relocated / optional / obsolete / not
  applicable). Nothing was created merely because a prompt expected it; the
  obsolete `tokens.json` → `_tokens.css` side effect of the old token script was
  removed rather than recreated. The same rule is now enforced in CI:
  `verify_repository_invariants.py` fails if CI or `make` invokes a validator or
  package script that does not exist.
* **Dependency safeguard** — no packages were added; `pnpm-lock.yaml` is
  unchanged.

## Limitations and extension points

* Surface templates cover five modes; new modes add a template in
  `compiler._template` and component entries in `_COMPONENTS`.
* `implementation_mapping.verified_existing` stays empty: a pure compiler
  cannot verify a repository. Components the request says exist are `EXTEND`.
* Browser, assistive-technology, and performance measurements are not run by
  the compiler; they are listed in `tests_required` / `NOT_MEASURED` budgets.
* The frontend migrated only new surfaces (the AI trust envelope) to semantic
  token classes; existing components still use Tailwind's Zinc/Emerald utility
  classes, which the gates allow. Migrating them is follow-up work.
* `semantic.color.foreground-muted` (Zinc 500 on Zinc 950) is 4.1:1 — below
  WCAG 2.2 AA for normal text — and is declared for large or non-essential text
  only; existing small labels using `text-zinc-500` inherit that risk.
