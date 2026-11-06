# Unified Venture Studio Directive — AMCOS

**Status:** repository integration specification; not a claim that every capability below is implemented.  
**Target:** `eyeszik/agent-mission-control-os`  
**Authority:** repository code, schemas, tests and runtime evidence outrank this directive.  
**Integration rule:** reuse canonical AMCOS owners; do not create parallel orchestrators, stores, approval systems, schedulers, token compilers, artifact registries or provider gateways.

## 1. Mission

Evolve AMCOS into a governed, multi-tenant venture and creative-studio operating system that can take a request from intake to a verified workflow and, only when explicitly selected and authorized, prepare a branded business and its commercial delivery channels.

The system must first establish what the repository can actually execute. It must not describe a proposed agent, provider, integration, workflow, or commercial outcome as available merely because it appears in a prompt or catalog.

Primary lifecycle:

`REQUEST → INTAKE → PROJECT → DISCOVERY → STRATEGY → WORKFLOW_SPEC → BUILD → SANDBOX_EXECUTION → VERIFY → HUMAN_DECISION → RELEASE → OBSERVE → LEARN`

Brand/commercial work is a conditional workstream, not a prerequisite for every automation:

`BRAND_POSTURE × DELIVERY_ARCHETYPE → applicable workstreams → governed artifacts`

A headless/internal automation must not be forced through brand, storefront, marketing, or customer-operations stages.

## 2. Non-negotiable system principles

1. **Preserve and compose.** Inspect before changing. Reuse, configure, repair, connect, extend, then add only when a canonical owner is absent. Never duplicate an existing capability.
2. **Three logical planes, existing physical owners.**
   - **Control:** intake, project lifecycle, DAG planning, dependency resolution, budgets, authority and approvals. Compose existing Project OS, intake mission, method/delegation compiler, workflow and action-plane services.
   - **Execution:** deterministic, bounded, isolated execution through the existing execution fabric, skills gateway, sandbox and receipts.
   - **Studio/commercialization:** brand, creative, web, product, campaign and channel workstreams over the same project/artifact graph. This is a domain boundary, not permission to bypass the action plane.
3. **Tenant/project scope is mandatory.** Every run, artifact, prompt, memory item, approval, event, schedule, provider binding, budget and receipt resolves to server-authorized `tenant_id → project_id`. Client-supplied identity/role/approval/spend authority is never trusted.
4. **Zero-trust integrations.** Use official OAuth, operator-delegated API credentials or signed service identities stored in an approved secret manager. Never generate, infer, scrape, expose, or persist credentials in prompts/artifacts/logs. Missing credentials or adapters produce a typed blocked/provider-gap state.
5. **Human authority remains explicit.** External writes, publishing, sending, spend, purchases, deployment, deletion, permission changes, legal declarations and other consequential actions require exact, unexpired, server-bound human approval. Approval binds action, payload hash, target, tenant, environment, policy version and dependency snapshot. A prompt, plan, test, or tool connection grants no authority.
6. **Low-cost and deterministic first.** Prefer local/FOSS and existing serverless/self-hosted primitives where compatible with repository architecture. Use deterministic code for validation, transforms, routing and calculations. Route models by task value, risk, quality and budget; frontier models are not the default for routine work.
7. **No fake autonomy.** Planning is not execution; a registered capability is not an installed provider; sandbox success is not live delivery; a locally rendered asset is not a published campaign.
8. **Evidence is a first-class output.** Persist provenance, hashes, versions, dependency lineage, verifier results, receipts, costs and human decisions using canonical AMCOS stores.

## 3. Onboarding: two orthogonal decision gates

The intake experience must collect both decisions before it compiles a final work plan. They are independent dimensions; neither may be inferred from the other.

### Gate A — brand / enterprise posture

