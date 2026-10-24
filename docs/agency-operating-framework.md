# Agency Operating Framework

The Agency Operating Framework turns the version-pinned 24-module, 295-task agency catalog into **project-scoped work**: per-project task instances, applicability decisions, evidence-bound verification, approvals, five stage gates, KPIs and five non-authoritative assurance records.

It adds an operating ledger on top of existing primitives. It is not a second authority:

- Evidence lives where it already lives: Project OS knowledge, N4 kernel evidence and decisions, N4 artifacts with their version history, and VNEXUS genome versions.
- Approvals are `approvals` rows, opened through `open_artifact_approval` and decided only through `POST /approvals/{id}/decide` (approver role and separation of duties).
- Audit events are `project_events` rows. Each write appends one event in the same transaction as the row it changes.
- Release stays with `agency/delivery`. Publication, spend, send and outreach stay disabled or dry-run. Nothing here dispatches an external effect.

Installing the catalog is not the same as executing 295 client tasks. A new plan starts at 0 verified and 0 approved, with every task in the backlog and unassessed.

Code:

| Area | Location |
| --- | --- |
| Catalog, bindings, engine, refs, assurance, metrics | `services/langgraph/agency/operating_framework/` |
| Vendored catalog and schema | `agency/operating_framework/data/catalog.seed-v1.json`, `catalog.schema.json` |
| Persistence | `persistence/operating_framework.py` (SQLite migration 20; PostgreSQL `supabase/migrations/20261024_amc_agency_framework_v1.sql`) |
| API | `api/routes/agency_framework.py` (`/agency-framework`, 24 paths) |
| UI | `apps/web/components/framework/`, `/framework` (also the **Operating Framework** section of `/agency`) |
| Zod twins | `packages/shared/src/schemas/agencyFramework.ts`, fixture `packages/shared/tests/fixtures/agency-framework.json` |

## Catalog

The catalog is vendored byte-for-byte and pinned by SHA-256 (`9a2c30e9e65c2a3a6de70245cc47bbeeea2c695b965c09a143935d8ce3df501a`, version `amc-agency-operating-framework/seed-v1`). `catalog.load_catalog()` refuses to import it unless **all** of these hold:

1. The bytes match the pin. A different hash is a different catalog version, never a silent upgrade.
2. It validates against the kit schema (an in-repo JSON Schema subset validator; the test suite also cross-checks with `jsonschema` 2020-12 when it is installed).
3. Semantic checks pass:
   - unique module and task ids;
   - per-module counts match the declared counts;
   - every task's module exists;
   - no dependency cycles;
   - the totals agree.

| | Count |
| --- | --- |
| Modules | 24 |
| Tasks | 295 (35 from the supplied AGM-01–03 checklist, 260 authored) |
| Stage gates | 01 Discovery 48 · 02 Strategy 58 · 03 Production 108 · 04 Activation 59 · 05 Growth 22 |
| Disciplines | Discover 48 · Strategize 58 · Design 29 · Build 79 · Activate 59 · Optimize 22 |

To change the catalog, ship a new file with a new version and pin. Existing plans keep their `catalog_version` and `catalog_sha256`.

## Module bindings (capability-to-code matrix)

`bindings.py` binds each module to the following:

- an N3 role that holds the module's N1 artifact type in `produces`. `verify_bindings` checks this against the live kernel.
- the native owner that holds its evidence.
- what this repository can do for it today.
- the external effect it would have if it ever went live.

Coverage is honest:

- **EXACT**: the N3 role's purpose is this module.
- **NEAREST**: the closest role that may produce the artifact.
- **NO_N3_ROLE**: no N3 role exists for the discipline. The nearest producer is used, and the gap stays visible in the UI.

