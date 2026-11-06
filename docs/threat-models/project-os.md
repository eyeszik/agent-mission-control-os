# Threat models: Project OS

Scope: every surface added by the project OS. STRIDE covers security threats; LINDDUN covers privacy threats. Each control names the code that enforces it, and each control is covered by a test in `services/langgraph/tests/test_project_*.py`.

Baseline that is **not weakened** by this work:

- Supabase bearer verification and server-derived principals.
- `amc.tenant_memberships` project scope.
- Approval separation of duties.
- Input sanitization.
- Fail-closed publication and paid-media modes.
- Secret-free configuration surfaces.

## Tenant and cross-brand isolation

| STRIDE | Threat | Control |
| --- | --- | --- |
| Spoofing | Client names a tenant or project it does not own | Tenant comes only from the principal; every project route runs `authorize_project_access`, which checks the workspace's *recorded* tenant |
| Tampering | Writing into another tenant's project id | `ensure_tenant_project` and `create_project_workspace` raise `ProjectOwnershipError` → 403 |
| Info disclosure | Reading another project's artifact via a valid id | Artifacts, threads, items and atoms are re-scoped to the path's project; mismatch → 404 |
| Elevation | Same-tenant member reads a project outside their scope | `allowed_project_ids` is enforced on every route and filters `/projects` and `/portfolio` |

LINDDUN (linkability, identifiability): portfolio rows are counts. M1–M5 memory, conversations and brand canon never cross projects.

## Conversation persistence

| Threat | Control |
| --- | --- |
| Chat state invisible to audit | Every message is appended to `project_events` in the same transaction |
| Fabricated artifact references | `artifact_refs` must name an artifact in the project and an existing version (409 otherwise) |
| Prompt injection via chat into memory | Chat writes M3 WORKING_CONTEXT only; it can never mint BRAND_CANON or an APPROVED decision |

Privacy class: conversation bodies are **CONFIDENTIAL_PROJECT**. Retention follows the project: deleting a project cascades to its threads and messages.

## Uploads and media ingestion

| Threat | Control |
| --- | --- |
| Script-bearing files (SVG/HTML) | Magic-byte sniffing with an allowlist; markup is refused (415) |
| Oversized payloads | 15 MB decoded cap; base64 length bounded by the request schema |
| Arbitrary server file read via video ingest | `output_dir` must resolve inside `AMC_VIDEO_INGEST_ROOT`; `..` traversal is refused (400) |
| Substituted or corrupted bytes | Content-addressed storage; hash re-verified on every read; ingest checks the hash after copying |
| Paid render masquerading as local | Ingest refuses manifests without `zero_paid_api_spend: true` |

## Provider credentials

- No credential value enters events, frontend payloads, logs, workspace exports, artifact metadata or receipts.
- The R2 adapter reports presence booleans only (tested).
- Provider profiles store observed metrics, never keys.
- Registering a LIVE profile is refused.

## Scheduler and publication

| STRIDE | Threat | Control |
| --- | --- | --- |
| Tampering | Publishing an edited item under an old approval | Approval bound to the exact version; an edit cancels jobs; the gate and the worker each re-check |
| Repudiation | Who published what | DispatchPermit, ExecutionReceipt and ObservationReceipt per attempt, hash-stamped |
| DoS / duplication | Overlapping ticks double-publish | Compare-and-set job claim; provider idempotency key; outbox `ALREADY_DELIVERED` |
| Tampering | Client-controlled clock moves jobs early | The tick API uses server time only |
| Elevation | Cron calling providers directly | Ticks only enqueue to the outbox; the worker is the sole adapter caller |

## Paid media

Planning is pure. `spend_authority_granted` is always `false`; budget requests go to the request-only spend ledger; and production configuration rejects `AMC_PAID_MEDIA_MODE != disabled`.

## Memory retrieval

| Threat | Control |
| --- | --- |
| Low-authority data overriding canon | Lower-authority writes are QUARANTINED; resolution ranks by authority, then by project scope |
| Agency-wide memory leaking a brand's facts | M0 is written only through `/agency-memory` by approvers and holds generalized know-how, not project data |
| Learning self-authorization | Protected targets become governance proposals and can never enter promotion; HUMAN_APPROVAL requires an approver |

## Knowledge ingestion

| Threat | Control |
| --- | --- |
| Indirect prompt injection from sources | Raw text is scanned; matches are rejected before any claim is kept |
| Copyright exposure | The source body is never stored; claims are capped; `PROPRIETARY_NO_COPY` keeps nothing |

## Privacy classes and retention

| Data | Class | Retention |
| --- | --- | --- |
| Project workspace, artifacts, versions | CONFIDENTIAL_PROJECT | Lifetime of the project (cascade on delete) |
| Conversations, M3 memory | CONFIDENTIAL_PROJECT | Lifetime of the project |
| Brand canon (M1) | CONFIDENTIAL_BRAND | Lifetime of the project; superseded records retained for lineage |
| Knowledge claims | DERIVED_THIRD_PARTY | Kept with source URI and rights class; rejected items keep only the hash and reasons |
| Learning signals | TENANT_INTERNAL | Append-only hash chain; never cross-tenant |
| Publication receipts | AUDIT | Retained with the attempt |

No customer PII is required by any project OS table. CRM journeys reference content items, not recipients. Recipient handling is out of scope until a reviewed provider exists.
