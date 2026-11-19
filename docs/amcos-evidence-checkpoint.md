# AMCOS unified production — evidence and progress checkpoint

**Recorded:** 2026-11-11 UTC · **Branch:** `arena/13d8169f-agent-mission-control-os` · **Base:** `f947863` (current `master` tip) · **PR:** #263 · **Overall:** PARTIAL / **NOT AUTHORIZED FOR PRODUCTION**.

This checkpoint distinguishes observed results from plans and historical claims. A manifest snapshot is not a release revision, signature, independent security review or approval. The [execution roadmap](amcos-execution-roadmap.md) holds the priority, complexity, dependency, capacity, schedule, risk and contingency inventory; the [completion register](amcos-completion-plan.md) tracks Q01–Q38 and M01–M42. `amcos-unified-production-status.md` is previous-phase context, not evidence of current completion.

## Change since the previous checkpoint

The branch reached `master`'s tip and merge conflicts were resolved on the code, not papered over:

| Item | State |
|---|---|
| Branch base | Rebased onto `f947863` (was `04258078`, 126 commits behind). PR #263 is now **MERGEABLE** with `master` as an ancestor; no conflict markers remain. |
| Superseded commits | `ad69e5e` and `0425807` (creative-renderer license pin) were dropped: `master`'s `0a8ba74` supersedes them with a larger rewrite (`findPackageRoot`, SHA verification, `LICENSE_VERSION_MISMATCH`). Nothing unique was lost. |
| `manifest.json` | Rebuilt as the **union** of `master` (336) and this branch (333) → **351** entries; every SHA recomputed against the merged tree using the documented procedure. Seven extra `master`-only paths (durable execution, engineering, artifacts) retained. |
| `test_hmac_ingress_runtime.py` | Conflict resolved as a union: `master`'s stronger `monkeypatch.delenv("DATABASE_URL")` guard plus this branch's explanatory docstring. |
| Duplicate fix found on `master` | `master`'s own manifest was **already stale** for `apps/web/package.json`, `packages/creative-renderer/package.json` and `pnpm-lock.yaml` before this branch touched them (`verify_manifest.py` fails on a pristine `master` worktree). Refreshed here. |

## Dependency-pin repair (root cause of a real CI failure)

Dependabot bumped two audited pins on 2026-11-08 without updating the invariants that guard them. This is a genuine defect on `master`, reproduced on this branch **after** a real `pnpm install --frozen-lockfile`:

- `apps/web/package.json` pins `next@16.4.5`; `node_modules` and `pnpm-lock.yaml` both resolve 16.4.5. UCPO's `dependency_check` compared the installed tree against a hardcoded `16.4.3` in `services/langgraph/agency/ucpo/source.py` and **failed closed** — so the `ucpo-sandbox` and `render-adapters` CI jobs would fail on any tree that installs from the lockfile. Before the reinstall, stale `node_modules` masked it.
- `next@16.4.5` is a **security release** (GHSA-mfr8-8qww-v76h cross-tenant disclosure via `unstable_cache`, GHSA-vc7v-qv4w-wrv8 cache leak across root params, cache poisoning of shared fallback shells). Reverting to 16.4.3 to satisfy the stale gate would have reintroduced known vulnerabilities, so the **gate was corrected to the installed, audited version** instead.

Four sites were aligned: `scripts/verify_repository_invariants.py` (two version checks and three lockfile tokens), `services/langgraph/agency/ucpo/source.py` (`DEPENDENCIES`), one assertion in `services/langgraph/tests/test_ucpo_pipeline.py`, and `docs/ucpo/repository-audit.md`. The assertion was **retargeted, not weakened** — the same fail-closed comparison now runs against the version actually installed.

## Repository gates

**PASS (7/7)** on the merged tree, `python 3.11` venv, after the pin repair:

```
verify_repository_invariants   PASS
verify_production_readiness    PASS
verify_auth_bindings           PASS
verify_ontology_parity         PASS
verify_design_tokens           PASS
verify_manifest                PASS  (351 critical files)
verify_guidance_registry       PASS
```

