# Production migration playbook: Expand → Backfill → Contract

This is the ordered procedure for moving the AMC schema forward on the production PostgreSQL / Supabase database, and for reversing it. Every SQL step is a committed file. Every check below is executed by `services/langgraph/tests/test_migration_roundtrip.py` on a disposable PostgreSQL server, and CI runs it in the `Backend on PostgreSQL` job.

| Artifact | Location |
| --- | --- |
| Forward migrations (expand) | `supabase/migrations/*.sql`, applied in filename order |
| Compensating rollbacks | `supabase/rollback/<migration>.down.sql`, generated from catalog diffs by `python scripts/db_migrations.py rollback` |
| Field-level mapping | `acceptance/migration_mapping.json`; summary in [`sqlite-to-postgres-mapping.md`](sqlite-to-postgres-mapping.md) |
| Tooling | `scripts/db_migrations.py`. It refuses any host other than localhost, so it cannot point at production by mistake. |

Production itself is applied by the deployment's own migration history. See [`docs/production-activation.md`](../production-activation.md) §1. This playbook does not change who runs that step or when; it adds the guards, the rollback and the evidence.

## 0. Preconditions (stop if any fails)

**0a. Verify the target, independently of its name.** A database is production only when at least two of these agree, and the owner confirms in writing:

- the production API deployment's `DATABASE_URL` host is `db.<ref>.supabase.co` (or its pooler) for that ref; the owner reads the host in the deployment dashboard and never shares the password;
- `GET <production API>/ready` returns 200 and `GET /version` reports the deployed commit;
- the database's own catalog holds the `amc` schema with live data (`select count(*) from amc.runs`, `select max(created_at) from amc.runs`).

A paused project is never restored to find out. Restore only after the target is verified, as a decision of its own.

**0b. Read its migration history, read only.** AMC keeps no ledger table, so history comes from the catalog:

```bash
python scripts/db_migrations.py detect --dsn postgresql://<user>@127.0.0.1:<port>/postgres --target "$READ_ONLY_TARGET_DSN"
```

`--dsn` is a local, disposable server, which replays the migrations to learn each one's signature (the stable keys it adds that survive to the final migration). `--target` is queried inside a `READ ONLY` transaction and is never migrated. Each migration reports `APPLIED`, `PENDING` or `PARTIAL`; stop on any `PARTIAL`. `test_migration_detect.py` proves the result at several prefixes and that the target's catalog is unchanged.

**0c. Read-only preflight for the pending files:**

```sql
select count(*) as approvals from amc.approvals;
select tenant_id, project_id, subject_ref, subject_type, count(*) as n
  from amc.approvals
 where status = 'pending' and subject_type in ('BRAND_OS_SOP_ADOPTION','BRAND_OS_SOURCE')
 group by 1,2,3,4 having count(*) > 1;   -- rows the uniqueness migration will mark stale
```


1. Take a point-in-time backup and record its id. The rollbacks restore **schema only**. `20260824_amc_trust_kernel_v1.down.sql` carries `DATA CHANGE NOT REVERSED`, because its up migration rewrites rows; those rows come back only from the backup.
2. CI is green on the exact commit being deployed, including `Backend on PostgreSQL (migrations + pytest)`, which runs the round-trip suite.
3. Pick the upgrade path:
   - From the last known production state (prior baseline `bb91590a`), the upgrade applies only the newer files. The suite proves this produces the same catalog as a clean init, and that no already-applied file was edited in place.

## 1. Expand (additive, online)

Apply each pending file in order, one transaction per file, with bounded locks:

```sql
begin;
set local lock_timeout = '5s';        -- never queue behind a long transaction
set local statement_timeout = '120s';
\i supabase/migrations/<file>.sql
commit;
```

`scripts/db_migrations.py apply` uses exactly these settings. If a lock times out, nothing is applied: retry outside peak load, never raise the timeout to force it through.

The first 19 migrations are expand steps:
- `create … if not exists`, new indexes, added nullable columns;
- constraint widenings that only admit new values (`approval_stale_status_v1`, `durable_intent_uncertainty_v2`).

None of those 19 needs `CREATE INDEX CONCURRENTLY`, because each index is created together with its new table. A future index on a populated table must use `CONCURRENTLY`, outside a transaction, as its own file.

**Review of the two newer files.**

