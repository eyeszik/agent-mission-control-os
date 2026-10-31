# UNBOUND Innovation Foundry — H02 development slice

Baseline: `9f12745a8d566e794a9b6e286972ee2033e7d5ee` (`master`, inspected 2026-10-31).
This is a reversible development feature, not production activation or a new agency runtime.

## Requirement / integration ledger

| Requirement | Canonical owner | Decision | Feature files | Acceptance | Risk / limit |
|---|---|---|---|---|---|
| Project authority | security/auth + routes/_project_common | REUSE | api/routes/innovation.py | Deny cross-project and cross-tenant requests | Local authentication remains loopback only |
| Typed innovation inputs/outputs | Feature-local contracts | NEW | agency/innovation/contracts.py; shared schemas/innovation.ts | Strict Pydantic/Zod parsing and matching fixture | Structural checks do not prove novelty |
| Divergence and synthesis | Feature-local pure compiler | NEW | agency/innovation/compiler.py | 35 raw ideas, 12 lenses, 5 wildcard annotations, 4 hybrids, 2 meta-hybrids, 5 shortlisted experiments | Offline fixture mechanisms are SIMULATED; no originality claim |
| Canonical persistence / lineage | ProjectOS, N4 artifact versions | EXTEND | agency/innovation/service.py | Stored bytes independently read; compare-and-set versions; graph rejects cycles | Concept edges are a typed projection inside one versioned research artifact, not separate canonical artifacts |
| Recoverable execution | durable jobs, ticks, fenced intents | EXTEND | agency/innovation/service.py | Bounded explicit advancement; duplicate advancement does not duplicate a result | No always-on scheduler; offline only |
| Execution/release authority | Existing permits, approvals, lifecycle | REUSE | No new approval system | No external executor or approval creation | Experiment drafts are not dispatched; approval control disabled |
| User journey | Mission Control, project store, API client, tokens | EXTEND | InnovationFoundryPanel.tsx | Create, advance, reload persisted result, control drafts | Mobile layout is not public HTTPS hosting |
| Live model/research | Canonical model router | DEFER | Compiler reports PROVIDER_GAP | Explicit blocked result with no fake evidence | No provider authorization, budget, entitlement or source verification invented |
| Learning / observations | Existing ProjectOS records | DEFER | Persisted experiment drafts only | No fabricated observations or decisions | Full evidence ingestion and independent review remain future work |
| M02/M03 federation/discovery | None selected | DEFER | None | No new framework/database | Out of scope |

## ADR-UNBOUND-001: bounded local compilation, canonical durable storage

Reuse the canonical project principal, research artifact ownership, versioned storage,
project events, and durable tick substrate. Keep feature phases local rather than changing
the global workflow FSM. The nine requested roles describe logical responsibilities;
they do not register nine new runtime identities or create approval authority.

The offline adapter has a fixed, inspectable repertoire of mechanisms. It exercises the
pipeline and supplies testable fixture data. Scores are simulated subjective aids, never
probabilities, market evidence, or predictions. Mechanism normalization catches literal
and whitespace duplicates; independent semantic originality/relevance review is absent.
No claim of semantic uniqueness across the market is made.

## Bounded plan

1. Audit current master and applicable guidance; run existing security/storage checks.
2. Implement strict contracts and pure deterministic fixture compilation.
3. Store initial intent and output in existing ProjectOS; advance through bounded durable ticks.
4. Add project-authorized API and Mission Control panel with truthful disabled actions.
5. Exercise refusals, recovery, browser flow, compatibility and integrity gates.
6. Commit and submit a development PR; do not merge or deploy.

Operational bounds: one source-backed implementation design, at most two repair passes per
failed check, no paid/model/research calls, three scoped implementation tasks, no recursive
delegation, no production effects. A tick compiles a fixed finite repertoire; no prompt-controlled
recursion, generated code, URL fetch or external tool dispatch exists in the offline path.

## Safety and data semantics

The brief contains no tenant, actor, approval, signature or permission fields. The server
resolves the project and checks its recorded tenant before storage access. Request wording,
source text, content hashes, simulation scores and source labels cannot grant permissions.
A completed simulation means the draft pipeline completed, not execution readiness, artifact
release, human approval or production readiness. All concepts and experiments remain drafts.

Experiment plans contain hypothesis, assumptions, measurements, falsification and stop
conditions. They contain no observations. No source means the claim remains unverified.
Cost and token usage remain unknown when no measured provider usage exists. No unauthenticated
public endpoint, new database, scheduler, vector service, provider, or telemetry platform is added.

## Setup and operation

Use the existing repository installation and local-auth startup instructions in README.md.
Build `@amc/shared` before starting/typechecking the web application. In Mission Control,
select an authorized project, open Innovation Foundry, enter a brief, and start a simulation.
Advance explicitly; there is no automatic background worker. Refresh to inspect persisted results.
Localhost links only work on the host/device running the server. A mobile browser on another
device needs a separately configured authenticated HTTPS deployment; this feature does not deploy it.

