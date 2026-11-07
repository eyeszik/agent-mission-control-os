# Engineering handoff — traceability and evidence ledger

This ledger distinguishes implemented contracts from executable production capability. Its implementation/test evidence was gathered locally; no model, provider, MCP, browser, deployed worker, hosted sandbox, runtime GitHub integration, or external production approval was exercised. The user explicitly requested opening this review PR; that action does not authorize merge, deployment, or activation.

## Requirement coverage

| ID | Requirement | Status | Canonical owner / implementation | Tests and observed evidence | Remaining gaps |
|---|---|---|---|---|---|
| ENG-01 | Preserve the agency-to-engineering handoff fields, deliverable/route/feature/acceptance/source/media-rights provenance, budgets, actions, and destinations | PASS | `agency/engineering/contracts.py` (`HandoffRequest`, `DeliverableSpec`, `SourceRef`, `AssetRef`, typed budgets/actions) | `test_engineering_contracts.py`; checked `handoff.example.json` against Pydantic and Draft 2020-12 JSON Schema | No agency UI/API adapter or source-task feedback route |
| ENG-02 | Durable, tenant/project-scoped, deduplicated handoff intake | PASS (local function) | `agency/engineering/intake.py` reuses `Principal`, `authorize_project`, `canonical_hash`, and `persistence.durable_runs.create_job`; deterministic ID is scoped by authenticated tenant/project/requester | `test_engineering_intake.py`: repeat resolves to same job/spec, one canonical initial transition; unauthorized project rejected | Not wired to an HTTP route; no tenant membership provisioning/remote database exercise; `repository_id` is not resolved against a server-owned repository allowlist |
| ENG-03 | Immutable, hash-bound context | BLOCKED (durable context absent) | `agency/engineering/context.py`; `ContextRecord` verifies sorted paths, byte sizes, blob hashes, source spans, revision, omissions, and AMC-CANON-1 manifest hash | `test_engineering_contracts.py`, `test_engineering_sandbox.py`: altered bytes/manifest rejected | Context bytes/manifest are not durably stored or linked to the intake job/artifact store; no repository checkout or source selection service |
| ENG-04 | Bounded plan and explicit check allowlist | PASS (contract) | `PlanRecord` validates DAG, path scope, unique steps/check IDs, supported unittest command, timeout limits, and self-computed plan hash | Plan hash round-trip/drift test in `test_engineering_sandbox.py`; invalid path/argv and cycle checks are contract-level | No planner/model routing, repo-specific plan validator, or persisted approval pin |
| ENG-05 | Isolated patch/build/test | BLOCKED for real coding; PASS only for synthetic fixture test | `agency/engineering/sandbox.py` creates a disposable chroot after verified distinct user/mount/network/PID namespaces, read-only workspace/runtime, bounded tmpfs, capability drop, `no_new_privs`, per-process rlimits, and a fixed stdlib-unittest controller | `test_engineering_sandbox.py`: observed namespace probe; rejects missing namespace identities and out-of-bound tmpfs facts; synthetic patch test exercises `RLIMIT_AS`; bounded infinite-loop test exercises `RLIMIT_CPU`; negative scope, unchanged-test, no-op, binary/size, context/plan drift, zero tests, failure, timeout, output-cap, and no-host-fallback cases | No real checkout/model-generated patch/build; no dependency install; no aggregate cgroup limits, no seccomp, shared kernel; therefore no arbitrary/untrusted code or production executor claim |
| ENG-06 | Check and review evidence bind exact plan/context/tree/environment/patch | BLOCKED (review service absent) | `CheckRecord`, `ExecutionResultRecord`, `ReviewRecord`, `ApprovalRecord` contracts bind relevant hashes and statuses | `test_engineering_sandbox.py` checks plan/context/tree/environment hashes and successful result invariants | No persisted review service, reviewer UI, approval/revocation/expiry recheck, or post-review drift invalidation service |
| ENG-07 | Existing durable transition/recovery semantics remain canonical | PASS for reuse; BLOCKED for engineering worker | Intake creates through `durable_runs`; state transitions stay in existing `durable_runs` / `agency.durable.ticks` | Intake tests assert one canonical transition and verify an unregistered kind fails closed with no intent | No engineering handler/worker registered; no recovery/reconciliation for an engineering effect because no effect is dispatched |
| ENG-08 | Budget, provider routing, MCP, and cost accounting | BLOCKED | Typed zero/positive budget ceilings are contracts only | Budget validation via Pydantic/schema tests | No provider routing, price table/version, reservation/settlement, MCP invocation, or observed-cost telemetry for this workflow |
| ENG-09 | Agency/API/UI approval and external-write boundary | PARTIAL | No new route, UI, worker, GitHub client, or action registration; the user explicitly requested one review PR via `gh`, outside the application | Intake's serialized gate remains `UNVERIFIED`; example policy disables workers and GitHub writes | No runtime approval surface, GitHub target mapping, feedback, browser/accessibility test, merge authorization, or deployment |
| ENG-10 | Preserve branding, marketing, creative, and existing workflows | PASS (scope) | Only engineering and standalone design-guardrail files, package data include rule, and integrity-manifest entries were added; existing workflow source was not edited | After rebasing on `master`, 78 targeted tests, `make gates`, and `compileall` passed; the 2095-pass full suite (107 skipped) was run before the rebase | No end-to-end existing UI/creative browser verification in this environment; CI should rerun the full suite on the PR head |
| ENG-11 | No unauthorized external action | PASS (scoped to this request) | No external service/client was invoked by application code; example switches remain false | Local Git/test evidence; the user explicitly authorized opening this review PR | Authorization is limited to opening the PR; it does not authorize merge, deployment, or production activation |

