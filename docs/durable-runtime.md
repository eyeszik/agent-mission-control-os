# Durable runtime

`services/langgraph/agency/durable/` and `persistence/durable_runs.py` run recurring and long-running work as
**bounded ticks** over durable state. A tick does one unit of work and ends; nothing depends on a process staying
alive. This change does **not** deploy a persistent worker or scheduler. Ticks are invoked explicitly
(`run_tick(...)`), so `RuntimeActive` is false until an authorized deployment exists.

## State machine

`fsm.py` defines 20 `RunState`s and the only legal edges (`TRANSITIONS`). It is pure, and every state is reachable
from `DORMANT`. `persistence.durable_runs.transition()` is the only writer. Each transition:
- asserts that the edge is legal;
- checks the fencing token;
- CAS-updates the row;
- appends to `durable_transitions` with the token, the logical tick and the trace id.

Only an allowlisted set of columns can be set through a transition.

Tables are created by SQLite migration 14, mirrored by `supabase/migrations/20261009_amc_durable_runtime_v1.sql`:
- `durable_jobs`
- `durable_intents`
- `durable_transitions`
- `durable_ticks`

## One tick (`ticks.run_tick`)

1. **Lease.** `claim_due_job` CAS-claims one due `SCHEDULED`/`RETRY_PENDING` job, or an in-flight job whose lease
   expired. The expired case enters `RECONCILING`. The claim increments `lease_token` (the fencing token).
2. **Precheck.** The handler checks project existence and tenancy, archive state, principal access, the attempt
   budget, source rights and the capability route. A failure goes to `BLOCKED_AUTHORITY`, `BLOCKED_PROVIDER` or
   `BLOCKED_ENVIRONMENT` with no write intent.
3. **Load.** The job spec was written server-side by `submit_visual_job` from a server-derived principal. Nothing in
   it is client authority.
4. **Key.** `idempotency_key` = SHA-256 of canonical (tenant, project, job, logical_tick, operation, target,
   input_hash, contract_version).
5. **Intent.** `reserve_intent` persists the write intent and the target's pre-image (head version and hash)
   *before* any effect. The key is a primary key.
6. **Dispatch.** Only the selected local capability is dispatched.
7. **Read back.** The persisted head is reopened from storage.
8. **Verify.** Independent verification runs (`verify_media`).
9. **Commit.** The receipt is committed with a fenced write, and the job moves to `WAITING_APPROVAL` (approval
   opened, bound to the content hash), `SCHEDULED` (recurring) or `DORMANT`.
10. **Telemetry.** The `durable_ticks` row is written:
    - trace, mission, project, node and capability;
    - mode, attempt and logical tick;
    - latency and queue lag;
    - cost `NOT_MEASURED`, GPU memory `NOT_MEASURED`;
    - artifact hash and verification state;
    - failure fingerprint, checkpoint version and `next_due_at`.
11. **Release.** The lease is released and the call returns.

Logical ticks and wall times are separate fields (dual clock). Wall time is never the uniqueness guarantee.

## Failure and recovery

- **Stale workers.** A worker whose lease was superseded gets `StaleFence` on its next write. It cannot commit.
- **Crash after an effect.** On the next claim the job enters `RECONCILING`, and the handler compares the head with
  the recorded pre-image. If a newer version exists, it is adopted, verified and committed, and nothing is
  re-dispatched (T16).
- **Crash before an effect.** The same intent is re-dispatched (`REDO`). This is allowed only for `RETRY_SAFE`
  handlers. Anything else dead-letters for a human.
- **Retries.** At most 3, with backoff of 30 s, 120 s and 600 s.
- **Negative knowledge.** A failure fingerprint is a hash of the operation, the error code and the environment
  fingerprint. A fingerprint that repeats under an unchanged environment goes straight to `DEAD_LETTER` instead of
  retrying a known-invalid strategy.
- **Duplicate submissions.** A duplicate submission returns the same job. Reusing a job id with a different spec is
  refused.

**Guarantee.** Local dispatch is at-least-once, with intent deduplication and pre-image reconciliation. It is **not**
exactly-once: idempotency keys alone do not give exactly-once delivery. No external effects are dispatched by this
runtime.

## Approval

`on_commit` opens an approval through `agency.intake.release.open_artifact_approval`. That creates a run record with
`needs_approval` + `initiated_by`, so `/approvals/{id}/decide` enforces the approver role and separation of duties.
The subject hash is the verified content hash. `settle_waiting_approval(job_id)` moves a waiting job on once a human
has decided. `artifact_release_verdict` refuses release in any of these cases:
- simulation;
- failed or stale verification;
- a cross-project artifact;
- an approval that is missing, pending, rejected or stale;
- a subject hash mismatch;
- self-approval.

## Observability

`observability.metrics()` / `project_metrics()` compute these from persisted rows only:
- queue lag, tick latency and render latency;
- verification pass/fail;
- retry rate and dispatch failures;
- open and committed intents;
- recoveries;
- approval latency.

GPU memory and cost are `NOT_MEASURED`, and percentile comparison is `BASELINE_UNKNOWN`.

`spans()` produces OpenTelemetry-shaped span documents from an attribute allowlist (no prompts, specs, principals or
palettes). `emit_spans()` sends them through the OpenTelemetry SDK only when it is installed and
`AMC_OTEL_EXPORT=enabled`. Datadog export is not implemented here and stays `NOT_CONFIGURED`.

## Formal model and manifests

- `genome.py`: the `MissionGenome`, with admission statuses:
  - `READY`
  - `PROJECT_AMBIGUOUS`
  - `HUMAN_INPUT_REQUIRED`
  - `CONFLICT_BLOCKED`
  - `REFRESH_REQUIRED`
  - `CAPABILITY_BLOCKED`

  It also holds the contradiction engine, the proof-debt ledger and a verifier registry that every predicate must
  name.
- `build_dag.py`: Track A, the A00–A11 build DAG:
  - deterministic node ids;
  - Kahn toposort with cycle and dangling-dependency rejection;
  - dependency closure, critical path and bounded waves;
  - `BuildComplete`, `ReleaseEligible` and `RuntimeActive` as three separate functions.
- `governance.py`: the G0–G4 matrix. Each row names its enforcing symbol, and `resolve_enforcers()` imports each
  one. G3 and G4 are never allowed, and an unknown action is treated as G4.
- `proofs.py`: the evidence validity cache, causal invalidation, the proof minimizer, the capability registry with
  circuit state, and the proof graph.

`scripts/compile_abc_manifests.py --write|--check` generates the `runtime/abc/*.yaml` manifests from this code.
`scripts/seal_abc_build.py` writes `runtime/abc/verification-seal.json` from real command results. See
`docs/abc-v6-runbook.md`.
