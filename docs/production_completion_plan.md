# Production completion plan

**Baseline:** `master` at `c6b5a700`.

- **Inputs:** `docs/system_audit.md` and `docs/capability_gap_register.md`. Gap ids (G-xx) refer to the register.
- **Increments:** each milestone ships as one or more reviewed PRs with green CI. No milestone is "done" until its definition of done holds on the merged commit.
- **Owners:**
  - **AMC eng:** repository work an agent or engineer can do.
  - **Owner:** decisions, credentials, accounts and authorizations that only the repository owner can give.
  - **Operator:** a person with deployment access.

## Rules every milestone follows

| Rule | Requirement |
|---|---|
| Order | Contracts and schema, then services, then adapters, then workflows, then UI, then tests and docs, then activation. |
| Schema changes | Each persistent change is a forward migration with a written rollback. SQLite and Postgres are kept in step, and the CI Postgres job applies every migration. |
| New APIs | Appear in OpenAPI, and the tenant-sweep security tests cover them. |
| Done means | The 7 verifier gates, compileall, the backend suite (SQLite and Postgres), the shared and web typecheck, tests and build, and Browser E2E all pass. Manifest resealed when a pinned file changes. |
| Truthfulness | Capability states in the inventory and README are updated from evidence. A planned check is never reported as passed. |
| Rollback | Revert the PR. Where a migration exists, apply its documented down step. |

## P0: reliability, truthfulness, safety prerequisites

| Milestone | Gaps | Tasks | Depends on | Tests / rollout gate | Owner | Done when |
|---|---|---|---|---|---|---|
| **M0 Truthful records** | G-01, G-02, G-03, G-04 | Replace constant completion scores with `NOT_MEASURED` or a named measurement. Zod parity for provenance fields. Document every environment variable the code reads. Declare optional dependencies as extras. Make the slug test hermetic. | — | Parity fixture; no constant score; inventory shows no undocumented variable; suite passes twice on one DB | AMC eng | The inventory's undocumented list is empty or justified, and no score is unmeasured. |
| **M1 Async runs** | G-05 | Agency create and resume enqueue a durable job; SSE progress; cancellation; lease and heartbeat recovery. | M0 | Crash-between-stages resume, duplicate submit, cancel, SSE ordering, stale-writer rejection | AMC eng | No request runs the graph inline, and recovery tests pass on Postgres. |
| **M2 Model settings** | G-10 | Project and tenant profile API with audit and compare-and-set; readiness rows. | M0 | Precedence end to end; viewer 403; pinned runs unaffected | AMC eng | Precedence works without the environment. |
| **M3 Action prerequisites** | G-06, G-07, G-09 | Budget allocation API; shared rate limiter; per-operation activation records. Still no live adapter. | M0 | Concurrent compare-and-set; cross-process limit; activation-without-evidence refused | AMC eng | A live dispatch is still impossible, and now also requires an activation record. |
| **M4 Step-up and signing** | G-08, G-37 | Step-up bound to actor, session and action; signing-key interface with rotation. | M3 | Replay, expiry and other-actor tests; tamper and rotation tests | AMC eng, then **Owner** (IdP choice, key custody) | Code complete with fakes; active only with the owner's IdP and key. |
| **M5 Handoff package** | G-11 | A typed `HANDOFF_PACKAGE` assembled only from existing records, with gaps stated explicitly. | M0 | Hash re-read; binding mismatch; missing-section reporting | AMC eng | Every delivered run can produce a package without invented content. |
| **M6 Activation** | G-36, G-38 | Postgres backup and restore drill, identities and memberships, exact CORS, secrets, storage, worker, telemetry export, exact-revision smoke. | M1–M5 | The smoke list in G-36, on the deployed revision | **Operator/Owner** | Evidence recorded for that exact commit. Until then the state stays NOT_DEPLOYED. |

**P0 definition of done:**
- Every run is durable, cancellable and observable.
- No recorded metric is unmeasured.
- Live effects remain impossible without a per-operation activation record, step-up where required, an exact approval and a budget reservation.
- A deployed revision has passed the smoke list with recorded evidence.

## P1: production suite and integrations

