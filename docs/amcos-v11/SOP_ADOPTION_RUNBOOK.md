# Runbook: adopting a Brand OS SOP in one real project

> **Status: NOT STARTED.** No SOP has been adopted in any real project. Claude prepared this runbook, but it never acts as requester or approver, never impersonates either, and never records an adoption.
> Every `‹…›` field below must be filled in by the owner and checked with the read-only queries in step 0 before anyone acts.

## Adoption record (one per project and SOP)

| Field | Value | Checked by |
|---|---|---|
| Production API base URL | `‹API›` | owner; verified per the production migration playbook §0a |
| Tenant id | `‹TENANT›` | query 0.1 |
| Project id | `‹PROJECT›` | query 0.1 |
| SOP | `‹F01…F08›` (one draft, newly written v0.1, not a recovered original) | `GET /brand-os/sops/‹SOP›` |
| Pinned draft digest (`source_sha256`) | `‹64 hex›` | `data/brand_os_index.v1.json`, `GET /brand-os/sops/‹SOP›` and (once staged) the adoption `artifact_hash` all agree; query 0.4 shows which earlier decisions were for other digests |
| SOP artifact id (`subject_ref`) | `art-‹PROJECT›-foundry-brand-os-‹f0n›` | `artifact_id` from `GET …/sops/‹SOP›/adoption` (use that exact value; do not build it by hand); query 0.4. If that GET returns `"state": "NOT_STAGED"` it has no `artifact_id`: record "not yet staged", take the id from the step 1 response, and use the first-adoption branch of step 0 |
| **Requester**: name, Supabase user id | `‹name›`, `‹uuid›` | query 0.2 |
| Requester role | one of `admin`, `operator`, `owner`, `approver` | query 0.2 |
| **Independent approver**: name, Supabase user id | `‹name›`, `‹uuid›` (must differ from the requester) | query 0.3 |
| Approver role | one of `reviewer`, `approver`, `admin`, `owner` | query 0.3 |
| Pre-adoption database backup id | `‹backup id›` | owner |

The pending migrations, including `20261122_amc_brand_os_pending_approval_unique_v1.sql`, must already be applied to this database, with every stop rule in [production migration playbook](../migrations/production-migration-playbook.md) §0b clear. `APPLIED` from `scripts/db_migrations.py detect` matches by name only, so it is not enough on its own: also confirm, read only, that `idx_amc_approvals_brand_os_pending` is **unique** and keeps its pending/Brand OS predicate (§0b check 6). `AMC_AUTH_MODE` must be `supabase`, and `AMC_DB_RLS_MODE` stays `off`.

## Step 0: verify identities and permissions (read only)

```sql
-- 0.1 the project belongs to the tenant
select project_id, tenant_id from amc.projects where project_id = '‹PROJECT›' and tenant_id = '‹TENANT›';

-- 0.2 requester: active, operator-capable, has the project
select user_id, role, active, allowed_project_ids from amc.tenant_memberships
 where tenant_id = '‹TENANT›' and user_id = '‹REQUESTER_UUID›';
-- expect active = true, role in (admin, operator, owner, approver),
-- and '‹PROJECT›' = any(allowed_project_ids) or '*' = any(allowed_project_ids)

-- 0.3 approver: a different, active user with an approver role in the same tenant
select user_id, role, active from amc.tenant_memberships
 where tenant_id = '‹TENANT›' and user_id = '‹APPROVER_UUID›';
-- expect active = true, role in (reviewer, approver, admin, owner), and ‹APPROVER_UUID› <> ‹REQUESTER_UUID›

-- 0.4 the complete decision history for THIS SOP's artifact in THIS tenant and project.
--     No row limit; stale and rejected rows are kept on purpose; oldest first, deterministic.
select approval_id, status, decision, reviewer, created_at, decided_at,
       subject_ref, subject_version_ref, subject_hash, policy_version, stale_reason, run_id
  from amc.approvals
 where tenant_id = '‹TENANT›' and project_id = '‹PROJECT›'
   and subject_type = 'BRAND_OS_SOP_ADOPTION'
   and subject_ref = '‹ARTIFACT_ID›'
 order by created_at, approval_id;
-- An empty result is expected before the first request, and also when the SOP was never staged in this project.
-- Read each row against ‹digest› and ‹VERSION› (the artifact_version from GET …/adoption):
--   status = 'pending'                                     -> a request is already open: stop, do not open another
--   status = 'resolved' and decision = 'approve' and subject_hash = digest
--     and subject_version_ref = ‹VERSION›                  -> already adopted: stop, nothing to do
--   decision = 'approve' and subject_hash <> digest        -> approval of an EARLIER revision: it does not cover these bytes
--   decision = 'approve' and status = 'stale', or the same digest
--     with another subject_version_ref                     -> an approval of an earlier stored version: it does not cover
--                                                             the current artifact, even when the bytes were restored
--   decision = 'reject', or status = 'stale'               -> keep it in the record; it never counts as approval
```

