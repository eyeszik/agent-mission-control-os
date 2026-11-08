# AMCOS V15 — CI Remediation Ledger (evidence-grounded)

Date: 2026-11-08. Base HEAD: `3c60e6eb4e338563045263c2144e8d0764dfe8ea` (default branch `master`).

## Inventory correction (EXECUTED via `gh`)

The reported "7 failed + 2 skipped" does **not** match any single real check run:

- PR #202 head `c7c2222f`: 8 CI checks — 7 pass, **1 fail** (Browser E2E, run
  41294638270 job 124812790647, step "Run browser release smoke"), 1 skip =
  CodeRabbit (external app, not a workflow job; `skipping` is its normal
  no-review state).
- Latest `master` run 42493947522 (head `1697a242`, 41 commits ahead of this
  branch's base): Backend, Mission Council, UCPO, Browser E2E **fail**;
  Frontend, Backend-PostgreSQL, Rendering, Dependency audit pass. The Backend
  failure step is "Verify repository invariants" — code that exists only on
  `master`, not at this branch's base, where all 7 invariant scripts PASS
  (EXECUTED locally). Those master-only failures are out of scope for this
  branch and must be re-checked after rebase/merge.
- Run 42492597524: Council + Browser E2E failed, 3 jobs `cancelled`
  (concurrency `cancel-in-progress`), not skipped-by-condition.

So: the two "skipped" checks are (a) CodeRabbit (external, optional) and
(b) concurrency-cancelled jobs misread as skips. No `if:`-condition skip of a
required CI job exists in `.github/workflows/ci.yml`. The 7 other CI jobs are:
Backend, Backend-PostgreSQL, Dependency audit, Frontend + the five named.

## Local reproduction at base HEAD (EXECUTED, Python 3.11.2 venv, Node 22.22.3, pnpm 10.29.3)

| Job | Local result |
|---|---|
| Backend (invariants×7 + compileall + pip check + pytest) | 2017 passed, 107 skipped (optional extras/browsers absent), invariants PASS |
| Mission Council (council extra installed) | 71 passed, 0 skipped |
| Rendering `test_rendering.py` after renderer build | 40 passed, 0 skipped |
| Rendering remote / UCPO browser tests | NOT_RUN locally: Playwright CDN (`cdn.playwright.dev`) and FFmpeg are unreachable from this sandbox (TLS reset / no apt candidate). CI runners provision both. |
| Frontend (shared+workspace build, typecheck, test, build) | PASS |
| Creative renderer build | **FAILED → root cause found → FIXED** |

## Confirmed defect (shared root cause for Rendering CI)

`pnpm --filter @amc/creative-renderer build` failed with
`PACKAGE_NOT_FOUND:@react-three/fiber`, although the package is installed.
Root cause, two layers:

1. `packages/creative-renderer/licenses/sources.json` pinned
   `@react-three/fiber` **9.4.0**, while `package.json`/`pnpm-lock.yaml`
   resolve **9.8.2**. The build's `LICENSE_VERSION_MISMATCH` guard fired.
   Verified via GitHub API: license bytes at tag `v9.8.2`
   (commit `d74622ea8ed717f7212d7e19d65ff3e325508389`) are byte-identical to
   the vendored file (SHA-256 `9c35b5de…5349a`). Pin updated to 9.8.2 with
   that commit — not a hash guess.
2. `build.mjs`'s catch swallowed every error except `LICENSE_NOT_FOUND:`,
   so the version guard degraded into a misleading `PACKAGE_NOT_FOUND`.
   The catch now also rethrows `LICENSE_VERSION_MISMATCH:`.

This defect breaks the `render-adapters` job's renderer-build step (and any
consumer of the sealed bundles). Other jobs do not build the renderer, so
they are independent — Council/UCPO/E2E failures on `master` are NOT
explained by this defect (correlation ≠ causation) and were not reproduced
at this base (Council passes; UCPO sandbox isolation passes, 3 passed +
2 Chromium-only skips; E2E needs Chromium, sandbox-blocked).

`manifest.json` entries for the two changed covered files were refreshed
with the repository's documented procedure
(`docs/dependency-integration-2026-10.md`); `verify_manifest.py` passes
(318 files).

## Changed files

- `packages/creative-renderer/licenses/sources.json` — pin 9.4.0 → 9.8.2 (verified commit + identical license SHA).
- `packages/creative-renderer/build.mjs` — surface `LICENSE_VERSION_MISMATCH` instead of masking it.
- `manifest.json` — refreshed git-blob SHAs for the two files above.
- `docs/ci-remediation-v15.md` — this ledger.

## Skip accounting

Required-job skips observed locally are environment-only (`NOT_RUN:
Playwright Chromium not installed`, renderer-build prerequisites) and are
converted to job failures by the workflows' existing `SKIPPED` greps in CI.
No skip markers were removed; no tests deleted; no assertions weakened.

## Status terms

Renderer defect: IMPLEMENTED + EXECUTED (build passes, 40 rendering tests
pass). Backend/Council/Frontend: EXECUTED locally. Chromium/FFmpeg/UCPO/E2E
real-browser gates: NOT_RUN locally (sandbox network), pending CI_VERIFIED
on the PR head SHA.
