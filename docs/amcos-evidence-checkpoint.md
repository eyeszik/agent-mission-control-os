# AMCOS unified production — evidence and progress checkpoint

**Recorded:** 2026-11-10 UTC · **Branch:** `arena/13d8169f-agent-mission-control-os` · **Base:** `f947863` (current `master` tip) · **PR:** #263 · **Overall:** PARTIAL / **NOT AUTHORIZED FOR PRODUCTION**.

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
| Full `services/langgraph/tests` (SQLite) | **see "Open" below** | Started on this exact tree; buffered stdout, recorded on completion. |

## Open / not claimed

- **Full-suite result for this exact tree** is reported only when the run finishes; anything else is `IN PROGRESS`, not a pass.
- **CI did not validate this branch.** The `CI` workflow has been `startup_failure` repo-wide since 2026-11-09 (16 consecutive runs), while other workflows, including `aisl-proxy.yml`, still start and succeed. `ci.yml` parses under strict YAML, has no duplicate keys, tabs, CRLF or BOM, and every pinned action SHA resolves (including `pnpm/action-setup@73e46992`, the commit behind annotated tag `v6.1.1`). The trigger is repository/platform-side, not a defect this branch introduced or can fix from source. **CI-verified** status is therefore unavailable, not green.
- **Canonical UCPO website QA remains BLOCKED** (pinned Playwright Chromium 156 unavailable locally; only noncanonical Chromium 153 diagnostics ran). Release state **NOT_AUTHORIZED**.
- Rights/licensing, human creative and accessibility review, and owner approval are **NOT_EVALUATED**. The preview contact page has no form, destination or lead capture; an anchor is not a buyer journey.
- Sandbox isolation lacks seccomp/cgroups and independent review; Blender is not equivalently hardened.
- No deployment, publication, spending, Supabase production operation, real collaboration or approval occurred. `master` is not self-merged.

## Compatibility note for reviewers

The brand-graph, twin and intelligence guards now require **tenant-wide** project access until per-node project binding exists. That is a deliberate restriction: bounded-project principals who legitimately hold one project's access are denied. **Do not grant wildcard access to work around it.** Per-node binding and independent review remain P0.
