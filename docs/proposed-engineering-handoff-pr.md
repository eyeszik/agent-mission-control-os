# Pull request description — governed engineering handoff and design guardrails

This PR is submitted for code review at the user's explicit request. It is review-only: it does not request a merge, production deployment, or activation of the disabled worker/integration paths.

## Summary

- Add strict typed handoff, context, plan, durable intake, check, isolation, execution, review, and approval records with a generated Draft 2020-12 JSON Schema.
- Reuse the existing authenticated `Principal`, canonical hash protocol, `durable_runs.create_job`, and durable FSM; add no competing persistence, scheduler, or state writer.
- Add deterministic tenant/project/requester-scoped idempotent intake; submitted requests remain `UNVERIFIED` and cannot authorize execution or GitHub delivery.
- Add a content-addressed in-memory context manifest and self-hashed plan validation.
- Add an explicitly named synthetic-fixture-only Linux namespace executor with strict path/test allowlists, bounded output/time/resources, no host fallback, and receipts bound to plan/context/tree/environment identities.
- Add standalone design guardrail helpers for selected log redaction, exact HTTPS host checks, process-local rate limits, and fail-closed human-review thresholds. They are not wired to a DesignSync route, durable pause, outbound client, or Slack sender.
- Add tests, a disabled reference policy, a synthetic handoff example, a practical execution guide, a traceability ledger, and a security review.

## Validation

- Current targeted engineering and design-guardrail tests: **78 passed**; guardrail tests: **39 passed**.
- Repository gates after rebasing on current `master`: passed; integrity manifest verified **336 critical files**.
- `compileall`, schema parity, and wheel packaging (required package assets present) passed on the rebased branch.
- Ruff formatting/lint/88-column checks and strict mypy for the guardrail package passed (Python 3.10 target).
- A full backend suite run before the branch was rebased on current `master` reported **2095 passed, 107 skipped, 2 existing httpx deprecation warnings**. CI should rerun the complete suite on this PR head.

## Review and merge boundaries

- Review the exact PR diff and run CI on the PR head before merge.
- Keep the example execution policy inactive; do not register a worker, route, or GitHub action as part of this change.
- Merge, deployment, production activation, and any other external action require their own authorization and evidence.

## Explicit non-claims

- This does not provide a real model-generated patch/build pipeline, persistent context artifact, registered worker, provider/router/budget/MCP integration, review/approval UI, API route, GitHub action, browser verification, or deployment.
- The executor passes synthetic fixture tests only. Aggregate cgroup limits and seccomp are unavailable, and the kernel is shared; arbitrary untrusted code remains blocked.
- No L0–L4 level, external production approval, or production readiness is claimed. Opening this review PR does not authorize merge or activation.

## Review focus

1. Verify the use of existing durable/auth/artifact owners and the absence of duplicate orchestration.
2. Audit namespace setup, environment scrubbing, rlimits, process limits, output handling, workspace immutability, and fail-closed paths.
3. Confirm the plan/context/patch/test-tree hashes remain bound through review and future approval contracts.
4. Keep the example policy inactive; do not register a worker or GitHub action as part of this change.
