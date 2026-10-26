# AVIC M0 report — baseline and verification evidence

## Q0 repository identity

| Field | Value |
|---|---|
| Branch | `claude/ai-agency-pipeline-oae65z` (reset to `origin/master`; its previous PR #185 was merged) |
| Base commit | `94e220e9d20876cd36d5bba35010157fb8089462` — matches the historical reference commit |
| Worktree at start | clean |
| Tooling | Python 3.11.17, Node 22.22.0, pnpm 10.29.3, local Chromium 141.0.7390.37 |

## Q1 baseline (before any AVIC change)

`python -m pytest services/langgraph/tests -q` on the base commit: **1628 passed, 21 failed, 14 skipped** in 3039.64 s
(exit 1). Every failure was classified by re-running it, and none is caused by this change:

| Failing tests | Count | Cause | Evidence |
|---|---|---|---|
| `test_rendering.py` | 18 | `packages/creative-renderer/dist/` was not built in this container (`FileNotFoundError …/dist/paper.cjs`, `WORKER_NOT_AVAILABLE`) | after `pnpm install --frozen-lockfile` and `node build.mjs`: 40/40 pass |
| `test_provider_semantics.py::test_provider_absence_is_explicitly_degraded` | 1 | the container exports empty `AMC_LLM_PROVIDER`, `AMC_GEMINI_MODEL`, `GEMINI_API_KEY`, `ANTHROPIC_BASE_URL` | with those unset: 4/4 pass |
| `test_ucpo_build.py` (2 sandbox tests) | 2 | host has Chromium 1194; `@playwright/test` 1.64.1 needs 1248, and the download host is not reachable from this container | known host limit; CI installs the matching browser and runs them in the UCPO job |

## After the change

- `services/langgraph/tests/test_avic.py`: **49 passed, 0 skipped** locally with Chromium (≈60–120 s).
- Seven verifier gates: all pass (`make gates` equivalents run one by one); `manifest.json` pins 283 files (6 AVIC
  boundary files added: `avic/svg.py`, `service.py`, `intent.py`, `png.py`, `evaluate.py`, `tests/test_avic.py`).
- `ruff check --select E9,F` on the new code: clean. `compileall`: clean.
- Full backend suite after the change, with the renderer package built and the empty provider variables unset:
  **1696 passed, 2 failed, 14 skipped** in 3939 s. The 2 failures are the `test_ucpo_build.py` sandbox tests that need
  Chromium 1248 (host limit above). The skips are optional extras not installed here (jsonschema, crewai/autogen, mcp)
  and archive-gated tests. Versus the baseline: +68 passes (49 AVIC tests, 19 environment-fixed), no new failures.
- Frontend: no file under `apps/web` or `packages/` was changed, so web typecheck/tests/build were not re-run.

## Measurements (actual, this host)

| Metric | Value | Notes |
|---|---|---|
| compile latency (intent → SVG) | 2.1 ms | demo run |
| render latency | 2.3–3.0 s | Chromium cold start dominates |
| verify latency | 1.5 s | stdlib PNG decode + checks at 1200×1500 |
| SVG size, editorial slice | 3,097 bytes, 27 elements | native, 0 raster |
| H1 fidelity, synthetic 320×240 reference (mean ΔE76 at full resolution) | 16 regions 7.20 · 64 → 3.86 · 256 → 1.61 | bytes 3.9 kB · 14.8 kB · 60.6 kB |
| Renderer variance | 2 distinct PNGs in 5 renders of identical SVG; ≤ 2/255 per channel on 0.8 % of pixels | handled by `RENDER_TOLERANCE` |
| H3 repair (injected contrast defect) | fixed in 1 attempt, 0 regressions | `test_h3_repairs_…` |

## Security findings

- The repository's `svg_safety` is a denylist; AVIC adds an allowlist validator on top. 15 malicious/invalid documents
  are rejected in tests (script, event handlers, foreignObject, external `href`, DTD/entities, `style`, `<animate>`
  javascript, `<set>`, `<a>`, dangling `url(#)`, out-of-range and NaN coordinates, duplicate ids, embedded raster in a
  native profile, `xml-stylesheet`), plus element/depth/byte ceilings.
- The stdlib PNG decoder bounds pixels before decompressing and refuses 16-bit/interlaced/unknown formats.
- Cross-tenant and out-of-scope principals are refused before any read; self-approval is refused by the approval route;
  stale approvals, tampered storage and cache divergence block release.
- No secret is read or written by AVIC; a test asserts an injected provider key never appears in stored artifacts.

## Unverified / not claimed

Cross-editor round trips, physically based materials, semantic reference understanding, DiffVG/LIVE-class
vectorization, HYBRID/RASTER output, any deployment or provider integration, and the archived Cloudflare worker.