| Module | Title | Tasks | N3 role | Artifact type | Coverage | Native owner | Capability | External effect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AGM-01 | Client Discovery & Business Audit | 10 | `market_researcher` | `research_brief` | NEAREST | project_os.knowledge + agency_kernel.evidence | HUMAN_ONLY | none |
| AGM-02 | Market Intelligence & Opportunity Sizing | 10 | `market_researcher` | `market_analysis` | EXACT | project_os.knowledge + agency_kernel.evidence | HUMAN_ONLY | none |
| AGM-03 | Target Audience & Voice-of-Customer Research | 15 | `market_researcher` | `research_brief` | EXACT | project_os.knowledge + agency_kernel.evidence | HUMAN_ONLY | none |
| AGM-04 | Competitive & Category Benchmarking | 13 | `market_researcher` | `market_analysis` | EXACT | project_os.knowledge + agency_kernel.evidence | HUMAN_ONLY | none |
| AGM-05 | Value Proposition & Offer Validation | 12 | `brand_strategist` | `offer_definition` | EXACT | agency_kernel.decisions | HUMAN_ONLY | none |
| AGM-06 | Brand Strategy, Positioning & Architecture | 12 | `brand_strategist` | `positioning_statement` | EXACT | agency_kernel.decisions + vnexus.genome | HUMAN_ONLY | none |
| AGM-07 | Verbal Identity & Messaging Architecture | 12 | `brand_architect` | `brand_platform` | NEAREST | agency_kernel.decisions + vnexus.genome | HUMAN_ONLY | none |
| AGM-08 | Visual Identity & Brand Design System | 15 | `design_lead` | `design_system_spec` | NEAREST | foundry + design_tokens + vnexus.genome | LOCAL_AVAILABLE | none |
| AGM-09 | Customer Journey & Experience Design | 10 | `design_lead` | `design_brief` | NEAREST | ui_ux compiler + agency_kernel.decisions | HUMAN_ONLY | none |
| AGM-10 | Website, UX/UI & Conversion Architecture | 15 | `implementation_lead` | `app_build_spec` | NEAREST | ui_ux compiler + foundry.experience + execution_fabric | LOCAL_AVAILABLE | none |
| AGM-11 | SEO, Local Search & AI Discovery | 15 | `brand_safety_reviewer` | `qa_report` | NO_N3_ROLE | execution_fabric.seo_checks | LOCAL_AVAILABLE | none |
| AGM-12 | Content Strategy & Editorial Operations | 14 | `copywriter` | `copy_variant` | NEAREST | project_os.content + project_os.calendar | LOCAL_AVAILABLE | none |
| AGM-13 | Social Media & Community Marketing | 12 | `growth_lead` | `campaign_package` | NEAREST | project_os.publishing (dry run) | DRY_RUN_ONLY | publish |
| AGM-14 | Paid Media & Performance Marketing | 12 | `media_planner` | `media_plan` | EXACT | project_os.paid_media (planning only) | PLANNING_ONLY | spend |
| AGM-15 | Email, CRM & Lifecycle Automation | 13 | `implementation_lead` | `automation_spec` | NEAREST | project_os CRM journeys + scheduler (dry run) | DRY_RUN_ONLY | send |
| AGM-16 | Partnerships, Influencers & Referral Programs | 11 | `growth_lead` | `campaign_package` | NO_N3_ROLE | agency_kernel.decisions | PLANNING_ONLY | outreach |
| AGM-17 | PR, Reputation & Social Proof | 11 | `copywriter` | `copy_variant` | NO_N3_ROLE | project_os.publishing (dry run) | DRY_RUN_ONLY | publish |
| AGM-18 | Analytics, Attribution & Data Governance | 12 | `analytics_lead` | `measurement_plan` | EXACT | analytics events + measurement plan | LOCAL_AVAILABLE | none |
| AGM-19 | Experimentation & Conversion Optimization | 11 | `analytics_lead` | `measurement_plan` | NEAREST | project_os growth experiments | LOCAL_AVAILABLE | none |
| AGM-20 | Launch Strategy & Campaign Activation | 13 | `release_manager` | `release_record` | NEAREST | delivery release candidate + approvals | HUMAN_ONLY | publish |
| AGM-21 | Customer Retention, Loyalty & Advocacy | 11 | `analytics_lead` | `measurement_plan` | NEAREST | learning ledger + experiments | LOCAL_AVAILABLE | none |
| AGM-22 | AI, Creative Operations & Automation Governance | 12 | `brand_safety_reviewer` | `qa_report` | NO_N3_ROLE | model profiles + provider capability registry | LOCAL_AVAILABLE | none |
| AGM-23 | Agency Delivery, Finance & Client Governance | 12 | `implementation_lead` | `implementation_plan` | NO_N3_ROLE | agency_kernel.decisions + approvals | HUMAN_ONLY | none |
| AGM-24 | Compliance, Security, Accessibility & Continuity | 12 | `brand_safety_reviewer` | `qa_report` | NEAREST | execution_fabric.wcag_audit + security tests | LOCAL_AVAILABLE | none |