The API is rooted at `/innovation/projects/{project_id}/runs`. Creation requires an
`Idempotency-Key`; tick and control mutations require the latest `expected_version`.
Reusing a key with different input or submitting stale versions must conflict. Pause/resume/cancel
only affect eligible nonterminal work. Approval and external execution remain unavailable.

## Recovery and rollback

Reload the current persisted artifact and version before retrying a mutation. Never blindly
repeat a request with uncertain side effects. Canonical durable intents and fences govern
recovery. A retry must preserve the original brief and input identity. An output object written
before a failed transaction may remain content-addressed but is not authoritative without a
committed artifact head. Keep old artifact versions for audit; do not delete canonical history.

No SQL migration is required. To roll back the feature, revert the feature commit(s), regenerate
only affected integrity pins using `scripts.verify_manifest.git_blob_sha`, and run the seven
repository gates. Retained project research artifacts remain inspectable through ProjectOS.
Do not restore an old whole manifest over unrelated newer changes.

## Deferred requirements and human decisions

Live generation and authorized research; adaptive multi-stage/provider checkpoints; real
experiment execution through the existing fabric; authoritative creative/release approvals;
source evidence submission and observations; independent relevance/novelty review; measured
quality/cost metrics; complete configuration/review/result views; public HTTPS activation.
The proposed 90% structural and 80% reviewer-relevance targets have not been measured.

## API demonstration (local fixtures only)

With a local authorized principal and a real project already created, use the existing
FastAPI docs at `/docs` to call the innovation routes. `POST .../runs` stores a
`RECEIVED` brief such as:

```json
{"objective":"Fictional pilot: make neighborhood tool sharing easier","mode":"GENERAL","provider":"simulated","constraints":["No external effects"]}
```

Send a unique `Idempotency-Key`, retain the returned run ID and version, then
`POST .../runs/{run_id}/tick` with `{"expected_version":1}`. Read the same run with
GET; the returned version/hash identifies the persisted simulation, not a release.

For an entirely offline compiler demonstration without persistence:

```bash
python - <<'PY'
from services.langgraph.agency.innovation import InnovationBrief, compile_run
brief = InnovationBrief(objective="Fictional pilot: neighborhood tool sharing")
run = compile_run(brief, "fixture-demo")
print(run.model_dump_json(indent=2))
PY
```

Run focused checks:

```bash
python -m pytest services/langgraph/tests/test_innovation_contracts.py services/langgraph/tests/test_innovation_api.py -q
pnpm --filter @amc/shared test
pnpm --filter @amc/web test
pnpm --filter @amc/shared build
pnpm --filter @amc/web typecheck
pnpm --filter @amc/web exec playwright test e2e/innovation.spec.ts
make gates
```

Canonical durable telemetry may label the actual local compiler invocation
`REAL_EXECUTION`. Its scope is compiler work only. Feature results and receipts explicitly
carry `simulation: true` and `experiments_executed: false`; no experiment outcome is implied.

## Requirement traceability and current state

| ID | Status | Dependencies | Implementation | Verification |
|---|---|---|---|---|
| H02-01 Strict brief and bounded fixture pipeline | IMPLEMENTED | Canonical hash protocol | contracts.py, compiler.py | test_innovation_contracts.py |
| H02-02 Project-scoped persisted snapshots | IMPLEMENTED | Existing ProjectOS, storage, tenancy | service.py | test_innovation_api.py |
| H02-03 Durable retry-safe compilation | IMPLEMENTED | H02-01/02, durable tick/intent/fence substrate | SimulationHandler | API partial-write and exhaustion cases |
| H02-04 Logical lineage and synthesis integrity | IMPLEMENTED | H02-01 | Parent IDs and typed versioned lineage projection | Contract dangling/cycle/hash refusal cases |
| H02-05 Authenticated mobile workbench | IMPLEMENTED | H02-02/03, canonical API client | InnovationFoundryPanel and innovation routes | innovation.spec.ts; innovation.test.ts |
| H02-06 Independent semantic novelty/relevance | NOT_VERIFIED | Independent reviewer and actual brief-specific generation | Fixed fixture repertoire only | No semantic benchmark claimed |
| H02-07 Live model and research | BLOCKED | Operation-specific authorization, budget, reviewed adapter | PROVIDER_GAP refusal | API live-provider refusal case |
| H02-08 Actual experiment execution/observations | MISSING | Reviewed executor, applicable permits, approvals and evidence verifier | Draft-only models | NOT_RUN is asserted, not execution success |
| H02-09 Exact experiment approval linkage | MISSING | H02-08 and canonical authoritative approval records | Approval control disabled | Browser disabled-control assertion |
| H02-10 Production/mobile HTTPS hosting | BLOCKED | Verified deployment binding, production authentication and database | No deployment changes | Local browser test only |

The offline repertoire is fixed across briefs. It tests structural behavior and governance
boundaries; it is not a live invention engine tailored to each objective. Constraints are
carried into experiment assumptions rather than independently verified for applicability.
The complete UNBOUND vision remains PARTIAL even though this development slice is reviewable.