## Sequential T01–T09 DAG status

The execution order is a strict chain: `T01 -> T02 -> T03 -> T04 -> T05 -> T06 -> T07 -> T08 -> T09`. A blocked stage does not authorize a fallback or a claim of downstream completion; documentation and contract-only work remain explicitly partial.

| ID | Stage | Depends on | Status | Local evidence | Blocking boundary |
|---|---|---|---|---|---|
| T01 | Inspect repository scope, authorization owners, persistence/FSM, and existing workflows | — | PASS | Source review and baseline checks recorded in the handoff review | Not an independent security audit |
| T02 | Define typed handoff contracts and generated schema | T01 | PASS | Pydantic/JSON Schema parity and contract tests | No agency/API adapter |
| T03 | Implement authorized, deduplicated durable intake using AMC owners | T02 | PASS_LOCAL | Intake tests verify authenticated scope, canonical create_job reuse, and fail-closed missing handler | Local persistence only; no engineering worker/route |
| T04 | Bind immutable context and plan to hashes | T03 | PARTIAL | In-memory context/plan verification and tamper tests | No durable context artifact or repository checkout |
| T05 | Enforce bounded validation | T04 | PARTIAL_SYNTHETIC_FIXTURE_ONLY | Namespace, filesystem, tmpfs, per-process rlimit probes; synthetic patch tests | Real coding/build blocked; aggregate cgroup controls and seccomp unavailable; shared kernel |
| T06 | Bind checks, review, and approval evidence | T05 | PARTIAL_CONTRACT_ONLY | Typed records and hash-binding tests | No persisted review/approval service, UI, revocation, or expiry recheck |
| T07 | Integrate API, worker, and UI | T06 | BLOCKED | No route, handler registration, UI, or browser run was added | Requires separately owned integration and approval path |
| T08 | Add provider/MCP routing and budget/cost accounting | T07 | BLOCKED | No provider or MCP call; budget fields are contracts only | Requires supported connection, authority, cost source, and server-side integration |
| T09 | Deliver review PR; separately gate deploy/activate | T08 | PARTIAL | Opening this review PR is explicitly user-authorized; no deployment or activation | Merge, production activation, and deployment remain separately gated and require their own authorization and evidence |

## Supplemental design guardrails (outside the T01–T09 chain)

A separate request adds side-effect-free helpers under `services/langgraph/agency/design/guardrails/filters.py`, with tests in `test_design_guardrails.py`. The checkout has no observed `DesignSync` subsystem or named integration point, so these functions are not wired into a route, worker, durable FSM, notification sender, or live outbound transport.

