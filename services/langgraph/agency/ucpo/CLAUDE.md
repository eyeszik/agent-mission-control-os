# agency/ucpo

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Website production line (UCPO) — brief to verified site, never deployed

`services/langgraph/agency/ucpo/` + `api/routes/ucpo.py` (`/ucpo`) + `components/ucpo/` (the Website Production section of `/agency`) + CLI `website`:

- **Stages are Project OS artifacts.**
  - Brief → requirements → PSEM genome → tokens → plates → site IR → source.
  - Each is stored through `foundry.studio.store` (key `foundry-ucpo-<site>-<stage>`) with `depends_on`, after `assert_role_may_produce`.
  - No table, migration or approval store is added. Don't add one.
- **Copy and requirements.**
  - Copy comes only from the brief.
  - Requirement ids are structural.
  - Every element in the generated source carries `data-req`.
- **Generated source is untrusted.**
  - `sandbox.probe_isolation` must *demonstrate* the sandbox: `unshare -rmn`, a read-only repo, `env -i`, `prlimit` and `timeout`. Otherwise return `BLOCKED_ISOLATION` and run nothing.
  - Build: `tsc` + `next build --webpack` inside the sandbox.
  - QA: `qa_runner.cjs` in the sandbox, with Chromium route-fulfilled from the export.
  - NOT_RUN or BLOCKED never counts as PASS.
- **Durable job.** Build + QA is the durable job `ucpo_site_build` (`SiteBuildHandler`), driven by an explicit `run_tick`.
- **Release.**
  - `release.seal_proof` binds every revision.
  - Approval opens only for an eligible proof and is decided via `/approvals/{id}/decide`.
  - `deployment` is always `NOT_AUTHORIZED`.
- **Registries.**
  - Disciplines, presentation systems, prompt modules and multimodal specs are registries.
  - Generation providers are `CAPABILITY_GAP`; never fake them.
- **Contracts.** Zod twins are in `packages/shared/src/schemas/ucpo.ts`; the fixture is `packages/shared/tests/fixtures/ucpo.json` (regenerate with `AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_ucpo_contracts.py`).

Details: `docs/ucpo/README.md`.
