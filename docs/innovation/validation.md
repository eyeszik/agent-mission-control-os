# H02 validation record

Baseline: `9f12745a8d566e794a9b6e286972ee2033e7d5ee`.
Environment: development workspace, Python 3.11 virtualenv, Node 24.19.0;
SQLite development tests; no real provider calls, production deployment or release.

| Cohort | Command | Observed | Interpretation |
|---|---|---|---|
| Baseline critical gates | `make gates` | All seven gates passed; 308 integrity pins | Static/integrity checks, not a production claim |
| Baseline storage/approval contracts | `python -m pytest services/langgraph/tests/test_approval_authority.py services/langgraph/tests/test_project_os_contracts.py services/langgraph/tests/test_project_artifacts.py -q` | 23 passed | Scoped regression baseline |
| Discovery correction | Initial selector included nonexistent `test_durable_runtime.py` | No tests ran | Corrected selectors using actual repository files; never counted as pass |

Candidate source is identified by the raw SHA-256 manifest in `sources.json` and the
feature commit containing this report. Local observed results:

| Cohort | Command | Observed | Scope |
|---|---|---|---|
| New backend | `python -m pytest services/langgraph/tests/test_innovation_contracts.py services/langgraph/tests/test_innovation_api.py -q` | 64 passed in 25.10s | 44 pure contracts plus 20 real SQLite/API/recovery cases |
| Existing agency/security/storage | `python -m pytest services/langgraph/tests/test_full_service_operations.py services/langgraph/tests/test_execution_fabric.py services/langgraph/tests/test_project_workspace.py services/langgraph/tests/test_project_artifacts.py services/langgraph/tests/test_approval_authority.py services/langgraph/tests/test_project_os_contracts.py -q` | 98 passed in 134.20s | Scoped broad regression cohort; not the full backend suite |
| Web unit suite | `pnpm --filter @amc/web test` | 95 passed, 17 files | Existing plus new client tests |
| Shared suite | `pnpm --filter @amc/shared test` | 258 passed after retry-phase addition | 19 files; includes final retry-phase wire verification |
| Wire contract | `pnpm --filter @amc/shared exec vitest run tests/innovation.test.ts` | 4 passed | Python fixture plus final retry-phase/refusal parsing |
| Shared/web typecheck | `pnpm --filter @amc/shared typecheck`; `pnpm --filter @amc/web typecheck` | Passed | Local compiler checks |
| Build | `pnpm --filter @amc/shared build`; `pnpm --filter @amc/web build` | Passed | Production bundle compiled, not deployed |
| Mobile browser | `pnpm --filter @amc/web exec playwright test e2e/innovation.spec.ts` | 1 passed in 4.7s | Actual local API/database at 390px; refresh, controls, cohort, drafts, disabled approvals and stale-selection guard |
| Critical gates | `make gates` | All seven passed; 312 pins | Existing hashes preserved, four new trust-boundary files covered |
| Python syntax | `python -m compileall -q services/langgraph/agency/innovation services/langgraph/api/routes/innovation.py` | Passed | Source compilation |
| Dependency consistency | `python -m pip check` in isolated venv | NOT_RUN: pip module unavailable | No dependency changes made |

Failures were retained and repaired, not excluded: the first browser run exposed non-atomic
status/phase assignment; the second exposed an ambiguous status locator. The API fault-injection
cohort initially failed because RETRY_EXHAUSTED was missing from the Python/Zod enums.
The final combined 64-case cohort includes the passing exhaustion refusal test.
The review also reproduced retry-counter rollback and a wrong-brief result; both have regressions.
Logs and initial browser artifacts were retained under `/tmp/unbound-preview` during this session.
They are ephemeral developer evidence, not customer artifacts or production audit retention.

Full backend suite, PostgreSQL runtime, full accessibility audit, live providers and hosted
CI final conclusions are NOT_VERIFIED. No tests were intentionally skipped to obtain these counts.
Hosted CI and PostgreSQL must be recorded separately from local SQLite.
No quality/relevance pilot was conducted; no performance, cost, originality,
conversion, commercial feasibility or full accessibility claims are made.

Final shared build, web typecheck and production web build passed again after the
retry-phase contract alignment. Final feature Python cohort: 64 passed.

Resource record: remote model/search/experiment calls 0; no monetary usage was
available, so monetary cost is UNKNOWN. Offline experiment draft ceilings are
10 cases/60 seconds/0 retries/0 external calls; no experiment ran. Compilation
uses 35 raw fixtures/4 hybrids/2 meta-hybrids/5 drafts; durable max attempts is 2.
Four scoped specialist tasks were used without recursive delegation. Exact aggregate
tool/token usage was not metered and is UNKNOWN; no dollar/token-budget enforcement
is claimed. No production mutation, deployment, paid provisioning or merge occurred.
