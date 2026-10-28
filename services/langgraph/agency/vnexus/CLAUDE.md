# agency/vnexus

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## VNEXUS ACE — persisted brand genome and the layers on it

`services/langgraph/agency/vnexus/` + `persistence/vnexus.py` (migration 15, eleven `amc.vnexus_*` tables) +
`api/routes/vnexus.py` (`/vnexus`) + `components/mission-control/vnexus/` (VNEXUS Studio mode):

- **Genome.** `genome.py` is pure: chromosomes, scopes brand → project → page → component → asset, typed
  constraints, `resolve()` (descendants never override IMMUTABLE keys; conflicts are reported, not applied).
  `service.py` owns the lifecycle. Only DRAFT is editable (CAS on `revision`); APPROVED is immutable and one per
  scope; revert makes a new draft. Every mutation appends to a per-brand hash-chained audit log.
- **Approval.** Submit reuses `open_artifact_approval`; `/approvals/{id}/decide` decides. `settle_version` only
  applies that decision, and only when subject hash/ref match, reviewer ≠ author/submitter and ancestors are
  unchanged. Don't add another approval path.
- **Graph and multiverse.** `graph.py`/`multiverse.py` are pure; `creative_service.py` writes inside a locked
  transaction. Branches fork from APPROVED only and are promoted solely by creating a reviewed version — no
  autonomous merge.
- **Production.** `production.approved_projection` refuses without an approved, non-blocking genome. Outputs go
  through the foundry `studio.store`/`observe` and link `DERIVED_FROM` the GenomeVersion node.
- **Media fabric.** `media_fabric.py` providers implement identify/capabilities/estimate/validate/submit/status/
  retrieve. Hosted providers are DISABLED with no network code; `mock.simulated` needs
  `AMC_VNEXUS_MOCK_PROVIDERS=1` outside production and its output is never claimable as generated
  (`can_claim_generated`).
- **Intelligence.** Marketing rates come only from MEASURED rows with a source. Forecasts and the twin are labelled
  SIMULATION. The prompt genome feeds the unchanged compiler. The 14 original prompts are absent and must not be
  invented. The immune system auto-fixes only deterministic, reversible issues, as a new revision.
- **Contracts.** Zod twins live in `packages/shared/src/schemas/vnexus.ts`, checked against the recorded fixture
  `packages/shared/tests/fixtures/vnexus.json` (regenerate with
  `AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_vnexus_contracts.py`).
- **Security.** `test_vnexus_security.py` sweeps every `/vnexus` route from the OpenAPI table as another tenant, a
  viewer and unauthenticated. A new route is covered automatically and must pass.

Details: `docs/vnexus-ace.md`.
