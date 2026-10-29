# agency/vnexus/brandbook

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## VNEXUS brand book — a projection of the approved genome, built incrementally

`services/langgraph/agency/vnexus/brandbook/` + the brand book routes in `api/routes/vnexus.py` + `components/mission-control/vnexus/BrandBookArea.tsx` (`docs/vnexus-brandbook.md`):

- **One authority.** The approved genome (plus explicitly referenced approved assets) is authority; the book is a projection; pages, prompts and previews are derived. Intake proposals become a genome DRAFT through `propose_draft`, then the existing review. Don't add an editable style guide.
- **Template.** `manifest.py` is a versioned, brandless 24-page template. A page's `required_paths`/`optional_paths` are its dependency set, so a page that reads a key must declare it. Conditional sections need an applicability decision (`production.brandbook.applicability.<page>`), never invented content.
- **States.** `FieldState` (VALUE/NONE/NOT_APPLICABLE/PROPOSED/UNKNOWN) is separate from `approved` and from `EvidenceClass`. `"@none"` and `"@not_applicable: reason"` are explicit genome decisions; NONE is never printed as copy. Production refuses unresolved keys, proposals and template tokens.
- **Assets.** One canonical master per build, placed by hash on every page. A master that is missing, unreadable or unsafe is reported and never substituted. Raster-in-SVG is never vector. Misuse specimens are labelled views, never masters.
- **Rendering.** Deterministic HTML, page format from the genome, no `overflow:hidden`. It is measured in Chromium through the `layout` mode of `visual/browser_runner.cjs`; a check that could not run is NOT_RUN. `identity.specs` renders `brand_guidelines` from this compiler (no hardcoded clear space or minimum size).
- **Incremental.** One Project OS record per page (sections + checks) keyed by dependency hash. Unchanged pages are reused, interrupted builds resume, and the build record always rebinds to the current genome. Project OS slugs artifact keys to 64 characters, so keys are short digests and `_put` refuses longer ones. The process cache holds pure compiler output keyed by tenant/project after authorization, never approvals.
- **Release.** Approval is bound to the production book bytes via `open_artifact_approval`; release is `artifact_release_verdict` plus a genome freshness check. No external effect.
- **Contracts.** Zod twins in `packages/shared/src/schemas/vnexusBrandbook.ts`, fixture `packages/shared/tests/fixtures/vnexus-brandbook.json` (regenerate with `AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_vnexus_brandbook_contracts.py`; needs Chromium). Benchmark: `python scripts/bench_brandbook.py`.