Also PASS: `compileall -q services/langgraph scripts`; `pip check` ("No broken requirements found"); `git diff --check`.

## Test ledger

| Suite | Result | Scope and caveats |
|---|---|---|
| Replay / cross-project / source authorization (SQLite) | **27 passed** | Operation inventory, 11-family three-project revocation matrix, six cross-project replay cases, inherited-source and twin child-scope guards. |
| HMAC ingress + replay + VNEXUS security/production + unified security | **59 passed, 10 skipped** | Includes the hand-resolved HMAC fixture. Skips are absent browser/FFmpeg and PostgreSQL-only paths. |
| UCPO pipeline/QA/proof-origin + brand handoff + unified delivery + VNEXUS contracts + manifest regressions + Northline bundle | **134 passed, 3 skipped** | Re-run **after** a genuine `--frozen-lockfile` install, so `dependency_check` now sees 16.4.5. Skips are pinned-browser and media-tooling. |
| `@amc/shared` | **266 passed** (21 files), build and typecheck PASS | Contracts including the brand-web bridge. |
| `@amc/web` | **97 passed**, typecheck PASS | 17 files. |
| `@amc/web` production build | **PASS** (`NEXT_TELEMETRY_DISABLED=1 pnpm --filter @amc/web build`) | Compiled in 7.4s, TypeScript 2.8s, 9/9 static pages. Run **after** the `next@16.4.5` install, so the build is verified on the version the pin repair moved to. Emits the known `next-env.d.ts` churn, reverted after the run. |
| UI AST gate | **PASS** (`pnpm --filter @amc/web verify:ui`) | No inline visual styles, arbitrary class colours or duplicate AI provenance roots. |
| `test_ucpo_build.py` | **3 passed, 2 skipped** | The two skips are the real sandboxed builds: `NOT_RUN`, Playwright Chromium absent. Playwright 1.65.0 requires Chromium r1254 and this sandbox has only the r1179-class 153 build; `playwright install` cannot reach its CDN. These stay NOT_RUN in CI terms, not passes. |
| Full `services/langgraph/tests` (SQLite) | **see "Open" below** | Started on this exact tree; buffered stdout, recorded on completion. |

## Open / not claimed

- **Full-suite result for this exact tree** is reported only when the run finishes; anything else is `IN PROGRESS`, not a pass.
- **CI admission is restored and proven by real execution.** The `startup_failure` was `pnpm/action-setup`; all five occurrences were replaced with the corepack step the working revision already used (`49fe32c`). Run **42953426593** on that head created and executed **8 jobs**. Hosted evidence, not inference.
- **Hosted job results moved from 1/8 to 5/8 green on run 42992419209 (head `225aefa`)**, each change tied to a named root cause:
  | Job | Before | At `225aefa` | Cause found |
  |---|---|---|---|
  | Dependency audit | failure | **success** | Unresolvable council constraints (below). |
  | Mission Council | failure | **success** | MCP fixture pinned `sys.executable`; the runner's interpreter is group/world-writable, which `mcp_client` correctly refuses. |
  | Rendering adapters | failure | **success** | `BUNDLE_FILES` required `node/xml.js`, absent from paper 0.17.0, so `fingerprint()` returned all-zeros and the worker looked unbuilt. |
  | Backend | failure | **success** | `next@16.4.5` pin repair (`5018d98`). |
  | Frontend | success | **success** | — |
  | Browser E2E | failure | failure | Four causes found and fixed locally (below); hosted re-run pending. |
  | UCPO sandboxed build | failure | failure | `/usr/sbin/chroot not found` on the runner; exec tools were hardcoded. |
  | Backend on PostgreSQL | — | failure | Not reproducible here (no PostgreSQL binary); the job now publishes failing test names as annotations. |