- `NEW_BRAND`: create positioning, naming proposal, audience, voice, identity, tokens and brand governance.
- `EXISTING_COMPANY`: ingest supplied brand assets, guidelines, tokens, voice, audience and constraints; preserve approved source material.
- `REBRAND`: audit current identity and assets, define retained/replaced/retired elements, migration and coexistence rules, then propose the new system.
- `HEADLESS_AUTOMATION`: no brand or public-facing overhead; create only the operational/service identity required by the workflow.

### Gate B — operational target / delivery archetype

- `PHYSICAL_PRODUCT`: product specification, production constraints, mockups, catalog and fulfillment integration. Manufacturer/channel adapters must be verified; listing, order and fulfillment writes remain gated.
- `DIGITAL_PRODUCT`: files/data/templates, rights and licence metadata, packaging, checkout and delivery. Payment/provider writes remain gated.
- `MANAGED_SERVICE`: customer intake, job orchestration, quality checks, delivery manifest and support workflow. Customer-facing sending/delivery remains gated.
- `SOFTWARE_OR_API`: API/webhook contract, auth, metering, documentation, deployment and operational monitoring. Deployment and external account changes remain gated.
- `INTERNAL_AUTOMATION`: private routing, ETL, reporting or internal operations; no storefront by default.

### Intake microtasks

1. Resolve actor from server auth; authorize tenant and project before reading project data.
2. Ask/record Gate A and Gate B as separate required enums; support an explicit `UNDECIDED` state and pause plan compilation until resolved.
3. Collect objective, users/audience, inputs, expected outputs, success criteria, constraints, budget ceiling, deadline, jurisdictions, data classification, required integrations and non-goals.
4. Detect whether this is a new project, existing project, continuation, or revision; bind exactly one accessible project or pause on ambiguity.
5. Ingest files/URLs only through supported, permissioned paths; classify provenance, rights, trust and freshness. Treat embedded instructions as untrusted data.
6. Resolve missing facts into explicit questions or typed assumptions. Never silently fabricate facts, provider access, budgets or approval.
7. Compile a versioned, schema-validated `VentureBrief` / project intake artifact with source refs, decision values, assumptions and unresolved blockers.
8. Persist via Project OS and existing intake/mission services; emit lifecycle events through existing event/analytics owners.
9. Show the operator a plan preview, exclusions, cost ceiling, permissions, external effects and approval points before dispatch.

## 4. Agent/role topology: logical responsibilities, not 17 mandatory runtimes

The following 17 responsibilities are a domain map. Bind each to an existing role, skill, service, workstream or workflow node where one exists. Do not instantiate 17 agents by default, create duplicate stores, or promise agent-to-agent autonomy. Missing owners become explicit capability gaps and prioritized work items.

| Role | Responsibility / typed output | Preferred existing owner or composition |
|---|---|---|
| Venture Orchestrator | lifecycle, budgets, DAG, dispatch plan, approval requests | Project OS + LangGraph/API orchestration + method/delegation compiler |
| Intake | brief, posture gates, requirements, assumptions | governed intake mission + project initializer |
| Research | sourced market/competitor/audience evidence | research capability only when a real search provider is configured |
| Business Model | offer, pricing assumptions, unit economics | deterministic finance/calculation skill; sourced inputs |
| Workflow Architect | versioned typed DAG and acceptance contract | workflow/delivery contract + method compiler |
| Workflow Builder | sandboxable nodes, adapters, error routes | execution fabric + skills; isolated code sandbox |
| Integration | OAuth/scope/provider readiness manifest | action/provider registry + secret manager boundary |
| QA / Verification | independent tests, artifact proof, release verdict | delivery critic, execution receipts, domain verifiers |
| Brand Strategist | brand strategy and approved genome | VNEXUS / Creative Foundry / Project OS |
| Creative Production | validated design/media assets | Foundry, AVIC, visual engine, UI/UX compiler |
| Product | product specs, catalog records and variants | project artifacts/workstreams; add only if no canonical owner |
| Commerce | store, payment and fulfillment adapter requests | ACE action plane; provider gaps stay blocked |
| Marketing | content plans, campaign artifacts and measurement spec | Project OS content calendar, campaign/workstream modules |
| Customer Operations | support, knowledge and service workflow | project memory/knowledge + approved CRM/customer adapters |
| Finance | budgets, costs, margin and ledger evidence | spend ledger, cost router and deterministic calculations |
| Security & Compliance | threat, policy, tenant, rights and secret review | trust kernel, N2/N3, ACE policy and existing security checks |
| Growth & Portfolio | measured performance and optimization proposals | Project OS portfolio/analytics; no invented metrics |

