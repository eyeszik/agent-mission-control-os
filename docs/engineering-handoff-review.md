# Engineering handoff implementation review

**Review status: blocked for production; local scaffolding and synthetic fixture evidence only.**<br>
**Review scope:** this branch's engineering package, supplemental design-guardrail helpers, their tests, package-data include rule, and the current repository integration points. This is not an independent security audit or deployment review.

## Summary

The change reuses AMC's authenticated project principal, canonical AMC-CANON-1 hash helper, durable job table/FSM, and existing fenced tick path. It adds no table, scheduler, worker, route, provider, MCP server, GitHub client, deployment, or remote write. The intake is deterministic and tenant/project/requester-scoped. Context and plan records are integrity-checked. A local Linux namespace sandbox executes only caller-supplied synthetic text fixtures through a fixed stdlib `unittest` controller; the result explicitly carries `execution_tier: SYNTHETIC_FIXTURE`. Separate design-guardrail helpers cover selected log scrubbing, URL allowlisting, in-process limits, and review thresholds; they are pure utilities, not wired enforcement or an external notification path.

A current local isolation probe and synthetic patch test passed. That is useful control evidence, but it is not evidence of model-generated coding, a real checkout/build, production isolation, a human-review outcome, merge, or deployment. A review PR is being opened at the user's explicit request; that action does not establish production capability. No L0–L4 capability level is claimed by this review.

## Findings

### F-01 — HIGH: no aggregate resource or syscall boundary

`/sys/fs/cgroup` is read-only; `memory.max`, `cpu.max`, and `pids.max` cannot be configured. `seccomp` is not configured and the kernel is shared. The executor uses per-process rlimits, PID/network/mount/user namespaces, a read-only minimal root/runtime/workspace, a bounded tmpfs, capability drop, and `no_new_privs`. These controls do not satisfy policy for arbitrary model-generated or attacker-controlled code.

**Disposition:** fixture-only function name/result tier; policy example blocks model code; no route/handler calls it. Any required isolation probe failure returns `BLOCKED`; there is no host fallback. Do not promote to production without aggregate limits, syscall filtering, an immutable runtime image, independent security review, and deployment evidence.

### F-02 — HIGH: no engineering worker or review/approval service

Handoffs are durably scheduled using the canonical `durable_runs.create_job` owner, but this branch registers no engineering handler. A tick with no handler blocks the job and writes no intent. There is no generated patch service, reviewer UI, approval/revocation/expiry recheck, or source-task feedback route.

**Disposition:** retain the no-handler fail-closed behavior. Do not add a worker or action registration until authority, capability, approval binding, and recovery semantics are implemented and tested.

### F-03 — HIGH: context is verified but not durably stored

`ContextRecord` hashes a sorted manifest and `verify_context_bytes` checks exact path set, sizes, and blob hashes. The context itself remains in memory and is not linked to the durable intake job or project artifact graph. No repository checkout or server-owned source selection is implemented.

**Disposition:** do not claim durable immutable context. A future implementation must use an existing scoped artifact owner and verify that its storage backend is authorized; do not assume that configured object storage is local.

### F-04 — MEDIUM: JSON Schema cannot express all semantic validators

`schema.json` is generated from Pydantic and checked for exact source parity. JSON Schema covers structure, types, bounds, and discriminators, but semantic hash equality, DAG acyclicity, path ordering, policy rechecks, and approval expiry/revocation are enforced by Python validators/services rather than expressible schema constraints.

**Disposition:** validate at the trusted application boundary as well as validating JSON Schema. Keep the generated-schema parity test.

### F-05 — MEDIUM: dependency environment is not reproducible

`services/langgraph/pyproject.toml` uses unbounded dependency lower bounds and no lockfile. Local tests were installed into an ephemeral `.venv`; that does not establish production dependency resolution or a stable runtime image.

