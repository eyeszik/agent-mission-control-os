# agency/vnexus/directions

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## VNEXUS creative directions — recommend, select by approval, rebuild only when needed

`services/langgraph/agency/vnexus/directions/` + the creative directions routes in `api/routes/vnexus.py` + `components/mission-control/vnexus/DirectionsArea.tsx` (`docs/vnexus-directions.md`):

- **Stages.** Intake → shared `CreativeIntent` (through the existing prompt compiler; exact identity text is kept out of raster prompts) → generate/import → record → review → human selection → conditional vector reconstruction → freeze. The 14 seats, six modes and eight stages are PROPOSED definitions; don't claim they reproduce an original spec.
- **Routes.** `providers.py` is the route registry. Cloudflare, Gemini critique, Exa/Tavily and Groq are declared with `adapter_implemented=False` and stay DISABLED. `AMC_VNEXUS_SPEND_MODE=zero` refuses unknown or non-zero prices and offers `manual.handoff`; a refused route never falls through to another model. Credentials are env var names, checked for presence only. `local.foundry_compose` is the only real generator (deterministic marks/icons).
- **Provenance.** Imports are `USER_REPORTED`; `observed` (server facts) and `reported` (importer statements) are separate fields; SIMULATED is never selectable or a master.
- **Review.** It only computes a stored session: `effects` are fixed false. Local measurements produce findings and gate evidence, never scores; scores come only from named human reviewers. No vision route exists, so perceptual lenses without human input are NOT_REVIEWED (null scores) and required ones block readiness. Gates are non-compensatory. `measured_recall` is always `HUMAN_RECALL_NOT_TESTED`. Work orders are `PROPOSAL_ONLY`.
- **Selection and freeze.** Selection is `open_artifact_approval` on the candidate bytes. Freeze needs that approval, a PASSED reconstruction when the role needs vectors, and a RELEASE review `READY_FOR_APPROVAL`; it submits a genome draft pinning `visual.logo.master_artifact` + `visual.logo.master_sha256`. The brand book and `produce_identity` read the master only through the approved genome and refuse bytes that don't match the pin. Don't add another approval path.
- **Reconstruction.** Only for roles that need editable paths. `controlled_trace` is the AVIC region split snapped to the palette (PARTIAL: rectangle regions, stair-stepped curves); identity text is never traced. Fidelity is claimed only from a measured Chromium comparison; without Chromium it is NOT_VERIFIED.
- **Storage.** Project OS artifacts only (no table or migration); the per-intent ledger is compare-and-set.
- **Contracts.** Zod twins in `packages/shared/src/schemas/vnexusDirections.ts`, fixture `packages/shared/tests/fixtures/vnexus-directions.json` (regenerate with `AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_vnexus_directions_contracts.py`; needs Chromium). Demo: `python scripts/render_directions_demo.py`.
