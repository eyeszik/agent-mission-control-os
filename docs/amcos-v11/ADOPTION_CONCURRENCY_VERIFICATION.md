# Adoption concurrency verification (outcome D)

## Defect

`open_artifact_approval` read the pending approvals and then inserted, without a lock or constraint. Two concurrent `POST /brand-os/projects/{p}/sops/{s}/adoption` requests with different `Idempotency-Key`s could each miss the other's row and open two pending approvals.

The first parallel test exposed three more races on the same path, all present before this change:

1. `LocalStorageAdapter.put_bytes`: concurrent writers of the same object shared one temp file `.<hash>.tmp`, so the second rename raised `FileNotFoundError`.
2. `foundry.studio.store`: two first-time creators collided on the artifact key (`IntegrityError` on SQLite, `ProjectConflictError` on PostgreSQL).
3. `register_storage_object`: on PostgreSQL READ COMMITTED both writers missed the row and inserted, raising `UniqueViolation` on `storage_objects_project_id_backend_content_hash_key`. SQLite's `BEGIN IMMEDIATE` serializes writers, so it never showed there.

## Fix (database-enforced, not process-local)

| Layer | Change |
|---|---|
| PostgreSQL | `supabase/migrations/20261122_amc_brand_os_pending_approval_unique_v1.sql` adds the partial unique index `idx_amc_approvals_brand_os_pending` on `(tenant_id, project_id, subject_ref, subject_type) WHERE status='pending' AND subject_type IN ('BRAND_OS_SOP_ADOPTION','BRAND_OS_SOURCE')`. Existing duplicate pending rows are first marked `stale`; the earliest is kept, and none is approved or deleted. The rollback is generated: `supabase/rollback/…unique_v1.down.sql` drops the index and states that the data change is not reversed. |
| SQLite | `sqlite_db._ensure_brand_os_pending_unique` builds the same index (`idx_approvals_brand_os_pending`) once. `init_db` runs on every transaction, so after the first build it is a read-only `sqlite_master` check. The first draft ran its UPDATE every time and caused `database is locked`; that was caught and fixed in this cycle. |
| Canonical fingerprint | The binding is unchanged and canonical: tenant, project, artifact id, version, SHA-256 content hash, subject type and policy version. |
| Approval creation | `intake/release.py`: `_ensure_approval_run` tolerates only a lost run-insert race. On a unique violation (`sqlstate 23505` or a sqlite UNIQUE `IntegrityError`), `create_approval_request` re-reads and returns the winner's approval if it binds the same content, or raises 409 `APPROVAL_CONFLICT`. Any other error re-raises. |
| Staging | A private temp name per writer; `studio.store` re-reads the head after a lost create, reuses it when the content is identical, and otherwise raises `StaleArtifactVersionError`; `register_storage_object` retries once on a unique violation. |
| Scoped idempotency | Unchanged: the scope is `tenant:user:brand-os.adoption:{project}:{sop}` and the payload is derived from the path. A same-key/different-payload case therefore cannot be expressed on this route. |

Other approval purposes are deliberately unconstrained by the index (`test_other_approval_purposes_are_not_constrained`).

## Tests (`services/langgraph/tests/test_brand_os_adoption_concurrency.py`)

| Test | SQLite | PostgreSQL |
|---|---|---|
| Six threads behind a barrier, different keys: one approval id, one pending row, no errors | PASS ×3 | PASS ×5 |
| Forced lost race (pre-insert read misses): insert refused by the index, re-read returns the winner | PASS | PASS |
| The database itself refuses a second pending adoption approval | PASS | PASS |
| A racer with different content gets 409, not a second approval | PASS | PASS |
| Other purposes are not constrained | PASS | PASS |

**Negative control.** With the original `release.py` restored, the parallel test and three of the others fail, so the tests discriminate. The existing `test_brand_os_api.py`, `test_sop_source_approval.py`, `test_tenant_rls.py`, `test_tenant_scope.py` and `test_migration_roundtrip.py` pass on PostgreSQL after the change (51 passed).
