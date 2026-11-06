# UCPO: baseline and traceability

## Baseline (before this change)

- Base: `master` at `72aecbb8` (the merge of #171).
- Backend suite on SQLite: **1533 passed, 28 skipped** (8 m 45 s), run with the provider environment variables unset as in CI.
- Isolation was proven on the host by direct probes before it was relied on:
  - no network inside `unshare -rmn`;
  - the repository is read-only after a bind remount, and `next build` still passes;
  - `env -i` scrubbing;
  - Chromium runs inside the namespace with route-fulfilled pages.
- Turbopack refuses the symlinked `node_modules`, so the build uses `next build --webpack`.

## Directive section → artifact, test, exception or blocker

| Section | Where |
| --- | --- |
| 06 Contracts and schemas | `ucpo/contracts.py`; Zod `packages/shared/src/schemas/ucpo.ts`; parity `test_ucpo_contracts.py` + `packages/shared/tests/ucpo.test.ts` |
| 07 Requirements, coverage, debt, Intent Linker | `requirements.py`, `semantic.py`; `test_ucpo_pipeline.py` (stable ids, loss stage, OMITTED vs UNAPPROVED_CHANGE, APPROVED_CHANGE, NOT_RUN never PASS, linker) |
| 08 PSEM | `foundry/grammars.py` (`psem_editorial`), `foundry/psem.py`; `test_ucpo_psem.py` (computed pairings, refused pairings, one accent, locked palette, legal posters) |
| 09 Composition / ConstraintWitness | `ConstraintWitness` contract and browser checks; extensions to `CompositionIR` are an exception (capability-gaps.md) |
| 10 Evolution | Exception: Foundry `variants.py` stays the owner |
| 11 Fifteen disciplines | `disciplines.py`; `test_ucpo_registry.py` |
| 12 Five presentation systems | `presentation.py`; `test_ucpo_registry.py`; all five built and browser-verified via `website --board` |
| 13 Sixteen prompt modules | `prompt_modules.py`; preservation tests in `test_ucpo_registry.py` |
| 14 Multimodal | `multimodal.py`; generation is `CAPABILITY_GAP` (tested) |
| 15 Website engine | `site.py`, `source.py`; path, scan, bundle-tamper and human-edit tests |
| 16 Secure build and preview | `sandbox.py`, `build.py`, `preview.py`; `test_ucpo_build.py` (`BLOCKED_ISOLATION` path, tamper refused before execution); `test_ucpo_api.py` (preview serves only a matching export on loopback) |
| 17 Browser QA | `qa.py`, `qa_runner.cjs`; `test_ucpo_build.py::test_browser_qa_catches_a_defective_generator` (accent on paper, no skip link, fixed width → FAIL) |
| 18 Fabric adapters | Exception: the durable job protocol is used; no second dispatch owner |
| 19 Durable workflow | `service.SiteBuildHandler`; selective regeneration, invalidation and supersession in `test_ucpo_build.py` |
| 20 Approval and release proof | `release.py`, `service.inspect_site`; self-approval refused, second approver allowed, proof stale after a change |
| 21 Operator UI | `apps/web/components/ucpo/WebsiteProductionView.tsx` (Website Production section); `apps/web/e2e/websites.spec.ts` (axe, disabled reasons, phone width) |
| 22 Agency framework | `framework.py`, `GET .../framework-bindings`; refs resolve through `operating_framework.refs` (tested) |
| 23 Connectors | Exception: none verified, none called |
| 24 Observability | Events and tick telemetry; metrics `NOT_MEASURED` (exception) |
| 25 Advanced modules | Partial (capability-gaps.md) |
| 26 First end-to-end system | `sample_ucpo_website.json` (fictional *Halden Fen*): three pages, 55 requirements, build PASSED, browser QA PASSED (42 checks), coverage 1.0, approval requested, approved by a second person in tests |