Each dispatched work order must specify: role/owner, objective, tenant/project, typed input refs, output schema, dependency hashes, permitted skills/scopes, side-effect class, budget/time limits, retry policy, verifier IDs, expected evidence and terminal states.

## 5. End-to-end lifecycle and microtask decomposition

### A. Discover and plan
1. Read repository instructions and relevant architecture docs.
2. Inspect current project, artifacts, approvals, providers, workstreams and previous decisions.
3. Build a requirement-to-capability map: `REQUIREMENT → OWNER → STATUS → GAP → DEPENDENCY → TEST → EVIDENCE`.
4. Select only applicable workstreams from the two onboarding gates.
5. Build a dependency DAG with stable IDs, typed contracts, deterministic ordering and explicit blocked nodes.
6. Estimate model/API/compute/storage costs and enforce per-action, project, tenant, daily and monthly ceilings.
7. Pin workflow version, policy version, schemas, model/provider profile and dependency snapshot to the run.
8. Produce a reviewable plan and delivery contract; do not dispatch external effects.

### B. Research and strategy
1. Define research questions, target geography/market and freshness requirements.
2. Query only installed, authorized providers; preserve URLs, timestamps, source snippets and retrieval provenance.
3. Separate sourced facts, operator claims, assumptions and model inferences.
4. Analyze audience, competitors, demand, differentiation, constraints and uncertainty.
5. Produce evidence-linked strategy and offer artifacts.
6. Calculate costs/margins from explicit inputs; show formulas and sensitivity ranges.
7. Mark unsupported market sizing, demand, legal or financial claims `NOT_MEASURED` / `UNKNOWN`.

### C. Brand and creative (only when applicable)
1. For existing brands, ingest and hash source guidelines/assets; record rights and authority.
2. For rebrands, generate an asset inventory and keep/modify/retire mapping before proposing changes.
3. Compile a versioned brand genome: positioning, audience, voice, naming, identity constraints, tokens and canonical mark.
4. Require review of material brand decisions; approved genome versions are immutable.
5. Convert deliverable requirements into typed asset specs with exact dimensions, formats, text, accessibility and rights constraints.
6. Route local deterministic rendering first; use a hosted model only through an enabled, reviewed provider adapter.
7. Persist every output as a Project OS artifact with source prompt, provider/model, parameters, prompt hash, asset hash, licence/provenance and dependency refs where available.
8. Independently inspect rendered bytes, dimensions, text, contrast, layout, format and brand invariants.
9. Permit bounded correction/revision; re-run affected verifiers and invalidate descendants when dependencies change.
10. Human selects/approves final direction and release candidate.

### D. Workflow specification and build
1. Convert goals into a versioned DAG/WorkflowSpec with node contracts, preconditions, postconditions and typed error routes.
2. Define idempotency keys, retry ceilings, timeouts, concurrency, rate limits, compensation/reconciliation and cancellation behavior.
3. Classify each node READ / LOCAL_WRITE / EXTERNAL_WRITE / SPEND / PUBLISH / SEND / DEPLOY / DESTRUCTIVE.
4. Resolve every tool to a registered capability with exact scopes and schemas; unknown tools fail closed.
5. Build only deterministic, bounded handlers; untrusted generated code runs in a network-isolated, resource-limited sandbox.
6. Generate fixtures, mocks and contract tests; mocks must never be reported as live provider evidence.
7. Store workflow source, lock/dependency metadata, build provenance and hashes as versioned project artifacts.

