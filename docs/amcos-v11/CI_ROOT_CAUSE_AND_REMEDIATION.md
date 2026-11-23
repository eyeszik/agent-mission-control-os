# CI root cause and remediation (AMCOS v11.0-C, outcome A)

Baseline: `origin/master` at `1bd62a7b` (CI run 44964419596). Three jobs failed and every other job passed, including Backend (SQLite), Backend on PostgreSQL, Frontend, Browser E2E, Rendering, Obscura and CodeQL.

| Job | Root cause | Evidence | Remediation | Local verification |
|---|---|---|---|---|
| Mission Council engines | The council extra could not be resolved, so the install step failed. | Dependabot #270 (`1baac4d4`) bumped `tomli` to 2.5.0 in `services/langgraph/constraints-council.txt`. The `crewai`, `crewai-cli` and `crewai-core` 1.15.37 wheels each declare `Requires-Dist: tomli~=2.0.2` (`>=2.0.2,<2.1`), read from the downloaded wheel METADATA. | Pin `tomli==2.0.2`, the smallest compatible version. A scoped Dependabot `ignore` covers only `tomli >=2.1` on `/services/langgraph`, so 2.0.x patches stay eligible. Nothing else is ignored. | In a fresh Python 3.11 venv, the CI install command exits 0; `pip check` reports "No broken requirements found"; the five council test files report **72 passed**. |
| Dependency audit | Same resolver failure in "Audit the optional council extra". | The job log shows the failure in step 5 before `pip_audit` ran. | Same pin. | `pip_audit` with CI's exact six `--ignore-vuln` flags reports "No known vulnerabilities found, 4 ignored", exit 0. |
| UCPO sandboxed build + browser QA | `test_avic.py:718` `DID NOT RAISE RuntimeError`. The edit returned before its preview write, so the simulated crash never happened. | The same runner's diagnostic step shows Chromium raster, PDF and layout all `PASSED`, so the browser was present. The failure is intermittent: UCPO failed on `c9849dbe` (a different test, `test_vnexus_brandbook.py:340`), passed on `cd6ad3af` and `a819a50b`, and failed on `1bd62a7b`. | **NOT_REPRODUCED.** Locally every render fails for an unrelated environmental reason: the sandbox Chromium wrapper `/opt/pw-browsers/chromium-1243/chrome-linux64/chrome` execs a `real/` binary that the render namespace does not mount, so the failure stops earlier, at line 707. No assertion was removed or mocked. The test now fails with the edit's own status and reasons instead of a bare "DID NOT RAISE", so the next CI failure names its cause. | NOT_RUN as CI runs it: no usable Chromium in this container (Ubuntu 24.04 has no apt `chromium`). |

## Two more breaks merged to master after the baseline (found while rebasing)

Master moved to `786d1017` during this cycle. Two Dependabot merges made the council extra unresolvable again, for different reasons:

| PR | Root cause (from wheel metadata) | Remediation |
|---|---|---|
| #268 `googleapis-common-protos` 1.75.0 → 1.76.0 | 1.76.0 requires `protobuf>=6.33.5,<8`; `constraints-council.txt` pins `protobuf==5.29.6`. pip reported `resolution-too-deep`. | Pin back to `1.75.0`. Dependabot ignores only `>=1.76` until the protobuf pin moves to 6.x. |
| #266 `psycopg-binary` 3.3.8 → 3.3.9 | `psycopg` 3.3.8 requires `psycopg-binary==3.3.8` exactly; the bump left `psycopg` behind (`ResolutionImpossible`). | Move `psycopg` to `3.3.9` to match (keeps the update). A Dependabot group moves both in one pull request from now on. |

Verified after the rebase:

- A fresh install of the council extra exits 0 and `pip check` is clean.
- The Mission Council tests: 72 passed.
- The PostgreSQL Brand OS, concurrency, RLS and migration suites on psycopg 3.3.9: 57 passed.
- A replay of the Dependency audit job's exact steps 4–5 in a fresh venv: both `pip_audit` runs exit 0.

pip prints a resolver warning there, because the newest pip-audit (2.10.1) prefers `tomli>=2.2.1`/`tomli-w>=1.2.0` and step 5 installs the council pins into the same environment. pip still exits 0 and pip-audit still runs. The Mission Council job does not install pip-audit, so its `pip check` step is unaffected.

## AVIC: what the code allows

`edit_asset` reaches `_commit`, and so the preview `_put` the test intercepts, only when `_produce` returns a passing report with PNG bytes. Two earlier exits return without raising:

- `REJECTED`, when the render is `BLOCKED` (renderer unavailable, or `RENDER_CAPACITY` because no slot is free without blocking) or `FAILED`, or when the evaluation fails;
- `CONFLICT` (stale base).

The test's compile on the same runner was `EVALUATED`, so the renderer worked moments earlier. The leading hypotheses are therefore a transient render failure or a capacity refusal. Neither is proven. The next action is to read the new failure message from the next CI run, which reports `status` and `reasons`.
