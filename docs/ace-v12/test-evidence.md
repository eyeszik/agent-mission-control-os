# Test evidence

These results were recorded from commands run in the development container, a 4-CPU Linux host, on branch
`claude/ai-agency-pipeline-oae65z`. Each command and its result are copied from the actual output. CI ran the same gates and suites independently; its results are listed
separately.

| Check | Command | Result |
|---|---|---|
| Seven verifier gates | `make gates` (each `scripts/verify_*.py`) | 7/7 PASS; manifest verified (182 critical files) |
| Ruff (new and changed Python) | `ruff check services/langgraph/agency/actions services/langgraph/agency/agency_os … test_ace12_*.py` | All checks passed |
| Python compile | `python -m compileall -q services/langgraph scripts` | OK |
| ACE v12 action suite | `pytest services/langgraph/tests/test_ace12_actions.py` | 74 passed |
| ACE v12 Agency OS suite | `pytest services/langgraph/tests/test_ace12_agency_os.py` | 8 passed (I13 export re-read included) |
| ACE v12 contracts, UI contract, traceability | `pytest test_ace12_contracts.py test_ace12_ui_contract.py test_ace12_traceability.py` | 2 + 3 + 1 passed |
| Concurrency regression (T35) | `pytest -k t35`, 3 runs without and 3 with the settle fix | without: 3/3 failed; with: 3/3 passed |
| Thread exceptions | `pytest -k "t34 or t35 or t43" -W error::pytest.PytestUnhandledThreadExceptionWarning` | 3 passed |
| Full backend suite, SQLite (local) | `python -m pytest services/langgraph/tests -q` against the default, reused `amc_local.db` | 1189 passed, 2 skipped, 1 failed. The failure is `test_project_workspace.py::test_same_idempotency_key_never_creates_two_projects` (pre-existing, unchanged here): it derives the slug `replay-co` from a fixed name, and that DB already held it from a run on 2026-10-09. The same file on a fresh DB: 15 passed |
| Full backend suite, SQLite (CI, fresh DB) | CI job "Backend (compile + invariants + pytest)" on `59fdc8cf` | 1173 passed, 19 skipped (the CI runner lacks Blender/FFmpeg/Chromium for some local-render tests) |
| Full backend suite, PostgreSQL 16 (local) | same command with `AMC_DATABASE_BACKEND=postgres` on a fresh database with the shim and all migrations applied | 1190 passed, 2 skipped |
| Full backend suite, PostgreSQL 16 (CI) | CI job "Backend on PostgreSQL (migrations + pytest)" on `59fdc8cf`, migrations 1–16 applied | 1173 passed, 19 skipped |
| Other CI checks on `59fdc8cf` | Frontend, Browser E2E, Dependency audit, genome-validation | all success |
| Shared package | `pnpm --filter @amc/shared test` / `typecheck` | 151 passed / 0 errors |
| Web unit tests | `pnpm --filter @amc/web test` | 80 passed |
| Web typecheck and UI AST gate | `pnpm --filter @amc/web typecheck`, `verify:ui` | 0 errors; gate passed |
| Web production build | `pnpm --filter @amc/web build` | Compiled successfully |
| Browser E2E (repo specs) | `pnpm --filter @amc/web test:e2e` against a CI-equivalent stack (operator principal, `proj_1`, fresh SQLite, no model key) | 7 passed, including `agency-os.spec.ts` |
| Browser acceptance drive | Playwright script over the production build with three identities (owner, editor, reviewer) | 18/18 steps passed (summarised below) |

## Acceptance drive

Each step ran in real Chromium against the real API. Every person was a fictional local identity.

1. The shell renders all ten sections.
2. The owner creates a project, then raises autonomy to "Request approval".
3. The editor adds a client and links the project.
4. The editor records strategy and identity inputs and is told they cannot confirm the canon.
5. The reviewer confirms the brand canon.
6. The editor previews a plan ("Ready to launch", nothing executed).
7. The editor launches local work; it is verified and awaits approval.
8. The editor previews and proposes a sandbox publication.
9. The requester's attempt to approve their own request is refused.
10. The reviewer sees the exact bindings and approves both requests.
11. The editor runs the approved action. The inspector then shows one read-back and an intact history chain, and
    no longer offers "Run".
12. The editor exports a verified delivery manifest (1 included) and can download it.
13. The lifecycle shows Distribution as "External action disabled" and Measurement as "Not measured".
14. The integration center shows live execution as disabled, connector gaps and void namespaces.
15. The command palette reaches Analytics by keyboard.
16. The light theme applies through tokens (canvas `rgb(250, 250, 250)`).
17. Mobile at 390 px has no horizontal overflow.

The only console errors were a 403, which was the refused self-approval in step 9 and is expected, and a 404 for
`/favicon.ico`, which this app does not ship.

Defects found by this drive and fixed before recording:

- CORS preflight rejected PUT and DELETE.
- The approval inbox hid its own confirmation.
- Lifecycle badges overflowed their cells.

## Not run here

- External references (OWASP, NIST, OpenTelemetry docs) could not be fetched; the environment proxy returned 403.
- No production, staging or live provider was contacted. There is nothing to contact: no live adapter exists.