| Capability | Local evidence | Boundary / remaining work |
|---|---|---|
| PII/credential log scrubbing | 39 helper tests cover email, bearer, OAuth/token assignments, and selected key-prefix patterns | Best-effort pattern filtering only; not a comprehensive DLP system and must run before logs are persisted/exported |
| SSRF host policy | Exact HTTPS host allowlist, no credentials, port restriction, literal-IP denial, optional resolved-IP validation | No DNS lookup or HTTP call; transport must pin the validated DNS answer, revalidate redirects, and enforce egress policy |
| Rate limiting | Thread-safe in-process sliding windows enforce 5 calls/client/minute and 50 admissions/process/hour | Client ID must come from authenticated server state; state is process-local and is not a distributed or durable quota |
| HITL thresholds | Visual error >15% or accessibility metric <95% returns a review-required decision; invalid metrics fail closed | Pure decision helper only; it does not pause the canonical FSM, create approval records, or send Slack notifications; the percentage is not WCAG conformance evidence |

## Test-to-requirement map

| Test file | Coverage |
|---|---|
| `services/langgraph/tests/test_engineering_contracts.py` | JSON Schema generation/parity, example handoff validity, strict/frozen values, path denials, context manifest/blob integrity, execution-policy disablement |
| `services/langgraph/tests/test_engineering_intake.py` | durable dedupe, project authorization, server-derived scope, no-handler blocked outcome, no intent side effect |
| `services/langgraph/tests/test_engineering_sandbox.py` | namespace/resource probe; negative namespace/tmpfs verification; synthetic isolated patch; address-space and CPU rlimit enforcement; tested-tree binding; changed-test/path/no-op/binary/size refusal; context/plan tamper; fail-closed no-host-fallback; zero tests/failure/timeout/output budget |
| `services/langgraph/tests/test_design_guardrails.py` | SSRF scheme/host/port/authority/IP/DNS-answer checks; selected secret/PII redaction; sliding-window boundaries and concurrency; fail-closed HITL thresholds |

Branch coverage was measured for the new engineering package with the following ephemeral tool command (Coverage.py 7.17.2 was installed into the untracked local `.venv`; no dependency/lockfile change was made):

```bash
.venv/bin/coverage run --branch --source=services.langgraph.agency.engineering -m pytest \
  services/langgraph/tests/test_engineering_contracts.py \
  services/langgraph/tests/test_engineering_intake.py \
  services/langgraph/tests/test_engineering_sandbox.py -q
.venv/bin/coverage report -m
```

Observed result: **39 passed; 81% line+branch coverage overall** (`context.py` 79%, `contracts.py` 80%, `intake.py` 93%, `sandbox.py` 81%, package `__init__.py` 100%). This is targeted engineering-package coverage, not full-repository coverage.

Design guardrail coverage was measured separately with Coverage.py 7.17.2:

```bash
.venv/bin/coverage run --branch --source=services.langgraph.agency.design.guardrails -m pytest \
  services/langgraph/tests/test_design_guardrails.py -q
.venv/bin/coverage report -m
```

Observed result: **39 passed; 96% line+branch coverage** (`filters.py` 96%, guardrails `__init__.py` 100%). This is targeted helper-package coverage only. After rebasing on current `master`, combined targeted engineering and design-guardrail tests passed **78 tests**; repository gates verified **336 critical files**, and compileall passed. The full backend suite was last run before the rebase: **2095 passed, 107 skipped, 2 existing httpx `cert=` deprecation warnings**. CI should rerun the full suite and wheel packaging checks on this PR head.

## Evidence status semantics

- `OBSERVED`: directly checked in this checkout or by a recorded local test.
- `ASSUMPTION`: a named premise not proven by available tooling.
- `PROPOSED`: intended future design, not implemented.
- `UNVERIFIED`: no direct evidence.
- `BLOCKED`: required control or owner is absent; no fallback permitted.

The fixture executor's `available=true` means the **local fixture controls that it probes** succeeded. It does not override the documented missing cgroup/seccomp controls and does not authorize production or model-generated code.