**Disposition:** record versions used in checks; add an approved lock strategy before production deployment. No lockfile was created in this change.

### F-06 — LOW: existing interface/browser flows were not exercised

No pnpm/browser tooling, API route, or UI was installed or activated for this change. Existing branding, marketing, and creative workflow source was not modified, but no browser regression was run.

**Disposition:** run the repository's future T06/T07 UI/security gates when those layers exist and browser tooling is available.

### F-07 — MEDIUM: supplemental design guardrails are helper-level only

The new guardrail functions do not issue requests, resolve or pin DNS, intercept redirects, write to the log sink, persist rate-limit state, pause the durable FSM, create an approval, or send a Slack notification. The checkout contains no observed DesignSync integration point. The email/token scrubber covers selected patterns only; the accessibility percentage is a project metric, not a WCAG conformance claim.

**Disposition:** use only as pure local helpers until the existing transport, authenticated identity, durable approval, and notification owners are explicitly wired and independently tested. Keep transport-level egress checks and durable/distributed quotas as separate requirements.

## Acceptance review

| Gate | Result | Evidence / limitation |
|---|---|---|
| Contract/schema shape and generated parity | PASS | Pydantic round-trip, `Draft202012Validator.check_schema`, generated file equality |
| Deterministic durable intake and project scope | PASS (local DB) | One durable job/transition for repeat input; unauthorized project rejected; no remote DB exercise |
| Context and plan hash validation | PASS (in-memory) | Blob/manifest/plan drift rejected; no durable context artifact |
| Namespace isolation probe | PASS (this sandbox) | Parent-compared user/mount/net/PID namespace identities; read-only root/workspace/runtime; byte/inode-bounded tmpfs; effective per-process limits; no-new-privs/caps verified |
| Synthetic patch/check | PASS (fixture only) | Fixed unittest runner ran two discovered tests; tests exercise read-only workspace and `RLIMIT_AS`; check binds plan/context/tree/environment |
| Model-generated repository coding | BLOCKED | Not implemented/authorized; aggregate cgroup/seccomp controls missing and kernel shared; fixture evidence does not count |
| Design guardrail helpers | PASS (local tests only) | 39 tests cover selected redaction, allowlist/DNS-answer checks, thread-safe process-local limits, and fail-closed thresholds; no route, transport, durable pause, or notification integration |
| Production worker, approvals, UI, API, and runtime delivery | BLOCKED | No registered route/handler/approval/delivery; the review PR is a separate user-authorized GitHub action |
| Current branch checks | PASS (targeted/gates) | After rebasing on `master`, 78 targeted engineering/guardrail tests passed, `make gates` verified 336 critical files, and compileall passed. The 2095-pass full backend run (107 skipped, 2 existing httpx warnings) predates the rebase; PR CI should rerun it on this head. |

## Security and integrity invariants to preserve

- `durable_runs.transition` remains the sole state writer; use canonical ticks, fences, write-ahead intents, and reconciliation.
- A missing provider, worker, route, approval, or isolation control is a blocker, never permission to run locally on the host.
- Handoff payloads request actions but cannot authorize them. Server-derived project scope is rechecked at every later effect.
- A later approval must bind exact base revision, plan/context hashes, tested tree, patch, target, action, policy, reviewer, expiry, and revocation state.
- Source/policy drift invalidates downstream approvals and test evidence.
- The only authorized remote action for this change is opening this review PR at the user's request; merge, deployment, runtime action, and production change are not authorized by that request.

## Recommendation

Treat this as a disabled scaffold for maintainer review. Keep `execution-policy.example.json` inactive. Do not advertise the workflow as complete, autonomous, production-safe, or capable of creating PRs through the application. The full backend suite passed before the rebase; current targeted tests and repository gates passed, and PR CI should rerun the full suite. Before any activation, separately assign owners and implement durable context, an engineering handler, review/approval controls, production isolation, and deployment evidence. Leave external activation blocked.
