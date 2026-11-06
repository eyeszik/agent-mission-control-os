# agency/operating_framework

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Agency Operating Framework — a ledger over existing owners

`services/langgraph/agency/operating_framework/` + `persistence/operating_framework.py` (SQLite migration 20 / `20261024_amc_agency_framework_v1.sql`) + `api/routes/agency_framework.py` (`/agency-framework`) + `apps/web/components/framework/` (`/framework`, also the Operating Framework section of `/agency`):

- **Catalog.** `data/catalog.seed-v1.json` is vendored byte-for-byte and SHA-256 pinned; `load_catalog` refuses it unless schema and semantic checks pass (24 modules, 295 unique tasks, per-module counts, no cycles). A changed catalog is a new version and pin, never an in-place edit.
- **Bindings.** `bindings.py` maps each module to an N3 role that may produce its N1 artifact type (`verify_bindings` checks the live kernel). Coverage is EXACT / NEAREST / NO_N3_ROLE; keep the gaps visible, don't invent roles.
- **Tasks.** Instances are CAS on `version`; every write appends one `project_events` row in the same transaction. VERIFIED only via `/verify` (server re-check, approver role, not the submitter); APPROVED only via `/settle` after `/approvals/{id}/decide` on an approval bound to `task_proof_hash`. `MANUAL_TRANSITIONS` is mirrored in `apps/web/lib/framework/view.ts` (parity-tested).
- **Refs.** `refs.resolve_ref` reads the owning store (knowledge, kernel evidence/decisions, VNEXUS genome, artifact head + byte read-back). Synthetic sources are labelled and never client proof.
- **Gates.** Evaluated from task state; approval subject `agency-gate:{plan}:{gate}` bound to `evaluation_hash`; strictly in order.
- **Assurance.** The five records are immutable `qa_report` artifacts (`assurance/<kind>/<id>`), hash-sealed and integrity-checked on read; they never approve, release or mutate the canonical graph.
- **Release candidates.** A Review may bind delivery's sealed candidate (`release_candidate_ref`). `candidates.inspect` re-checks it read-only:
  - reviewer: an approver who did not start the run;
  - artifact hashes are recomputed from the run payload via the binding layer's own `_workspace_artifact_specs` / `_agency_subject_hash`, never a second hash scheme;
  - the Review never opens a second release decision; the run's approval and delivery stay the authority.
- **Claims.** `claims.py` detects marketing claims by signal, not length. Detection, substantiation (person-linked refs only, never "verified"), policy (always human review) and decision stay separate. Don't change `project_os.knowledge.extract_claims`; its six-word floor is right for ingestion.
- **KPIs.** Only from `measurement` evidence and plan events; a zero denominator is `NOT_MEASURED`.
- **Contracts.** Zod twins in `packages/shared/src/schemas/agencyFramework.ts`, fixture `packages/shared/tests/fixtures/agency-framework.json` (regenerate with `AMC_REGENERATE_FIXTURES=1 pytest services/langgraph/tests/test_agency_framework_contracts.py`).

Release eligibility stays with `agency/delivery`; nothing here dispatches an external effect. Details: `docs/agency-operating-framework.md`.