Totals: 7 EXACT, 12 NEAREST, 5 NO_N3_ROLE. Six modules carry an external effect (publish, spend, send or outreach). For those modules the binding only plans the work; the effect itself stays with its existing disabled or dry-run owner.

## Task lifecycle

States: `BACKLOG`, `READY`, `ACTIVE`, `IN_REVIEW`, `VERIFIED`, `APPROVED`, `BLOCKED`, `INVALIDATED`, `NOT_APPLICABLE`.

Applicability values: `UNASSESSED`, `REQUIRED`, `CONDITIONAL`, `NOT_APPLICABLE`. A reason is always required.

Manual moves follow `MANUAL_TRANSITIONS` in `contracts.py`. The web UI reads the same table, and a parity test checks it. Three states can never be set by hand:

- **IN_REVIEW** needs the task's required ref kinds (evidence, decision, artifact or measurement). Every ref must resolve as attachable inside this tenant and project.
- **VERIFIED** is set only by `POST …/verify`. The server re-resolves every ref, and the caller must hold an approver role and must not be the person who submitted the work (`SELF_VERIFICATION`). A failed re-check is recorded on the task and returns 422 `VERIFICATION_FAILED`.
- **APPROVED** is set only by `POST …/settle` after the existing approvals route decides an approval. That approval was opened against `task_proof_hash`, the hash of the plan, the task and the verified checks. If the proof has changed since, settle invalidates the task (`APPROVAL_SUBJECT_STALE`). A rejection sends the task back to `ACTIVE`, and that rework is measured.

Every write is compare-and-set on `version`. A stale version is 409 `STALE_VERSION`; a write never silently overwrites. Writes require `Idempotency-Key`: a replay returns the stored result, and reusing a key with a different body is refused.

`POST …/revalidate` re-resolves every verified or approved task. Tasks whose evidence has drifted move to `INVALIDATED`, and their pending approvals, plus pending review-record approvals whose candidates changed, are marked stale.

## Evidence references

| Ref | Resolves against | Attachable when |
| --- | --- | --- |
| `knowledge:<id>` | Project OS `knowledge_items` | `PROMOTED` and within freshness (`fetched_at` + the knowledge freshness window) |
| `evidence:<id>` | N4 kernel evidence | in scope and within `freshness_seconds` |
| `decision:<id>` | N4 decisions | the decision records at least two alternatives and a selected option |
| `genome:<version_id>` | VNEXUS genome versions in this project | `APPROVED`. A newer approved version makes it `GENOME_SUPERSEDED` |
| `artifact:<id>@v<n>` | N4 artifacts | `n` is the head version, and the stored bytes read back with the recorded SHA-256 |

Every resolution reports an origin: `CUSTOMER_SOURCED`, `PUBLIC_SOURCE`, `INTERNAL_RECORD`, `INFERENCE` or `SYNTHETIC`. Sources with `synthetic:`, `fixture:` or `synthetic://` prefixes are synthetic. Synthetic evidence can satisfy a gate in a rehearsal, but the plan and gate views then show `synthetic_evidence_present` / `synthetic_only`. It is never client proof.

## Stage gates

The five gates, `01_DISCOVERY` through `05_GROWTH`, are evaluated from task state:

- **NOT_ASSESSED**: any task in the gate is still unassessed.
- **BLOCKED**: a required or conditional task is not verified.
- **NEEDS_HUMAN**: everything required is verified. A person still has to decide.
- **APPROVAL_PENDING**, **PASSED** and **STALE**: overlaid from the gate's approval.