**First adoption (`GET …/adoption` returns `NOT_STAGED`).** The SOP was never staged in this project, so no adoption approval can refer to it yet and query 0.4 has no `‹ARTIFACT_ID›` to bind. Do not construct the id. Complete 0.1 to 0.3, record the artifact id as "not yet staged", and go to step 1. Its `202` response carries `artifact_id`: run query 0.4 with that exact value straight after step 1 and expect exactly one row, the new `pending` request.

The API's adoption state reads only the newest non-stale row (`list_approvals_for_subject_refs`), so it can hide older or stale decisions. That is why this query, not `GET …/adoption`, is the evidence of prior decisions.

**Stop if:** any check fails; query 0.4 shows a pending row or a current (resolved, same digest, same `subject_version_ref`) approval; requester and approver are the same person; or either person holds a shared or service account. One human per identity.

## Step 1: the requester asks (requester's own session)

UI: there is no SOP screen, so the request goes through the API, using the requester's own signed-in session token.

```bash
curl -sS -X POST "‹API›/brand-os/projects/‹PROJECT›/sops/‹SOP›/adoption" \
  -H "Authorization: Bearer $REQUESTER_SESSION_TOKEN" -H "X-AMC-Tenant: ‹TENANT›" -H "Idempotency-Key: $(uuidgen)"
```

**Expect 202** with:

- `"state": "PENDING"`;
- `artifact_hash == source_sha256 == ‹digest›`;
- `grants_runtime_authority: false`.

Record `approval_id`, `artifact_id` and `artifact_version`.

- A retry with the same key replays the first response. A new key while the request is pending returns the same `approval_id`.
- **409 `APPROVAL_CONFLICT`:** a pending approval exists for other bytes. Stop and investigate.

## Step 2: the independent approver decides (approver's own session)

UI: **Agency → Approvals**. The item reads *"Adopt this newly written Brand OS SOP for this project"*. Before choosing **Approve…** or **Reject…**, check:

- the shown hash equals `‹digest›`;
- "Requested by" is the requester's identity.

The equivalent API call:

```bash
curl -sS -X POST "‹API›/approvals/‹APPROVAL_ID›/decide" -H "Authorization: Bearer $APPROVER_SESSION_TOKEN" \
  -H "X-AMC-Tenant: ‹TENANT›" -H "Idempotency-Key: $(uuidgen)" -H "Content-Type: application/json" -d '{"decision":"approve"}'
```

A **403** means the approver is the requester or lacks the role. That is the separation-of-duties guard; do not work around it.

## Step 3: verify and keep the audit evidence

```bash
curl -sS "‹API›/brand-os/projects/‹PROJECT›/sops/‹SOP›/adoption" -H "Authorization: Bearer $REQUESTER_SESSION_TOKEN" -H "X-AMC-Tenant: ‹TENANT›"
```

Expect `"state": "ADOPTED"`. Then capture the evidence (read only):

```sql
-- the decision row: resolved, approved, decided by the approver
select approval_id, status, decision, reviewer, decided_at, subject_ref, subject_version_ref, subject_hash, policy_version
  from amc.approvals where approval_id = '‹APPROVAL_ID›';
-- expect status = 'resolved', decision = 'approve', reviewer = '‹APPROVER_UUID›',
--   subject_hash = '‹digest›', policy_version = 'amc-brand-os-sop-adoption/v1'

-- the anchor run. One run is shared by every request for this artifact and keeps the FIRST request's metadata,
-- so initiated_by is the requester only when this is the artifact's first approval; the event below is per request.
select r.run_id, r.status, r.metadata->>'initiated_by' as first_requester, r.metadata->>'artifact_hash' as first_hash
  from amc.runs r join amc.approvals a on a.run_id = r.run_id where a.approval_id = '‹APPROVAL_ID›';

-- who asked, and the activity trail: the APPROVAL_REQUIRED event for this approval names its requester as actor
select sequence, event_type, actor, subject_ref, created_at from amc.project_events
 where project_id = '‹PROJECT›' and payload->>'approval_id' = '‹APPROVAL_ID›' order by sequence;
-- expect an APPROVAL_REQUIRED row with actor = '‹REQUESTER_UUID›'
```

Store, with the adoption record above: these three result sets, the step 1 and step 3 API responses, and the timestamps. Any other state means it is **not** adopted:

| State | Meaning and next step |
|---|---|
| `REJECTED` | A new request (step 1 again) opens a new pending approval on a run of its own, with that request's requester as the separation-of-duties anchor, so it can be decided normally. Requires a backend that includes the per-request approval run fix (`test_approval_run_per_request.py`); on an older backend `/approvals/{id}/decide` returns 409 for it: stop and escalate, do not work around it. |
| `STALE` or `REVISION_CHANGED` | The stored bytes changed. Do not rely on this approval; re-request. |
| `STAGED_NO_APPROVAL` | Repeat step 1 once; it reuses the artifact and opens one approval. |

## Scope of the decision

The decision covers only these exact bytes, in this one project. It does not carry over to other projects or to a new draft revision. It grants no runtime authority, and it never publishes, spends or messages anyone. The advisory step companion is not part of the adoption.
