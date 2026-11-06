# Project OS

**PROJECT is the durable unit of system state.** Runs are executions within projects. Chats are interfaces into projects. The filesystem workspace is a materialized view of a project. External providers are execution adapters. Memory is scoped knowledge, not hidden global state.

Every new subsystem composes through:

```
tenant_id → project_id → (brand / campaign / workstream) → artifact_id → version_ref
  → evidence/source refs → dependencies → approval scope → execution receipt
  → observation receipt → measurement → learning signal
```

Companion documents:

- [`content-calendar.md`](content-calendar.md): content operations, calendar, scheduler, CRM journeys.
- [`memory-knowledge.md`](memory-knowledge.md): memory scopes, KnowledgeOps, governed self-improvement.
- [`creative-production.md`](creative-production.md): DAM, the video bridge, workstreams, brand stewardship.
- [`publishing-providers.md`](publishing-providers.md): the publication contract and the paid-media boundary.
- [`portfolio.md`](portfolio.md): portfolio command center and the cost × quality router.
- [`threat-models/project-os.md`](threat-models/project-os.md): STRIDE/LINDDUN threat models and privacy classes.

## Status

| Capability | Status | Notes |
| --- | --- | --- |
| Project workspaces, initializer, lifecycle | IMPLEMENTED | `persistence/projects.py`, `POST /projects` (idempotent) |
| Project activity stream | IMPLEMENTED | `project_events`; runs, chats, artifacts, approvals and publication all append |
| Artifact graph v2 (versions, compare, restore, branch, merge, replace master) | IMPLEMENTED | metadata over the N4 registry, not a second registry |
| Dependency invalidation + remediation queue | IMPLEMENTED | N4 `propagate_artifact_change` + `artifact_edit_requests` |
| Object storage, local content-addressed | LOCAL_ONLY | `agency/project_os/storage.py` |
| Object storage, Cloudflare R2 | EXTERNAL_ACTIVATION_REQUIRED | adapter describes the binding and fails closed; production config rejects it |
| Workspace mirror, legacy dual materialization | IMPLEMENTED | `projects/<tenant>/<project>/`, hash-verified |
| Conversations | IMPLEMENTED | every message is also a project event |
| Prompt ledger + `07_prompts/` mirror | IMPLEMENTED | DB is authority; ALL_PROMPTS.md/index/lineage are exports |
| Content operations, calendar, scheduler | IMPLEMENTED | see content-calendar.md |
| Publication | DRY_RUN_ONLY | no live provider is installed |
| Paid media | IMPLEMENTED_FAIL_CLOSED | planning only; spend authority never granted |
| CRM sending | DRY_RUN_ONLY | journeys reuse the scheduler and the dry-run publication path |
| Memory, KnowledgeOps, learning governance | IMPLEMENTED | knowledge *fetching* is NOT_AVAILABLE (callers supply fetched text) |
| Video render (FreeVideoForge) | LOCAL_ONLY | requires Pillow + FFmpeg on the machine; discovered, never assumed |
| Portfolio, brand drift, provider routing | IMPLEMENTED | |

## Capability disposition

What already existed decided what was built. Nothing below duplicates an existing primitive.

| Spec concept | Disposition | Canonical owner |
| --- | --- | --- |
| Artifact registry, lineage, branching | REUSE + EXTEND | N4 `agency_artifacts` + `artifact_dependencies`; `artifact_versions` adds the history the row overwrites |
| Artifact types | EXTEND (one type) | N1 gains `media_asset` (creative); content kinds and workstream stages are *subtypes* of existing types |
| Approval separation of duties | REUSE | `security/approval_authority.assert_may_decide` (generalized from run approvals) |
| Idempotency | REUSE | `persistence/idempotency.py` for project creation; scheduler/publication keys for delivery |
| Outbox, receipts | REUSE | trust-kernel outbox + `OutboxDispatcher`; `DispatchPermit`/`ExecutionReceipt`/`ObservationReceipt` models |
| Learning quarantine | REUSE + persist | compiled-agency `LearningLedger`, replayed per tenant from `learning_signals` |
| Invalidation/blast radius | REUSE | N4 propagation (hard → invalidated, soft → review_required) + stale approvals + lineage remediation |
| Cinematic IR, FreeVideoForge | INTEGRATE | `agency/project_os/video.py` translates; neither is rewritten |
| UI/UX compiler, DTCG tokens | REUSE | workstream stages map onto them; no second token compiler |
| Scheduler | CREATE_NEW (one) | `scheduled_jobs` + `run_scheduler_tick`; publish, refresh and CRM journeys share it |
| Memory store | CREATE_NEW (one) | `memory_records` with an explicit authority order |
| Publication provider contract | OPERATIONALIZE + FAIL_CLOSED_EXTERNAL | dry-run provider; live registry ships empty |
| Paid-media | FAIL_CLOSED_EXTERNAL | planning + existing spend-authorization ledger |
| R2 | FAIL_CLOSED_EXTERNAL | `UNVERIFIED_EXTERNAL_BINDING` |

