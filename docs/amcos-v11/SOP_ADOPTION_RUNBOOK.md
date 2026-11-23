# Runbook: adopting a Brand OS SOP in a real project

Two different people carry this out. Claude never performs the approver role.

| Role | Who | Needs |
|---|---|---|
| **Requester** | an operator for the project | a role in `admin`, `operator`, `owner` or `approver`, and project access, through an active `amc.tenant_memberships` row |
| **Approver** | someone other than the requester | a role in `reviewer`, `approver`, `admin` or `owner` in the same tenant |

The decision covers **only** the exact pinned bytes of one newly written draft (F01–F08), in one project. It is not a recovered Brand OS 3.0 original. It grants no runtime authority, and it never publishes, spends or messages anyone.

## Before you start

1. The production API and database are live, the pending migrations are applied (including `20261122_amc_brand_os_pending_approval_unique_v1.sql`), and `AMC_AUTH_MODE=supabase`.
2. Pick the project id and the SOP (`F01`–`F08`). Read the draft first: `GET /brand-os/sops/<SOP>` returns its ordered steps, its digest and its AGM dispositions.
3. Both people sign in through the web app. Each request carries `Authorization: Bearer <their own session token>`. If a person belongs to more than one tenant, the request also carries `X-AMC-Tenant: <tenant id>`. Never share or paste tokens.

## Step 1: the requester asks for adoption

```bash
curl -sS -X POST "$API/brand-os/projects/$PROJECT/sops/$SOP/adoption" -H "Authorization: Bearer $REQUESTER_TOKEN" -H "Idempotency-Key: $(uuidgen)"
```

Expect **202** with `"state": "PENDING"`, an `approval_id`, and `artifact_hash == source_sha256`. Check that `decision_covers` names the SOP and the project.

- **Retrying is safe.** The same key replays the first response. A new key while the request is PENDING returns the same `approval_id`. A concurrent duplicate cannot open a second approval, because the database refuses it.
- **409 `APPROVAL_CONFLICT`** means a pending approval exists for different bytes. Stop and investigate; do not retry in a loop.

## Step 2: the approver decides

1. In the web app, open **Approvals**. The item reads *"Adopt this newly written Brand OS SOP for this project"*.
2. Compare the shown content hash with `source_sha256` from step 1.
3. Choose **Approve…** or **Reject…** and confirm. The API equivalent:

```bash
curl -sS -X POST "$API/approvals/$APPROVAL_ID/decide" -H "Authorization: Bearer $APPROVER_TOKEN" -H "Idempotency-Key: $(uuidgen)" -H "Content-Type: application/json" -d '{"decision":"approve"}'
```

A **403** here means the approver is the requester or lacks an approver role. That is the separation-of-duties guard working, not a fault.

## Step 3: confirm

```bash
curl -sS "$API/brand-os/projects/$PROJECT/sops/$SOP/adoption" -H "Authorization: Bearer $REQUESTER_TOKEN"
```

| State | Meaning |
|---|---|
| `ADOPTED` | Done. `grants_runtime_authority` is `false`. |
| `REJECTED` | A new request opens a new decision. |
| `STALE` or `REVISION_CHANGED` | The stored bytes no longer match the pinned draft. Do not use this approval; re-request. |
| `STAGED_NO_APPROVAL` | A failure happened between storing and opening the approval. Repeat step 1 once; it reuses the artifact and opens exactly one approval. |

## Record

Keep, per adoption: project id, SOP id, `source_sha256`, `approval_id`, the requester and approver identities, the timestamps, and the final state. Adoption of a project's SOP does not carry over to any other project.