A gate approval is opened with subject `agency-gate:{plan}:{gate}` and bound to the gate's `evaluation_hash`. If the evaluation changes after approval, the gate is `STALE`. Gates pass only in order (`PREDECESSOR_GATE_NOT_PASSED`). An optional channel that nobody chose (`NOT_APPLICABLE`) never blocks a gate.

## Assurance records

Meaning, Mutation, Probe, Renewal and Review are **findings, not authority**. Each record is stored as an immutable Project OS artifact:

- type `qa_report`;
- subtype `assurance.<kind>`;
- key `assurance/<kind>/<record_id>`.

Each record is sealed with a `record_hash`. Every read re-verifies its integrity: the bytes hash, version 1 and the record hash. A correction supersedes the earlier record instead of editing it, and superseding anything but the current head is `STALE_SUPERSEDE`.

| Record | What it proves | What it never does |
| --- | --- | --- |
| Meaning | Qualifiers found, exclusions absent, output locations read back. The semantic score is advisory only. | Count a score as coverage |
| Mutation | One perturbation of an in-memory variant. Expected versus observed findings; misses (false negatives) and unexpected findings (false positives) are both reported, with a confusion matrix. | Write the variant |
| Probe | A dependency change inside a `graph_snapshot` sandbox: declared versus observed effects plus a blast-radius certificate. | Change the canonical graph (`canonical_unchanged` is checked) |
| Renewal | Trigger evidence, the affected decision and its retained alternatives, with a proposal. | Replace the decision |
| Review | Exact subject hashes, a dependency snapshot and full-byte access to every candidate. It can open an approval for plain artifact candidates. Bound to a sealed delivery release candidate, it re-checks the seal and links the run's own approval (below). | Approve or release. A plain candidate stays pending until `/approvals/{id}/decide`; a sealed release candidate is decided only by its run's approval, and released only by delivery |

Mutation detectors: `CLAIM_CHANGED`, `LOCALE_CHANGED`, `A11Y_ALT_MISSING`, `REFS_REQUIRED`, `APPROVAL_SUBJECT_MISMATCH`, `ARTIFACT_STALE` and `REF_NOT_FOUND`.

`CLAIM_CHANGED` compares two claim surfaces of the base and the variant:

- the Project OS sentence extractor (sentences of 6–60 words);
- the framework's claim detector (`claims.py`).

The detector finds a claim by its *signals*, not its length. It reads every markup segment and sentence, so "Free", "Save 30%" or "Ships in 2 days." on its own is seen. The signals are price, quantity, comparison, absolutes, environmental terms, subjective wording and factual verbs. Comparison is Unicode- and punctuation-normalised (NFKC, trademark marks dropped, curly quotes straightened, trailing `.`/`!` ignored). A `*` or `?` is kept, because it changes the claim. Navigation text such as "Learn more" carries no signal and is not a claim.

Remaining blind spot, measured and not hidden: a claim with no signal word (for example "Packed by hand." → "Packed by machine.") is still missed. The mutation fixtures record it as a false negative in the confusion matrix. Precision and recall with a zero denominator are `NOT_MEASURED`.

### Claims: detection, substantiation, policy, decision

A Meaning record's body carries a `claims` inventory for its outputs. The four stages stay separate:

1. **Detection.** Each claim gets its classes:
   - substance: `PRICE`, `QUANTIFIED`, `COMPARATIVE`, `ABSOLUTE`, `ENVIRONMENTAL`, `SUBJECTIVE`, `FACTUAL`;
   - modifiers: `QUALIFIED` with its qualifiers, `THIRD_PARTY_QUOTE`;
   - an `ambiguous` flag for questions.
2. **Substantiation need.** Objective classes need evidence; puffery is `REVIEW_AS_OPINION`. A quotation repeats a claim and never substantiates it.
3. **Substantiation state.** Evidence is linked only by a person, through `claim_evidence: [{claim, evidence_refs}]`:
   - each ref must resolve reviewed and fresh in this project, or the request is refused with `REF_REJECTED`;
   - a link to a claim not found in the outputs is refused with `UNKNOWN_CLAIM`;
   - a linked claim is `EVIDENCE_LINKED_UNVERIFIED`, never "verified", because a person still judges whether the evidence supports it;
   - an unlinked objective claim is `UNSUBSTANTIATED`.