- **Council constraints were genuinely unsatisfiable**, which is why both council jobs died at install: `aiofiles 25.1.0` vs crewai `~=24.1.0`; `aiosqlite 0.22.1` vs `~=0.21.0`; `pdfplumber 0.11.10` vs `~=0.11.4` and **0.11.10 does not exist on PyPI**; `pydantic 2.14.3` vs crewai's `<2.13` (now **2.12.5**, retained as required); plus the matching `pydantic_core 2.41.5`, `pdfminer.six 20251230` and `json_repair 0.60.1`; `pypdfium2 5.15.1` was additionally **yanked** and is now 5.15.2. Verified in a clean Python 3.11 venv: `pip check` clean, council suite **72 passed / 0 skipped** (was 59/13), dependency-audit job reproduced green ("No known vulnerabilities found, 5 ignored").
- **MCP fixture portability.** Five council tests failed on every runner with `mcp.testsrv.echo is not on the tool allowlist`. The annotation layer added for this purpose returned the reason: `testsrv: /opt/hostedtoolcache/Python/3.11.18/x64/bin/python is group- or world-writable`. The control is correct; the fixture's choice of interpreter was not portable. `council_support.isolated_python()` now returns a `0700`-directory launcher execing the same interpreter when it is writable, and `sys.executable` unchanged otherwise. Reproduced by building a real venv whose interpreter is a `0777` copy: the old pattern is refused with CI's exact message, the new one is admitted, and the council set passes **81/81** in that environment.
- **Rendering.** `runtime.BUNDLE_FILES` listed `node/xml.js`, which paper@0.17.0 does not ship (confirmed from the published tarball: `dist/node` has `self.js`, `extend.js`, `canvas.js`, `browser.js`) and which nothing imports — the worker uses `paper/dist/paper-core.js`, bundled into `paper.cjs`. Because `fingerprint()` returns 64 zeros unless every entry exists, a clean build always looked unbuilt, producing `WORKER_NOT_AVAILABLE`, `BLOCKED_ENVIRONMENT` and the missing-file error. Replaced with `node/browser.js`; after `rm -rf dist && node build.mjs` the fingerprint is real and `test_rendering.py` passes **40/40** locally.
- **Browser E2E: four real defects, found by running the specs in a real browser against a live stack**, not by inspection:
  1. `approvals[].framing_codes` was a **string** on the wire. `_row_to_dict` performs the documented list conversion ("the API contract is a list", ASI09) but three list readers bypassed it, so `AgencyRunSchema` rejected every run carrying an approval, the panel's `catch` left `run` null, and the lifecycle panel rendered `Awaiting run-scoped trust state...` indefinitely.
  2. `ArtifactPreviewPanel` emitted `data-testid="mc-release-btn"` once **per** approval, so a project with approvals from earlier runs produced duplicate ids and strict mode failed.
  3. The innovation brief forced horizontal scroll at 390px: its textarea fell back to default `cols` width (measured `scrollWidth 404` vs `390`). Fixed with `block w-full min-w-0` and `min-w-0` on the grid column; now `scrollWidth 390 == innerWidth 390` after the exact reload path the spec exercises.
  4. The Run Remediation rows reported the **run-scoped** hook-gap count beside a **project-wide** gate, so a blocked gate read "hook gaps 0". The two scopes are now labelled separately.
  Local result with a fresh database and a real browser: `agency-smoke` **4/4** and `innovation-capabilities` passing; `tsc --noEmit` clean; `verify:ui` clean; 118 approval tests and 6 framing tests pass.