### E. Execute and verify
1. Recompute plan/dependency hashes before execution; refuse stale plans.
2. Check server authority, role, project scope, provider availability, policy, budget and sandbox before each node.
3. Reserve idempotency and write-ahead intent before any mutation; reconcile UNKNOWN outcomes by read-back before retry.
4. Run eligible independent cells concurrently only when resource and mutation targets do not collide.
5. Record truthful per-node states, logs, cost, duration, output refs and failure fingerprints.
6. Validate output contracts and read back persisted bytes independently.
7. Run unit, integration, end-to-end, accessibility, security, tenant-isolation, reliability and domain checks as applicable.
8. Produce proof manifest and delivery-contract verdict. LLM judgment alone cannot produce deterministic PASS.
9. Quarantine injection, rights uncertainty, unsupported claims, missing provider evidence and stale artifacts.

### F. Human decision and release
1. Seal release candidate from exact artifact versions, dependency hashes, checks, target and policy.
2. Present a human-readable diff, evidence, known limitations, cost, target and side effects.
3. Require authorized reviewer and separation of duties where policy requires.
4. Bind approval to exact candidate hash and expiry; any mutation makes approval stale.
5. Release only through the canonical approval/action gateway.
6. Never equate approval with successful external execution; require dispatch receipt and independent read-back.
7. If live adapter is absent or LIVE is disabled, stop at a truthful blocked/dry-run state.

### G. Observe, report and learn
1. Record operational and lifecycle events using canonical analytics/event stores.
2. Distinguish measured outcomes from estimates and user-reported outcomes.
3. Track cost per run/deliverable, cycle time, human review time, failure/rework and quality evidence where actually measured.
4. Generate final manifest, handoff instructions, support/maintenance needs and project closure record.
5. Store lessons as quarantined learning signals; promote only through existing governance.
6. Do not optimize for vanity metrics or infer commercial success from asset production.

## 6. Repository integration map and gap controls

The inspected repository already documents substantial canonical infrastructure. These are reuse targets, not permission to rebuild them:

| Concern | Canonical repository owner (verify current code before editing) |
|---|---|
| Tenant/project state, artifact versions, lineage, memory, workspace | Project OS / N4 persistence |
| Intake and release flow | `agency/intake`, existing approvals |
| Planning and delegation | method-routing/delegation compiler |
| Deterministic execution | execution fabric, N3 skills dispatcher, sandbox |
| Exact approvals and external actions | ACE v12 action plane; LIVE currently documented disabled |
| Brand system and local creative production | VNEXUS ACE, Creative Foundry, AVIC, visual engine |
| Design tokens and UI specs | single DTCG compiler / UI-UX compiler |
| Website build and browser QA | UCPO |
| Content calendar and scheduling | Project OS content operations / single scheduler |
| Workflow release contract | unified delivery contract and critic |
| Mission execution | Mission Council; mock model default unless real models enabled |
| Analytics and portfolio | first-party analytics / Project OS portfolio |

**Known integration questions to resolve against current source and tests before implementation:**

- Does intake persist both posture enums as required, versioned fields and enforce the two gates before planning? If not, add to the existing intake contract/UI/API with backward-compatible defaults and migration.
- Can every delivery archetype map to a canonical workstream and typed acceptance contract? Add only missing mappings; do not create a parallel workflow engine.
- Are all 17 responsibilities mapped to real owners, with unsupported roles shown as gaps rather than fake agents?
- Does one project support multiple brand/product/workflow workstreams without violating tenant/project isolation?
- Are brand genome, assets, website, workflow specs and commercial records linked by artifact dependencies and invalidation?
- Are prompt/provider/model provenance and exact media generation parameters consistently captured? Extend artifact metadata only where absent.
- Are provider capabilities discoverable from installed adapters and credentials without exposing secrets? Registry status must distinguish DEFINED, INSTALLED, CONFIGURED, AVAILABLE, VERIFIED and LIVE_GATED.
- Do all external actions route through ACE v12, with no legacy bypass path? LIVE remains disabled until a separately reviewed provider, security, legal and operational activation.
- Are cost ceilings enforced before model calls, rendering, API calls and spend reservations?
- Are cancellation, retries, crash recovery, UNKNOWN reconciliation and partial failure covered across long-running multi-stage projects?
- Are end-to-end proofs and lifecycle analytics sufficient to identify who/what produced each deliverable and why it passed?
- Are user-facing screens clear about dry-run, local-only, provider-gap, needs-human and verified states?
- Do tests cover both onboarding axes, all archetypes, legacy project compatibility, tenant boundaries, approval staleness, provider absence, idempotent replay and failure recovery?