4. **Policy and decision.** Every claim is routed to `HUMAN_REVIEW`. Nothing is rejected or approved by the detector, and there is no length-based exemption.

### Review bound to a sealed release candidate

`POST …/assurance/review` with `release_candidate_ref: "release-candidate:<run_id>"` binds the candidate that `agency/delivery` sealed for that run. The read path is `candidates.inspect`; it never writes.

**Who may bind.** The reviewer must hold an approver role (`REVIEWER_ROLE_REQUIRED`). They must not be the run's initiator (`REVIEWER_IS_INITIATOR`).

**Scope.** The run must be in the plan's tenant and project. A run anywhere else is indistinguishable from a missing one (`REF_NOT_FOUND`).

**Subjects.** The subjects are exactly the manifest's artifacts at their sealed versions. Explicit `candidate_refs` must match them (`CANDIDATE_REFS_MISMATCH`).

**Use-time checks**, the same facts the release gate re-checks:

- the manifest recomputes to the sealed `candidate_manifest_hash` and to the sealed approval subject;
- the artifacts are still the sealed heads;
- the dependency snapshot is unchanged;
- every artifact hash recomputes from the stored run payload it was bound over. This is the binding layer's own spec and subject hash, not a second scheme, so this is the full-candidate inspection;
- in enforce mode, the run's approval is bound to the sealed subject.

**Blocking findings.** Any failure is recorded as a blocking finding and the record is `BLOCKED`:
`CANDIDATE_NOT_SEALED`, `CANDIDATE_INVALID`, `CANDIDATE_HASH_MISMATCH`, `ARTIFACTS_CHANGED`, `DEPENDENCIES_CHANGED`, `PAYLOAD_UNVERIFIED`, `APPROVAL_SUBJECT_MISMATCH`.

**Decision.** The record links `native_approval_ref`, the run's approval. `request_decision` is refused (`RELEASE_DECISION_OWNED_BY_DELIVERY`), so no second release approval can exist.

**Read-back.** `GET …/assurance/{id}` re-inspects the candidate. `subject_now.subject_current` turns false the moment the candidate drifts.

**Supersession.** A correction's record id is derived from the record it supersedes. Two concurrent corrections of one head therefore collide on the artifact key, and exactly one wins (`STALE_SUPERSEDE`).

## KPIs

`metrics.py` defines 13 KPIs, each with its own inputs:

- **Awareness:** qualified reach.
- **Acquisition:** qualified leads, conversion rate, cost per lead.
- **Sales:** new-customer revenue, CAC, CAC payback.
- **Brand:** aided awareness.
- **Retention:** cohort survival, monthly churn.
- **Profitability:** contribution margin, LTV.
- **Delivery:** approval rework rate.

Values come only from two sources:

- N4 evidence rows of type `measurement`. Measurements are recorded through `POST …/measurements`, and only an approver can attest a measurement as verified.
- The plan's own audit events, for approval rework.

A missing input or a zero denominator gives `NOT_MEASURED`. Inputs from different windows are flagged. Synthetic inputs are labelled `SYNTHETIC`. There are no default benchmarks and no targets.

## Readiness levels

The plan view never collapses these into one flag:

