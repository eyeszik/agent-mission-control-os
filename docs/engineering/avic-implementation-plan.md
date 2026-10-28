# AVIC implementation plan (as executed)

Principle: the smallest verified capability first, built on existing owners; every claim backed by a test or a
measurement; anything without an implementation is named PROPOSED/BLOCKED rather than approximated.

| Step | Scope | Result |
|---|---|---|
| 1 | Verify checkout, instructions, archive | Done: HEAD `94e220e9…`, archive inventoried as data (`avic-m0-inventory.md`) |
| 2 | Inventory owners, write contract map | Done (`avic-contract-map.md`) |
| 3 | Baseline checks | Done; results and environment blockers in `avic-m0-report.md` |
| 4 | M1 slice: IntentIR, SceneIR, allowlist SVG, Chromium render, independent evaluation, edits | Done |
| 5 | Connect to Project OS (store/observe, N3 roles, approvals, release record) | Done (`avic/service.py`) |
| 6 | H3 causal repair | Done for contrast, palette, accent budget, text overflow, exact text; blank renders → human |
| 7 | H1 bounded reconstruction | PARTIAL: stdlib region split + gradient fit, measured; research methods PROPOSED |
| 8 | H2 brand mutations, H4 variants | Done (approval-gated mutation; reproducible branches, Pareto selection, no inherited approval) |
| 9 | H5 materials | Done as illustrative shading with provenance; physics backend BLOCKED |
| 10 | Frontend | Not extended: no operational need yet, and no route exists to call (directive: frontend only for operational capabilities) |
| 11 | Integration, security, regression | 49 AVIC tests; seven gates; full backend suite before/after |
| 12 | Inspect SVG and previews | Done (`runtime/avic/demo/`, viewed) |
| 13 | Measurements and defects recorded | `docs/avic.md`, `avic-m0-report.md` |
| 14 | Rollback reference | `94e220e9d20876cd36d5bba35010157fb8089462` (this change is additive; revert the commit, no migration) |
| 15 | Stop before external mutation | No deploy, publish, Cloudflare/Supabase/Vercel/DNS/billing action |

## Next actions (not done, in priority order)

1. ~~`/avic` API route and operator UI~~ done (phase 1): `/avic`, Zod twin + recorded fixture, route sweep, Visual Compiler section, browser test. Reference uploads through the API are next.
2. Bézier contour fitting for H1 (stdlib marching squares + least-squares cubic fit), measured against the region baseline.
3. Licence-reviewed optional DiffVG/LIVE adapter behind a capability probe, CPU baseline kept.
4. Cross-editor round-trip tests (Inkscape CLI where installed) for NATIVE_EDITABLE_VECTOR.
5. A reviewed raster path before HYBRID_SVG can exist (would also need a change to `svg_safety`, which rejects `data:` hrefs).
6. Semantic reference analysis only with a licensed, local model; until then references contribute palettes only.
