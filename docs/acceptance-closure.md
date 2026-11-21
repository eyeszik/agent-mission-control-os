# Complete-package acceptance closure

Four acceptance criteria, each with its source of truth, the command that checks it, and where its evidence lives. The sealed results for one commit are in `validation_report.json` (`acceptance_closure`) and `tool_proof_log.json`.

| # | Criterion | Source of truth | Gate / test | Evidence |
| --- | --- | --- | --- | --- |
| 0 | Canonical AGM binding | `agency/operating_framework/data/catalog.seed-v1.json` (SHA-256 pinned) | `python scripts/acceptance/discover.py` (exit 2 = `BLOCKED_AMBIGUOUS_SPEC`) | `acceptance/discovery_manifest.json` |
| 1 | Ordered SOP contracts | `services/langgraph/agency/sop/data/sop_registry.v1.json` | `verify_repository_invariants.py` (contiguity, acyclicity, dataflow, 100% stage coverage, fixture parity); `test_sop_contracts.py`; `packages/shared/tests/sop.test.ts` | runtime guard `agency/sop/guard.py`, wired in `graph/agency/build.py` |
| 2 | Source-to-AGM reconciliation | `acceptance/source_trace_map.json` (reviewed, hash-pinned) | `python scripts/verify_source_reconciliation.py`; `test_source_reconciliation.py` | `acceptance/reconciliation_report.json` |
| 3 | Production migration mappings | `supabase/migrations`, `supabase/rollback` | `test_migration_roundtrip.py` (needs `AMC_EPHEMERAL_POSTGRES_DSN`) | `acceptance/migration_mapping.json`, [migration playbook](migrations/production-migration-playbook.md) |
| 4 | Executed tests | this commit | the full matrix in `validation_report.json` | `acceptance/logs/` |

## SOP registry

The registry orders every live stage of both pinned topologies (`agency/v1-legacy`, `agency/v2-contract`) and four recovery procedures:
- degraded non-delivery;
- stale-edit 409;
- crash reconciliation;
- rejection.

Every step names:
- its owner (an N3 role, or `server`, or `membership:approver`) and its RoleOS skill;
- its pre- and post-conditions, input and output schemas, and idempotency formula;
- its gate binding and retry/lease bounds;
- its failure disposition (`FALLBACK_DEGRADED` or `BLOCKED`, never a silent pass);
- the code that enforces it and the tests that prove it.

`verify_against_code()` resolves every one of those references against the tree.

The guard runs each stage only when its required upstream state exists, and fails the run if a stage drops its declared output. It is behaviour, not topology, so `graph_fingerprint` and paused runs are unaffected.

## Reconciliation

The reconciler checks three kinds of source:
- **Root planning sources.** 87 items from `requirements_extract.json`, `assumption_ledger.json`, `claim_registry.json` and `constraint_ledger.yaml`. Each carries a JSON-pointer id and a reviewed content hash.
- **The AGM module table.** The 24 rows in `docs/agency-operating-framework.md`, reconciled field by field against the catalog and `bindings.py`.
- **Cross-stack parity.** Python, TypeScript and OpenAPI must agree on:
  - stages, run states and error codes;
  - SOP ids and AGM ids;
  - the N1/N2 ontology.

Statuses are `MATCHED | PARTIAL | MISSING | DRIFTED | PROVIDER_GAP | NOT_MEASURED`. The gate fails when:
- a source has no mapping entry (orphan);
- a reference does not resolve;
- an item is `MISSING`;
- a source changed since review;
- a `DRIFTED` item has no recorded resolution;
- any parity check fails.

The root planning bundle stays `draft_until_verified`. A planning item that the code later superseded is recorded as resolved `DRIFTED` with a pointer to the authority that replaced it; it is not marked `MATCHED`.