| File | What it does | Locks and data | Rollback |
|---|---|---|---|
| `20261121_amc_tenant_rls_v1.sql` | Adds `amc.current_tenant_id()`; enables (not forces) RLS on every `amc` table; adds `amc_tenant_isolation` on the 84 tables with `tenant_id`. | `ENABLE ROW LEVEL SECURITY` takes a brief `ACCESS EXCLUSIVE` lock on each table, all in one transaction. If any table is busy for 5 s, the whole file aborts and nothing changes. No data change. The owning backend role stays exempt, so behaviour is unchanged while `AMC_DB_RLS_MODE=off`. | Generated; restores the pre-RLS catalog exactly (tested). |
| `20261122_amc_brand_os_pending_approval_unique_v1.sql` | Marks duplicate pending Brand OS approvals `stale` (keeps the earliest), then builds a partial unique index on `amc.approvals`. | **Deviates from the rule above.** The index is built on a populated table inside the transaction, not `CONCURRENTLY`: it holds a `SHARE` lock on `approvals` (writes wait) for one full scan. Acceptable when 0c shows a small `approvals` table. On a large one, split it into a data file plus a `CONCURRENTLY` file before applying. **Data change:** the duplicate rows become `stale` and are not restored by the rollback. | Generated; drops the index; staled rows come back only from the backup. |

These two files do not switch on enforcement. Keep `AMC_DB_RLS_MODE=off` and the existing application role. `FORCE ROW LEVEL SECURITY` and scoped mode wait for every tenant-scoped route, background worker and cross-tenant operation to be handled and for staging isolation tests to pass (`docs/migrations/tenant-rls.md`).

## 2. Backfill (idempotent, chunked, tenant-scoped)

Only needed when data moves between stores, for example importing a local SQLite workspace into production:

```bash
python scripts/db_migrations.py backfill --dsn <ephemeral-or-staging> --sqlite local.db \
  --tables tenants,projects,runs,approvals --tenant <tenant_id>
```

How it works:
- Tables are copied in foreign-key order, in fixed-size chunks by `rowid`, one transaction per chunk, using `insert … on conflict do nothing`. A re-run is a no-op.
- Values are translated with the mapping's rules:
  - JSON text → `jsonb`;
  - ISO / `YYYY-MM-DD HH:MM:SS` text → `timestamptz` (naive values are UTC);
  - 0/1 → `boolean`.
- **Verify:** for every table, the row count and a SHA-256 over the canonicalised rows must match on both sides. Any mismatch is a failed backfill, not a warning.

## 3. Contract (only after soak)

No contract step is pending. Every current migration is additive.

When one is needed (drop a column, tighten a constraint), the order is:
1. Ship code that no longer reads or writes the old shape, and soak it for at least one release.
2. Ship the destructive migration as its own file.
3. Commit a hand-reviewed rollback for it. The generator refuses to write a rollback for a dropped column or a type change, because data cannot be recreated from the catalog.

## 4. Rollback (compensating, newest first)

```bash
python scripts/db_migrations.py apply --dsn <dsn> --down   # every rollback, newest first
```

To roll back one step, run its `supabase/rollback/<migration>.down.sql`. Each file is a single transaction with the same lock and statement timeouts.

The suite proves:
- every single migration rolls back to the exact catalog before it;
- clean init → full rollback → re-migrate is catalog-identical.

A rollback that restores a narrower `CHECK` constraint fails if rows already use the new values (for example approvals in `stale`). That failure is intended: resolve those rows first, never drop the constraint.

## 5. Authorization model (what is and is not enforced in the database)

- `amc` is revoked from the Supabase Data API roles. The suite proves `anon` and `authenticated` get `permission denied` on `amc.approvals`, `amc.runs` and `amc.tenant_memberships`.
- Tenant and project authorization is server-side: verified Supabase JWT → `amc.tenant_memberships`. Browser-supplied tenant or reviewer values are never authoritative.
- **Row-level security** is enabled (not forced) on every `amc` table by `20261121_amc_tenant_rls_v1.sql`, with `amc_tenant_isolation` on the 84 tables with `tenant_id`. The owning backend role is exempt, so it is defence in depth only until a non-owner role and scoped mode are activated. That activation is a separate owner decision, with its own staging gate (`docs/migrations/tenant-rls.md`). The PostgreSQL tests in `test_tenant_rls.py` and `test_tenant_rls_enforcement.py` cover it.

## 6. Post-apply verification

1. `/ready` returns 200 (config valid and `ping_database()` succeeds).
2. Run the PostgreSQL backend suite against a staging copy (`AMC_DATABASE_BACKEND=postgres`).
3. Record the backup id, the applied files and the catalog digest from `acceptance/migration_mapping.json` in the release record.
4. Re-run `scripts/db_migrations.py detect` against the target: every file must now be `APPLIED`.