| Level | Here |
| --- | --- |
| SPECIFIED | The catalog defines the task |
| IMPLEMENTED | Code exists for the owning capability (see the binding's `capability`) |
| TESTED | Covered by the test suites below |
| VERIFIED | A task verified by a second person against re-resolved evidence |
| APPROVAL_READY | `NEEDS_HUMAN` on a task or gate |
| RELEASE_ELIGIBLE | Always `false` in this ledger. Release eligibility is owned by `agency/delivery` (`ReleaseCandidateManifest` / `evaluate_release_predicate`) |
| RELEASED / PRODUCTION_ACTIVE | Not claimed. Activation follows `docs/production-activation.md` |

## API

All routes require authentication and are tenant- and project-scoped. A plan in another tenant, or in a project outside the principal's scope, is 404 `PLAN_NOT_FOUND`. Writes need `Idempotency-Key`. Errors use the AMC envelope `{detail, error: {code, message, status, details?}}`.

| Method | Path |
| --- | --- |
| GET | `/catalog`, `/catalog/tasks`, `/metrics/definitions` |
| POST, GET | `/plans` (POST is idempotent per project + catalog version) |
| GET | `/plans/{id}`, `/plans/{id}/tasks`, `/plans/{id}/tasks/{task}`, `/plans/{id}/gates`, `/plans/{id}/audit`, `/plans/{id}/metrics` |
| POST | `/plans/{id}/applicability`, `/plans/{id}/revalidate`, `/plans/{id}/decisions`, `/plans/{id}/measurements` |
| POST | `/plans/{id}/tasks/{task}/transition`, `…/unblock`, `…/verify`, `…/request-approval`, `…/settle` |
| PUT | `/plans/{id}/tasks/{task}/refs` |
| POST | `/plans/{id}/gates/{gate}/request-approval` |
| GET, POST | `/plans/{id}/assurance`, `/plans/{id}/assurance/{record_id}`, `/plans/{id}/assurance/{kind}` |

Request bodies are strict (`extra="forbid"`). Fields such as `verified_by`, `approval_ref`, `verifier` or `decision` are refused with 422, never ignored.

## UI

`/framework`, also the **Operating Framework** section of `/agency`:

- **Instantiate:** choose an engagement type and scope. The form makes no completion claims.
- **Overview:** a plan summary with the honest counts and the synthetic-evidence banner.
- **Tabs:** Tasks, Gates, KPIs, Assurance and Audit, switchable with the arrow keys.
- **Tasks tab:**
  - a module navigator grouped by discipline;
  - a task list with state, applicability and search filters, plus bulk applicability;
  - a task inspector with applicability, the allowed moves, refs, server checks, approval status, dependencies and history.
- **States:** empty, loading, error and phone-width layouts are handled.
- **Refusals:** the server's message is shown as an alert, and the task state is left unchanged.

## Persistence, migration and rollback

The migration is additive: two new tables, and no existing table is altered.

- `agency_framework_plans`: unique on (`project_id`, `catalog_version`).
- `agency_task_instances`: a CAS `version` column, with CHECK constraints on state and applicability, and a project index.

On PostgreSQL both tables live in `amc.*`, and access is revoked from `anon` and `authenticated`.

Rollback:

1. Remove `app.include_router(agency_framework.router, …)` from `app/main.py`, or revert the commit. Nothing else imports the package.
2. Drop the tables (PostgreSQL shown; SQLite is the same without the `amc.` prefix):
   ```sql
   DROP TABLE IF EXISTS amc.agency_task_instances;
   DROP TABLE IF EXISTS amc.agency_framework_plans;
   ```
3. Approvals, project events, artifacts, knowledge and kernel evidence written while the framework was on are ordinary rows of their owners. They stay valid and need no cleanup.

Verified on PostgreSQL 16: apply all migrations (86 `amc` tables), roll back (84), re-apply (86), re-run (a no-op).

## Tests

| Suite | Covers |
| --- | --- |
| `test_agency_framework.py` | Seed validation and tamper refusal, bindings against N3, instantiation, idempotency, applicability and `NOT_MEASURED`, gated transitions, separation of duties, stale version, concurrent writers (exactly one winner), crash between row and event (no partial commit; retry recovers), injected-authority refusal, stale evidence, invalidation, gates in order with staleness, tenant isolation, no external effects |
| `test_agency_framework_assurance.py` | All five records, negative cases, the confusion matrix, tamper detection, tenant isolation, read-back in a fresh process |
| `test_agency_framework_slice.py` | The connected B2C slice: discovery evidence → positioning decision → VNEXUS approved genome → identity (VNEXUS production on local Chromium, or reported `NOT_RUN`) → website → five records → an unapproved review candidate; then genome supersession invalidates the positioning task and drops gate 02 to `BLOCKED` |
| `test_agency_framework_archetypes.py` | Fictional B2C goods, B2B services and SaaS engagements end to end, with persistence checked in a fresh process |
| `test_agency_framework_contracts.py` | Enum parity with Zod, the recorded fixture, `Idempotency-Key` on every write |
| `packages/shared/tests/agencyFramework.test.ts`, `apps/web/tests/framework-view.test.ts` | Zod fixture parity, transition-table parity with Python, `NOT_MEASURED` display |
| `test_agency_framework_release_candidate.py` | Review ↔ sealed candidate:<br>• valid binding and read-back, then release by the run's own approval;<br>• missing, foreign-project and foreign-tenant runs;<br>• operator and initiator refused;<br>• moved artifacts and a new dependency edge;<br>• a tampered manifest and a forged approval subject;<br>• an unsealed run and an absent approval;<br>• a refused second decision and refused subject changes;<br>• idempotent replay, concurrent supersedes with one winner, an interrupted write |
| `test_agency_framework_claims.py` | Short-claim detection:<br>• the seven supplied short claims;<br>• long equivalents, qualifiers and disclaimers, quotations;<br>• Unicode and punctuation, questions, navigation text;<br>• markup segments;<br>• mutation detection with no false positives;<br>• Meaning inventory with person-linked evidence, unknown claims and fabricated refs refused |
| `apps/web/e2e/framework.spec.ts` | Browser test on the live stack: catalog → modules → applicability → refused review and refs → gates → KPIs → assurance keyboard tabs → audit → reload persistence → phone width. It also runs the accessibility checks below |

All data in these tests is fictional and labelled synthetic. No result here is a client result.

## Accessibility

The target is WCAG 2.2 AA. `apps/web/e2e/framework.spec.ts` checks it in two ways.

**axe scans** (`@axe-core/playwright` 4.13.0, tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`; no rule disabled) of every state:

- the instantiation form;
- the dashboard;
- the task inspector, with and without an error;
- the Gates, KPIs and Audit tabs;
- each assurance kind, empty and with a record;
- a record's detail view;
- a refused candidate review;
- the loading state;
- the error state;
- phone width (390 px).

**Checks axe cannot make:**

- keyboard-only task opening;
- a visible focus indicator;
- focus returning to the opening task when the inspector closes (2.4.3);
- errors announced as `role="alert"`;
- the loading state announced as `role="status"`;
- no keyframe or movement animation under `prefers-reduced-motion` (2.3.3);
- retrying from the keyboard after an error;
- no horizontal overflow at 390 px (1.4.10).

**Defects found and fixed by these tests:**

- focus was lost when the inspector closed;
- the loading skeleton kept pulsing under reduced motion and had no live role;
- the shell's Search button had no accessible name at phone width (4.1.2).

**Not tested automatically. These need a person with assistive technology:**

- screen-reader reading order and verbosity (NVDA, VoiceOver);
- 1.4.4 resize to 200 %;
- 1.4.12 text spacing;
- 2.5.8 target size, which axe does not measure fully;
- 1.4.11 non-text contrast of focus rings in both themes;
- 3.3 error suggestions for the JSON record editor, which accepts free JSON;
- cognitive load of the 295-task view.

**Dialog containment is not applicable.** The framework view has no dialogs: the inspector is an in-page panel. Passing these tests does not prove conformance.

## Known gaps

- Five modules have no N3 role of their own (AGM-11, 16, 17, 22, 23). They bind to the nearest producer, and the gap is shown.
- The framework never seals or releases: a Review can bind delivery's sealed candidate (above), and release eligibility stays with `agency/delivery`. The browser suite cannot show a bound candidate, because CI's stack runs without `AMC_CONTRACT_MODE=enforce` and without a model key. That rendering is covered by the backend tests and the Zod fixture instead.
- No external effect is executed for any module. Modules with publish, spend, send or outreach effects stay planning-only or dry-run, as their existing owners are.
- Many catalog tasks are `HUMAN_ONLY`: the repository records and verifies the evidence, but a person does the work.
- `CLAIM_CHANGED` misses claims that carry no signal word (see Assurance records). The claim lexicon is English-only.
- Ownership for the five modules without an N3 role is proposed, not activated: see `docs/role-ownership-decisions.md`. Rollout and rollback for the hosting setup are in `docs/agency-framework-rollout.md`.
