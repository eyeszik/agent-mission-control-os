# H02 review record

Scope: the new innovation contracts, pure compiler, ProjectOS/durable integration,
API routes, shared wire schemas, and Mission Control panel. This is a bounded
read-only code review plus development refusal tests, not a universal security proof.

## Findings and repair requirements

1. **Failure counters rolled back.** A refusal raised inside the encompassing transaction
   erased canonical durable retry evidence. A reviewer reproduced three dispatch failures
   each leaving the job SCHEDULED with attempts and fence still zero. Repair: commit the
   canonical failed tick evidence before returning the HTTP refusal; preserve max-attempt
   exhaustion as an explicit blocked feature result. Test injected dispatch faults.
2. **Result/brief relationship missing.** Schema-valid result bytes could carry a different
   objective from the admitted brief. Repair: validate objective, selected mode, provider
   semantics and input identity at document readback, and bind candidate admission to the
   original brief. Hashes alone are not authority or semantic correctness.
3. **Stale UI response.** Selecting a different run during a pending mutation could allow
   the earlier result to overwrite selection. Repair: disable selection while mutating,
   abort pending detail fetches and reject aborted/project-stale responses. Browser test
   delays a real request and asserts history selection remains disabled.
4. **Intermediate assignment failure.** Updating status and phase separately triggered
   strict coherence validation between assignments. The first browser run observed HTTP
   422 on Pause. Repair: validate and install a coherent replacement state atomically.

Observed passing regressions and any remaining limitations are in `validation.md`.

## Protected boundaries

- Project authorization must occur before storage access, including list/read/tick/control.
- Feature body fields cannot declare actor, tenant, approval, signature or external permission.
- Byte SHA-256 checks, strict schema validation and ProjectOS compare-and-set versions remain separate.
- Durable leases/intents/receipts are reused, not reimplemented by prompts.
- Retrieved input is never executed. The fixture compiler has no network/model/tool dispatch.
- Experiments retain NOT_RUN/NOT_REQUESTED; release and execution controls remain unavailable.
- SQLite local tests do not establish PostgreSQL concurrency coverage or production readiness.

Remaining integration risks: full adaptive provider execution and exact release-purpose approval
linkage are not implemented; independent semantic originality/relevance and objective-specific
creative quality are not verified. Unscoped real provider calls must not be added as a workaround.