## Storage authority

Three layers, one authority each:

1. **Relational canonical state** (SQLite locally, PostgreSQL in production) owns identity, tenant/project ownership, state machines, versions, lineage, approvals, rights, schedules, jobs, receipts, memory, metrics and dependencies.
2. **Object storage** owns bytes. It is content-addressed (`sha256`), so a write is idempotent and every read re-verifies the hash. `storage_objects` records what should exist, and `POST /projects/{id}/storage/reconcile` marks objects PRESENT or MISSING against what the backend actually holds.
3. **The human-readable workspace mirror** is never authority. Every file in it can be regenerated from the relational state.

## Workspace layout

```
<AMC_EXPORT_ROOT>/projects/<tenant>/<project>/
  00_admin/ … 21_archive/        semantic folders, created lazily
  .amc/runs/<run_id>/            run materializations (workspace-package.json, mirror-index.json)
  .amc/manifests/project-manifest.json
  .amc/objects/<hh>/<sha256>     local object storage
```

Folder names are a closed vocabulary (`WORKSPACE_FOLDERS`) mirrored in TypeScript. Path segments are validated, so nothing can address outside the project root (`WorkspacePathError`).

### Migration from run-first exports

The legacy exporter still writes `<root>/<brand>-<run>/`, and existing artifact bindings still point there. Each run is then **dual-materialized** into the project workspace (`mirror_run_export`):

- each file is copied into its semantic folder (`business/` → `03_strategy/business/`, `branding/design-system/` → `06_design/design-system/`, and so on);
- each copy is hash-verified against its source;
- the result is reported as `project_workspace` on the run response.

Canonical artifact hashes are computed from payloads, not from either copy on disk, so they are identical whether or not the mirror runs. An interrupted mirror is repaired by re-running it (tested). The run-first layout is not retired: the browser E2E suite and `FileOrganizationPanel` still read `workspace_export`, and the panel now also shows the project mirror.

## Project initializer

`POST /projects` with an `Idempotency-Key`:

1. Validates the tenant and the caller's role (owner, admin or operator).
2. Allocates an immutable `project_id`. A generated id requires tenant-wide project scope; an explicit id must be inside the caller's scope and must not belong to another tenant.
3. Assigns a mutable slug, unique per tenant, and display metadata.
4. Writes the canonical rows in one transaction: the tenant/project registry, `project_workspaces`, the manifest (with its hash), the first `PROJECT_CREATED` event and the `project.charter` memory namespace.
5. Creates the project's N4 engagement (`eng-project-<id>`), which hosts the project's artifacts.
6. Materializes the mirror. A mirror failure is reported, never fatal.

Replaying the same key returns the same response. Reusing the key with different input returns 409. A project whose runs predate workspaces is given a workspace the first time a run touches it.

## Artifact graph v2

`ArtifactMetadataV2` is the v2 view of an N4 artifact. It carries media, channel, locale, dimensions, duration, master/variant links, source/evidence/prompt/dependency refs, storage URIs, approval state, and rights and provenance refs.

