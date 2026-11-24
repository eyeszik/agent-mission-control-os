# Review and merge handoff (AMCOS v11.0-C)

**Terminal state: PARTIAL_VERIFIED.** Every authorized, feasible item is implemented and locally verified. Two items stay open with evidence: the AVIC flake is NOT_REPRODUCED, and CI on the candidate is NOT_RUN until a push is authorized.

## Local commits (not pushed)

1. `ci: pin tomli 2.0.2 …`: outcome A
2. `Brand OS adoption: one pending approval per subject …`: outcomes C and D
3. `Tenant RLS: prove bypass, pooling, concurrency …`: outcome E
4. `Integrity manifest and computer-agent contract mapping …`: outcomes G and H
5. Evidence ledger and handoff (this file)

## Review focus

- `agency/intake/release.py`: `open_artifact_approval` was split into helpers. Reuse behaviour is unchanged: the same binding on the same run returns the existing approval. Only a unique violation is caught.
- The migration is scoped to the two Brand OS subject types. Duplicate pending rows are marked stale, not deleted, and the rollback cannot restore that data change.
- `persistence/database.py`: the pooled path was previously unusable. Turning pooling on in any environment now actually uses the pool.
- `studio.store`, `storage.put_bytes` and `register_storage_object` are shared by every Project OS producer. The changes affect only the concurrent-create path.

## Approvals required (none taken)

| Action | Why it is gated |
|---|---|
| Push the branch and open a draft PR (the branch was squash-merged, so restart it from master with a force-with-lease push) | remote write |
| Merge | release decision |
| Apply `20261122_…_unique_v1.sql` (or the RLS migration) in production | production database change |
| Create or bind the `amc_app` role, set `AMC_DB_RLS_MODE=scoped`, wrap routes in `tenant_scope` | production RLS activation |
| Adopt a real SOP in a real project | needs an independent human approver |

## Blockers and next actions

| Blocker | Evidence | Next action |
|---|---|---|
| AVIC `test_avic.py:718` intermittent on CI | CI annotations on `1bd62a7b` and `c9849dbe`; local Chromium is unusable | After the push, read the new failure message (status and reasons) from the UCPO job, then fix the named cause |
| No CI run on the candidate | no push authorization | Authorize the push; watch Mission Council, Dependency audit, UCPO and Backend on PostgreSQL |
