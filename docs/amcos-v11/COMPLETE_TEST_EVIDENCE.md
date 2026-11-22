# Complete test evidence (AMCOS v11.0-C)

Base `origin/master` `1bd62a7b`; candidate = local branch `claude/amc-reconciliation-remediation-mlwtwc`, not pushed. Python 3.11.18; PostgreSQL 16.15 in a throwaway local cluster. Statuses: PASS / FAIL / BLOCKED / NOT_RUN / N/A.

## Full backend suite

| Backend | Result | Failures attributable to this change |
|---|---|---|
| SQLite | 2541 passed, 39 failed, 104 skipped | **0** |
| PostgreSQL (all 21 migrations applied) | 2573 passed, 39 failed, 72 skipped | **0** (no PostgreSQL-only failure) |

**Baseline proof.** The 39 failing node ids are identical on both backends. The same 39 also fail on an untouched `1bd62a7b` worktree in this container: 39 failed, an identical set. They are environmental (BLOCKED here), not regressions:

- 12 `test_avic.py`, 1 `test_avic_api.py`, 1 `test_avic_contracts.py`, 4 `test_vnexus_brandbook.py`, 2 `test_vnexus_directions*.py`, 4 `test_vnexus_production.py`, 5 `test_foundry.py`, 1 `test_abc_v6.py`, 2 `test_ucpo_build.py` and 5 `test_unified_security.py` need Chromium inside the render sandbox. The container's `/opt/pw-browsers/chromium-1243/chrome-linux64/chrome` is a wrapper that execs a binary the sandbox does not mount (`BROWSER_EXIT:1`, exit 127).
- 2 `test_ffprobe_provisioning.py` need a provisioned ffprobe.

Master CI ran these jobs on a real runner. They passed there, except the intermittent UCPO failure (see `CI_ROOT_CAUSE_AND_REMEDIATION.md`).

## Targeted suites

| Suite | Result |
|---|---|
| `test_brand_os_adoption_concurrency.py` (new, 5) | PASS: SQLite ×3, PostgreSQL ×5; negative control fails on the old `release.py` |
| `test_tenant_rls.py` + `test_tenant_rls_enforcement.py` (7 + 6 new) | PASS ×3 on PostgreSQL; pooled tests failed before the pool fix |
| Brand OS / SOP / RLS / migration set on PostgreSQL | 51 passed |
| Mission Council, 5 files, council venv with `tomli==2.0.2` | 72 passed |
| `pip check` (council venv) | PASS |
| `pip_audit`, council extra, CI's ignore list | PASS ("No known vulnerabilities found, 4 ignored") |
| Computer-agent native path | ACE v12 85, fabric 57, council gateway 9 (+5 MCP in the council venv), Obscura 68 passed / 9 NOT_RUN |
| `test_avic.py::test_a_crash_between_stage_writes…` | NOT_REPRODUCED (BLOCKED locally, at line 707) |

## Gates, lint, build, frontend

| Check | Result |
|---|---|
| 9 gates (invariants, production readiness, auth bindings, ontology parity, design tokens, manifest (386 files), guidance registry, AGM discovery, source reconciliation) | PASS |
| `ruff --select E4,E7,E9,F` on every changed Python file | PASS |
| `compileall` services/langgraph + scripts | PASS |
| `@amc/shared` build, typecheck, test | PASS (274 tests) |
| `@amc/web` typecheck, test | PASS (106 tests) |
| `@amc/web` build, Browser E2E | NOT_RUN locally (no TypeScript changed; they passed on master CI) |
| CI on the candidate | NOT_RUN: the branch is not pushed (push needs authorization) |

## Files changed

- **CI:** `services/langgraph/constraints-council.txt`, `.github/dependabot.yml`, `services/langgraph/tests/test_avic.py`
- **Concurrency:** `supabase/migrations/20261122_amc_brand_os_pending_approval_unique_v1.sql` and its generated rollback; `persistence/sqlite_db.py`, `agency/intake/release.py`, `agency/foundry/studio.py`, `agency/project_os/storage.py`, `persistence/projects.py`; new `tests/test_brand_os_adoption_concurrency.py`; regenerated `acceptance/migration_mapping.json` and `docs/migrations/sqlite-to-postgres-mapping.md`
- **RLS:** `persistence/database.py`, `tests/test_tenant_rls.py`, new `tests/test_tenant_rls_enforcement.py`
- **Docs:** `docs/brand-os.md`, `docs/migrations/tenant-rls.md`, `agency/sop/CLAUDE.md`, `docs/amcos-v11/*`, `manifest.json`
- **Unchanged:** the 8 SOP drafts, their pins, and the Pydantic/Zod contracts.