- **Edits are compare-and-set on the version.** `record_artifact_revision(expected_version=…)` updates `WHERE version = ?`, so of two concurrent edits from the same head, exactly one wins. The other gets 409 (`StaleArtifactVersionError`).
- **One master, many derivatives.** `branch` creates a derivative that is `variant_of` its source and hard-depends on it, and shares its `master_artifact_id`.
- **Replacing a master propagates.** `merge(replace_master=true)` or any upstream revision invalidates the hard descendants (and marks soft ones `review_required`). It also stales their approvals and opens one remediation edit request per invalidated artifact. The response's `blast_radius` names exactly what changed.
- **Compare** returns content, location and fingerprint flags, the metadata diff, a unified text diff for text objects, and a *metadata-only* visual diff for images and video (no pixel diffing is claimed).
- **Restore** writes a new version whose content is an old version's. History is append-only.

## API and schema evolution

- **Routes:** `api/routes/projects.py`, `api/routes/project_ops.py` and `api/routes/portfolio.py` (60 paths under `/projects`, `/portfolio`, `/agency-memory`, `/providers`, `/learning`, `/project-os`). They appear in the canonical OpenAPI generated by FastAPI.
- **Contracts:** Pydantic models in `agency/project_os/models.py`; strict Zod twins in `packages/shared/src/schemas/projectOs.ts`. Vocabulary parity is enforced by `scripts/verify_ontology_parity.py`. Object parity is enforced by `packages/shared/tests/fixtures/project-os.json`, which `tests/test_project_os_contracts.py` regenerates from the models and fails on drift (`AMC_REGENERATE_FIXTURES=1` to update).
- **Database:** every table exists in SQLite migration v13 and in `supabase/migrations/20261001_amc_project_os_v1.sql`. The contract test checks that their CHECK constraints match the Python vocabulary.
- **Compatibility policy:** existing response fields are never removed or renamed. New data is added as optional fields (for example `project_workspace` on runs). A breaking change requires a new route or a versioned schema (`amc-workspace/v2`, `amc-project-os/v1`).
- **Rollback:** the migration only creates new tables, so rolling back the application leaves them unused and harmless. Dropping them is a deliberate, separate operation.

## Reproducibility

`ReproducibilityRecord` records:

- source hashes and prompt hashes;
- the schema version, provider, model and seed;
- the generation-config hash and tool-contract version;
- the environment signature and execution-args hash;
- input refs and the output hash;
- the **real guarantee**: `BYTE_IDENTICAL`, `DETERMINISTIC_PIPELINE`, `SEEDED_BEST_EFFORT` or `NON_DETERMINISTIC`.

FreeVideoForge runs are `SEEDED_BEST_EFFORT` when seeds are recorded. Nothing claims byte-identical output from a nondeterministic provider.

## Reliability contracts

`GET /project-os/status` reports `reliability_contracts()`. Numeric objectives (availability, p95/p99 latency, scheduler delay, queue age, publication delay, recovery time) exist only when an operator sets `AMC_SLO_<SERVICE>_<METRIC>` after measuring a baseline. Until then they read `GAP_NO_BASELINE`, the same rule as [`production-slo-contract.md`](production-slo-contract.md).

The mechanisms report the constants their code enforces:

| Mechanism | Status |
| --- | --- |
| Bounded retry (≤ 3 outbox attempts) | IMPLEMENTED |
| Dead letter (FAILED outbox and jobs are kept) | IMPLEMENTED |
| Duplicate-delivery prevention | IMPLEMENTED |
| Readback reconciliation | IMPLEMENTED |
| Object reconciliation | IMPLEMENTED |
| Resource limits | IMPLEMENTED |
| Circuit breaker | NOT_IMPLEMENTED (no live provider to break against) |
| Backups | EXTERNAL_ACTIVATION_REQUIRED |
| Restore validation, RTO, RPO | GAP_NO_BASELINE |

## Known limits

- `DatabaseReliabilityStore.state` reads whole trust-kernel tables. Each scheduler delivery enqueues through it, so delivery throughput degrades as those tables grow. This is a pre-existing full-scan pattern, and it is also why local runs against a large `amc_local.db` are slow.
- The scheduler has an API trigger (`POST /projects/{id}/scheduler/tick`, server time only) and a function (`run_scheduler_tick`). No always-on worker or cron is deployed. Wiring one is an activation step (see `production-activation.md`).