- **UCPO sandbox.** The failure-only diagnostic added for this purpose returned `/usr/sbin/chroot not found`. Two causes: the exec chain interpolated five absolute tool paths, and the probe searched only `PATH`, where `chroot`/`prlimit` do not appear for an unprivileged user. Both now resolve at run time (PATH, then the sbin directories). Verified that isolation is **not** weakened: with the interpreter placed outside every mounted directory (the runner's arrangement) the probe returns `available=True`, `network_probe_exit=3`, canary and repository still hidden.
- **Browser E2E is green on the hosted runner** (run `42999989334`, head `69afc9d`). The four defects above were causes, and the hosted job now passes with a per-run database, so no local result was over-reported.
- **The chroot fix worked, and unmasked the real UCPO failure.** At `69afc9d` the sandbox step (which previously died on `/usr/sbin/chroot`) passes. The failure moved to the AVIC step that had never before been reached, and that step had no JUnit report and no annotation step, so it reported only `exit code 1`. Both were added. The annotations then named ten failing tests, all `BROWSER_EXIT:2`, and the added minimal-render diagnostic returned the actual message: **`sh: 1: cannot create .../.amc-sandbox-root/usr/bin/chromium: Permission denied`**. Playwright's browser resolves to `/usr/bin/chromium` on that runner, `/usr` is already bind-mounted read-only, and `_mount()` prepares every target with `mkdir -p` and `: > target`. The redundant nested mount wrote into a read-only bind, so the chroot was never entered. `_dedupe_mounts()` now drops a mount already covered by a wider one. Verified against the defect itself: the old ordering exits 2 with `Read-only file system` on this host, the new one runs the command, and seven tests pin the behaviour including that a path outside every system directory is still mounted.
- **Backend on PostgreSQL is now attributable, and three defects were found and fixed.** `pgserver` provides a real PostgreSQL 16.2 in this sandbox, so the job was reproduced exactly: shim, all 19 migrations, then the same `pytest` command.
  1. `jobs.expire_stale_leases` queried a bare `amc_jobs`. PostgreSQL keeps the durable queue in the `amc` schema, so the one reader that hardcoded the name instead of calling `table()` raised `UndefinedTable` while working on SQLite; lease recovery never ran on PostgreSQL.
  2. The audit chain assumed a single writer. SQLite gets that from `BEGIN IMMEDIATE`; PostgreSQL at `READ COMMITTED` lets two writers read tip *N* and both compute *N+1*. Measured **14 of 24** concurrent appends collide with a unique violation. A transaction-scoped advisory lock, taken *before the tip is read* (a lock inside the insert is too late, because `_next_audit` had already computed the seq), gives **24/24**. Verified by running both arrangements against the same database.
  3. `_next_audit` derived `seq` from `len(audits)+1` while the store validates against `MAX(seq)+1`, so any pruned or retained row wedged every later append permanently. Observed directly: `count 4762` against `max(seq) 4772` after a cleanup. The seq now comes from the tip, and `verify_audit_chain` walks by `seq` rather than `enumerate(start=1)` for the same reason.
- **What is still not established.** Hosted logs and artifacts remain unreachable from here (served from `*.blob.core.windows.net`), which is why check-run annotations are the primary evidence channel and why every failing job must publish one. The UCPO and PostgreSQL fixes are verified by local execution against the real dependency (real PostgreSQL 16.2, real mount namespaces) but the hosted re-run is the proof, and is not claimed until observed. A local Chromium in this sandbox cannot start headless at all (ANGLE/Vulkan initialisation fails), so the browser-render paths cannot be executed here — only the mount logic that broke them can, and that is what was tested.
- Failed approaches, recorded so they are not repeated: `actionlint` binaries are unreachable and `actionlint-py` does not build; Playwright's Chromium **r1254** cannot be downloaded here (the packaged `@sparticuz/chromium` 153 stand-in is usable for the Node E2E suite but not for the Python QA runner, which pins r1254); `chmod` cannot make a venv interpreter writable because `os.stat` follows the symlink, so a real copied interpreter is needed to simulate the runner.
- **Canonical UCPO website QA remains BLOCKED** (pinned Playwright Chromium 156 unavailable locally; only noncanonical Chromium 153 diagnostics ran). Release state **NOT_AUTHORIZED**.
- Rights/licensing, human creative and accessibility review, and owner approval are **NOT_EVALUATED**. The preview contact page has no form, destination or lead capture; an anchor is not a buyer journey.
- Sandbox isolation lacks seccomp/cgroups and independent review; Blender is not equivalently hardened.
- No deployment, publication, spending, Supabase production operation, real collaboration or approval occurred. `master` is not self-merged.

## Compatibility note for reviewers

The brand-graph, twin and intelligence guards now require **tenant-wide** project access until per-node project binding exists. That is a deliberate restriction: bounded-project principals who legitimately hold one project's access are denied. **Do not grant wildcard access to work around it.** Per-node binding and independent review remain P0.