## 7. Required implementation work packages

Execute in dependency order; split further into small PR-sized tasks only after inspecting actual code. No task may exceed the established repository/runtime execution limits.

**WP0 — baseline and evidence**
- Read `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, relevant docs and local instructions.
- Inventory routes, UI, schemas, migrations, workflow nodes, providers, tests and CI.
- Run baseline checks where execution access exists; record command, environment and result.
- Build the requirement/capability/owner/gap matrix and identify protected behavior.

**WP1 — contract design**
- Inspect current VentureBrief/intake/project schemas and frontend onboarding.
- Define backward-compatible enums for both gates and typed archetype-specific requirements.
- Define `VentureBrief`, `WorkstreamSelection`, `WorkflowSpec`, `IntegrationManifest`, `VerificationReport` and `DeliveryContract` only where canonical equivalents do not exist.
- Add schema versions, validation, migration/compatibility strategy and shared TS/Python contract fixtures.

**WP2 — onboarding integration**
- Extend existing intake UI/API; do not add a second entry point.
- Enforce separate posture and archetype decisions.
- Add conditional questions and workstream selection.
- Add project binding, assumptions, unresolved-question and plan-preview states.
- Add accessibility and browser E2E tests.

**WP3 — planner/workstream mapping**
- Map archetypes to existing project workstreams and agent/role owners.
- Compile typed DAGs with dependency, authority, budget, timeout and idempotency metadata.
- Surface missing providers and unsupported nodes before dispatch.
- Pin workflow and policy versions for replay compatibility.

**WP4 — brand/creative continuity**
- Reuse approved VNEXUS genome, Foundry, AVIC, UI-UX and UCPO owners.
- Verify lineage from brief → genome → asset spec → output → independent proof.
- Add missing provenance metadata and invalidation tests only after confirming absence.
- Keep hosted media generation disabled until adapter and review requirements pass.

**WP5 — execution/integration safety**
- Route all work through execution fabric/skills and all external effects through ACE.
- Verify sandbox isolation, least privilege, secret handling and provider readiness.
- Add provider contracts/mocks, but label mock evidence and never enable LIVE by implication.
- Add crash, replay, collision, timeout, budget and UNKNOWN reconciliation tests.

**WP6 — verification/release**
- Extend delivery contracts with archetype-specific acceptance criteria.
- Add independent domain verifiers and proof manifests.
- Bind approvals to exact release candidates and test stale approval rejection.
- Confirm release receipts/read-back and disabled-live behavior.

**WP7 — economics/observability**
- Capture measured model/API/compute/storage cost and operator review time where available.
- Add cost ceilings and deterministic scenario calculators with explicit assumptions.
- Connect lifecycle events to existing analytics and portfolio read models.
- Do not publish savings claims without real baseline and measured comparison.

**WP8 — documentation and operator handoff**
- Update architecture, onboarding, runbooks, capability/provider matrix and user guide.
- Document each archetype, current status, blockers, approvals and safe local test path.
- Provide an end-to-end example clearly labelled VERIFIED, IMPLEMENTED_UNVERIFIED, DOCUMENTED or HYPOTHETICAL.

## 8. Status vocabulary and proof requirements

Use these labels consistently:

- `VERIFIED`: behavior executed successfully and independently observed; cite command/test/receipt.
- `TESTED`: named automated test passed; not necessarily production behavior.
- `IMPLEMENTED`: reachable code exists; execution not proven.
- `DOCUMENTED`: documentation only.
- `PARTIAL`: incomplete implementation.
- `PROPOSED`: this directive or roadmap only.
- `INFERRED`: supported interpretation, not directly established.
- `MISSING`: no implementation found after scoped inspection.
- `UNKNOWN`: insufficient evidence.
- `BLOCKED`: policy, authority, provider, dependency or environment prevents execution.
- `LIVE_GATED`: external effect is intentionally unavailable pending reviewed activation.

For every requirement preserve traceability:
`REQ-ID ↔ schema/API/UI ↔ owner/module ↔ capability ↔ gap/change ↔ test ↔ evidence`.

A documentation statement, registry entry, mocked test, dry-run, plan, generated prompt or successful local render cannot be promoted to live external execution evidence.

## 9. Validation and acceptance

A change is acceptable only when applicable criteria pass:

1. Existing project/run/artifact/API contracts remain backward compatible or are explicitly versioned/migrated.
2. Both onboarding decisions are independent, persisted, validated and required before plan compilation.
3. Each archetype selects only relevant workstreams; headless/internal flows do not create brand/storefront work.
4. All work orders are typed, tenant/project scoped, budgeted, version-pinned and traceable.
5. Unsupported agents/providers are visibly blocked; no capability is fabricated.
6. All external effects remain fail-closed and require exact approval through the canonical action plane.
7. Idempotency, concurrency, retry, cancellation, replay and UNKNOWN reconciliation are deterministic.
8. Artifacts carry provenance, hashes, lineage, independent verification and approval binding.
9. Tenant isolation, authorization, secrets, prompt injection, rights, accessibility and sandbox controls are tested.
10. Unit, contract, integration, E2E, type, lint, build, migration and security checks relevant to changed surfaces pass.
11. Documentation, provider matrix, runbooks and UI status language match actual code.
12. Baseline failures are separated from introduced failures; no test is weakened or removed to obtain a pass.

## 10. Economics and agency capability claims

Evaluate a representative brand launch and a headless automation separately. Compare traditional agency, freelancers, internal team and AMCOS-assisted operation only with dated, sourced benchmarks and explicit scope. Include labor, revisions, software, models, hosting, storage, external providers and human oversight. Report conservative/moderate/high-automation scenarios, formulas, sensitivity and confidence.

Separate:
- potential savings from measured savings;
- asset generation from commercial outcome;
- project throughput from quality equivalence;
- local/sandbox operation from live channel execution.

Never claim AMCOS replaces a full agency or achieves a revenue/margin outcome without evidence.

## 11. Execution protocol for coding agents

`INGEST → BASELINE → MAP → DIAGNOSE → PLAN → IMPLEMENT → TEST → REPAIR → VERIFY → HANDOFF`

- Inspect actual source before proposing file edits. Treat this document as a specification, not a command to implement all future work at once.
- Preserve working behavior; use additive migrations/adapters and feature flags where appropriate.
- Ask only blocking questions. Otherwise record assumptions and proceed within authorized scope.
- Parallelize independent reads; serialize conflicting writes. Use bounded tasks, tool calls and repairs.
- Do not modify production data, credentials, external accounts, spend, publication, deployment or destructive resources without explicit action-specific approval.
- On uncertain writes, read back state before retrying. Stop on unresolved critical security, authority, migration or compatibility blockers.
- Report exact files changed, tests actually run, results, untested areas, risks, rollback, remaining gaps and next action.

## 12. Final objective

AMCOS should become a coherent, evidence-backed operating foundation for governed automation and optional brand-to-market execution. The target is not a fixed count of agents or maximum autonomy. The target is the smallest reliable composition of existing capabilities that produces a verified deliverable, with clear human authority, measurable cost, reproducible execution and truthful limits.

**Final law:** reuse what works; repair what fails; connect what exists; complete what is unfinished; add only what is missing; verify every consequential claim; never fabricate execution.
