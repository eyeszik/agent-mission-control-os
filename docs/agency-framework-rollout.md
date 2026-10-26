# Agency Operating Framework: rollout and rollback runbook

This runbook covers putting the Agency Operating Framework (PR #168, plus the hardening that follows it) into an environment, and taking it back out. It **extends** `docs/production-activation.md`. That document stays the production gate, and nothing here weakens it. No step here was executed against a live environment; every live action needs explicit approval from an owner.

## 1. Hosting facts (observed 2026-10-24)

| Item | Status | Evidence |
| --- | --- | --- |
| Hosting provider declared in the repo | **CONFIRMED: Vercel**, two projects (frontend `apps/web`, backend `services/langgraph`) | `apps/web/vercel.json` (`framework: nextjs`), `services/langgraph/vercel.json` (Python function `app/main.py`, `maxDuration` 60); `docs/production-activation.md` §1 and §5 |
| Vercel projects linked to this repo | **CONFIRMED: none** on the connected account | Vercel API: one team (`eyesziks-projects`) with 0 projects; a repo filter for this repo returns 0 |
| Deploy on push/merge | **CONFIRMED: no deploy happens today.** With no linked Vercel project, a push or merge deploys nothing. If projects are linked later, Vercel's Git integration deploys on push by default, so re-check this before merging anything then. | Same as above; no workflow in `.github/workflows/` deploys |
| CI | **CONFIRMED: test-only.** `ci.yml` runs on push to `master` / `remediate/**` and on PRs. It applies migrations only to its own throwaway PostgreSQL service. | `.github/workflows/ci.yml` (`backend-postgres` job) |
| Production database | **PARTIAL.** One Supabase project exists, `eyeszik's Project`, Postgres 17, us-east-1, status **INACTIVE**. Nothing confirms it is the AMC database. | Supabase API listing |
| Migrations at app startup | **CONFIRMED: none on PostgreSQL.** Only SQLite creates its schema at startup (`sqlite_db.init_db`). PostgreSQL migrations are applied manually, in filename order. | `persistence/database.py`, `persistence/sqlite_db.py`, CI |
| Feature flag for the framework | **CONFIRMED: none.** The `/agency-framework` router is mounted unconditionally in `app/main.py`. | `app/main.py` |
| Backups | **UNKNOWN.** Supabase backup policy for the inactive project was not inspected. | — |

Consequence: today, nothing ships unless someone links Vercel projects and applies migrations by hand. The rollout below is therefore a *first activation* procedure, not an upgrade.

## 2. Change inventory

| Change | Schema | Backward compatible? |
| --- | --- | --- |
| PR #168: framework catalog, tasks, gates, assurance, KPIs | **New tables**: `amc.agency_framework_plans`, `amc.agency_task_instances` (migration `20261024_amc_agency_framework_v1.sql`; SQLite migration 20) | Additive. No existing table changes. The routes return 500 if the tables are missing. |
| Hardening: Review bound to sealed candidates, short-claim detection, accessibility | **None** | Additive request fields (`release_candidate_ref`, `claim_evidence`) and response fields. Existing clients keep working. Records created before the change remain readable. |

## 3. Approvals required before any live step

| Step | Approver |
| --- | --- |
| Link or create the two Vercel projects | Repository owner |
| Reactivate a Supabase project, or choose another PostgreSQL | Repository owner, after a backup decision |
| Apply production migrations | Owner or admin, after a dry run (§5) |
| Mark the environment ACTIVE | Owner, after `docs/production-activation.md` §6–§9 pass |
| Any publication, spend, send or outreach | **Not part of this rollout.** It needs a separate provider implementation phase (`docs/production-activation.md` §11). |

## 4. Preflight (read-only)

1. CI is green on the exact commit to deploy. Record the SHA.
2. `python scripts/verify_production_readiness.py` and `python scripts/verify_manifest.py` pass on that SHA.
3. Confirm which PostgreSQL is the target and that it is the AMC database:
   ```sql
   SELECT to_regclass('amc.runs'), to_regclass('amc.approvals');
   ```
4. List applied migrations, or check for the marker tables of the newest earlier migration. Every migration before `20261024_*` must already be present.
5. Confirm a fresh backup or snapshot exists, and record its id. If no backup can be taken, **stop**.
6. Confirm the secret references (names only, never values) listed in `docs/production-activation.md` §2–§3. Do not print values.

## 5. Migration dry run

Run against a disposable copy of the target, not the target itself:

```bash
# Restore the snapshot into a scratch database, then:
psql "$SCRATCH_DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/20261024_amc_agency_framework_v1.sql
psql "$SCRATCH_DATABASE_URL" -tAc "SELECT count(*) FROM information_schema.tables
  WHERE table_schema='amc' AND table_name IN ('agency_framework_plans','agency_task_instances')"   # expect 2
psql "$SCRATCH_DATABASE_URL" -tAc "SELECT count(*) FROM information_schema.role_table_grants
  WHERE table_schema='amc' AND table_name LIKE 'agency_%' AND grantee IN ('anon','authenticated')"   # expect 0
psql "$SCRATCH_DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/20261024_amc_agency_framework_v1.sql  # re-run: no-op
```

The same sequence was verified locally on PostgreSQL 16: 86 tables, then 84 after rollback, 86 after re-applying, and the re-run was a no-op.

## 6. Deploy sequence

1. Apply `20261024_amc_agency_framework_v1.sql` to the target. This is safe before the code deploys, because the old code never reads these tables.
2. Deploy the backend revision. Check `/health` → 200, then `/ready` → 200 with `database_backend=postgres` and `auth_mode=supabase`.
3. Check `/version`. `commit_sha` must equal the approved SHA. If the platform does not inject it, record that and verify the SHA in the Vercel deployment instead.
4. Deploy the frontend revision.
5. Run the authenticated smoke tests (§7).
6. Only after §7 passes, follow `docs/production-activation.md` §5 step 13 to mark the environment ACTIVE.

## 7. Smoke tests (authenticated, real tenant)

Use a real operator with a membership. Never auto-enroll an account.

| Check | Expect |
| --- | --- |
| `GET /agency-framework/catalog` | 24 modules, 295 tasks, `sha256` = `9a2c30e9…df501a` |
| `POST /agency-framework/plans` on a scratch project | 201; 295 tasks, 0 verified; gates `NOT_ASSESSED` |
| Same request with the same `Idempotency-Key` | The same plan is replayed |
| `GET /agency-framework/plans/{id}` as a member of **another** tenant | 404 `PLAN_NOT_FOUND` |
| Review with `release_candidate_ref` for a run in another project | 422 `REF_NOT_FOUND` |
| Review of a real sealed candidate, by an approver who did not start the run (enforce mode only) | 201 `NEEDS_HUMAN`; `freshness` all true; `decision_ref` null; the run's approval unchanged |
| `/framework` in a browser | Renders; the Search button has an accessible name at phone width |
| Publication, spend and send counters | Unchanged |

Receipts and observability: no new receipts. Check that framework writes appear as `project_events` with `payload.kind` `agency_framework.*`, and that logs carry no secrets (`docs/production-activation.md` §9).

## 8. Rollback

**Thresholds.** Roll back on any of:
- a failed smoke test in §7;
- a 5xx rate above the pre-deploy baseline on `/agency-framework/*`;
- any cross-tenant read;
- any external effect.

**Steps, in order:**

1. **Application.** In Vercel, roll the backend and frontend back to the last verified deployment (`docs/production-activation.md` §10 step 4). The old code ignores the framework tables.
2. **Data: keep by default.** The two tables are additive. Leaving them in place costs nothing and keeps the audit trail.
3. **Data: remove only if required**, and only after taking a backup:
   ```sql
   DROP TABLE IF EXISTS amc.agency_task_instances;
   DROP TABLE IF EXISTS amc.agency_framework_plans;
   ```
   Approvals, `project_events`, assurance artifacts, knowledge and kernel evidence written while the framework was live belong to their own owners and stay valid.
4. **Forward fix.** Preferred over rollback for any defect that is not a security issue: fix in a PR, then re-run CI and §7.
5. **Recovery.** If data was damaged, restore from the snapshot taken in §4 step 5. There is no in-app data migration to undo.

## 9. Known gaps for this runbook

- No Vercel project exists yet, so §6 cannot be rehearsed end to end. The first real deploy is also the first rehearsal. Run it in a Vercel preview first.
- Backup and point-in-time recovery for the Supabase project were not inspected (it is INACTIVE).
- The framework has no feature flag. Disabling it means rolling back the deployment.