| Milestone | Gaps | Tasks | Depends on | Owner | Done when |
|---|---|---|---|---|---|
| **M7 Research and knowledge** | G-12, G-13 | Search and fetch adapters with SSRF protection and parser limits; embeddings per tenant; universal brief compiler. | M0, M6 (for live search) | AMC eng, **Owner** (search and embedding providers) | Claims carry source and date; cross-tenant retrieval is empty; injection tests pass. |
| **M8 Brand system** | G-14, G-15, G-16, G-18, G-19 | Brand graph node kinds, drift checks, prompt outcome links, naming checks (provider-gated), motion tokens, sonic briefs. | M7 | AMC eng, **Owner** (registry providers) | Drift detection on seeded violations; no clearance claim without a source. |
| **M9 Studio: design to code** | G-21, G-20 | Node sandbox, then React/Next generation from the UI/UX IR and tokens with an accessibility gate. | M1 | AMC eng | A generated page passes typecheck, lint, tests, axe AA, keyboard and reduced-motion checks. |
| **M10 Studio: image and video** | G-22, G-23 | Image adapters (local first), video captions, cutdowns and render manifest. | M3, M9 | AMC eng, **Owner** (weights or providers) | Bytes re-read and verified; manifests re-derived from `ffprobe`. |
| **M11 Print** | G-17 | Print manifest plus deterministic preflight. | M5 | AMC eng (dependency choice reviewed) | Seeded defects fail and a correct file passes. Drafts are labelled pre-press. |
| **M12 Content, SEO, governance** | G-24, G-25, G-31 | Claim lineage enforcement; sitemap and JSON-LD; LEG and ETH detectors. | M7 | AMC eng | Unlinked claims block approval; seeded dark patterns are caught. |
| **M13 Live adapters, one at a time** | G-26, G-27, G-28, G-29 | Each provider behind §0 controls and an activation record. | M3, M4, M6 | AMC eng, **Owner** (provider, credentials, authorization per adapter) | That adapter's activation receipt and reconciliation tests exist. The others stay gated. |
| **M14 Workflow builder** | G-30 | Natural-language outcome → DAG → mandatory simulation → live through the fabric and gateway. | M3, M13 | AMC eng | A simulation has zero effects; live nodes are gated per activation. |
| **M15 Evaluation and learning** | G-32, G-33 | Deterministic validators, datasets, regression suites, feedback promotion with consent. | M12 | AMC eng | An evaluator regression fails CI; no unapproved default change. |
| **M16 Code health and UI** | G-34, G-35, G-39 | Remove or quarantine legacy code; wire or relabel unwired modules; readiness panel, repair cards, approval change preview. | M0 | AMC eng | Nothing is unreachable unless labelled, and no disabled control lacks an explanation. |

**P1 definition of done:** each production capability in the register is IMPLEMENTED, LOCAL_ONLY, or an explicit PROVIDER_GAP with a repair card, and every live adapter carries its own activation evidence.

## P2: optimisation and scale

| Milestone | Gaps | Depends on | Notes |
|---|---|---|---|
| M17 Specialist agents | G-40 | M14 | Bounded concurrency; role contracts never widen authority. |
| M18 Templates | G-41 | M14, M5 | Rights checks before publishing a template. |
| M19 Scenario planning | G-42 | M13 (analytics) | Always labelled SIMULATION. |
| M20 Enterprise operations | G-43 | M6 | Data residency, quotas, audit export. |
| M21 Telephony | G-44 | M13 | Only after the owner selects a provider and use case. |

## Owner decisions that gate progress

These cannot be made from the repository:

1. Identity-provider step-up method (M4).
2. Signing-key custody (M4).
3. Deployment accounts and activation authorization (M6).
4. Search and embedding providers (M7).
5. Naming and registry providers (M8).
6. Image, video and audio providers or licensed local weights (M10).
7. CMS, social, email, SMS, ads, CRM and analytics providers, each with credentials and explicit live authorization (M13).
8. Whether the Nango connection layer is in scope. `eyeszik/nango` is not attached to this repository's sessions.

## Next increment

**M0 (Truthful records)**: G-01 to G-04. It is small, needs no owner input, and removes the one finding that conflicts with the no-fabricated-metrics rule.
