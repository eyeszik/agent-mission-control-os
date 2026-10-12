# External Action Risk Policy v1 (proposed)

Status: design specification; no live adapters or policy changes are enabled by this document.

## Purpose and canonical integration
Extend, rather than replace, server-derived identity, tenant/project authorization, Project OS artifact versions, approval decisions, execution-fabric permits/receipts, and idempotency. This is a proposed policy overlay, not an alternative authority store. Current execution fabric remains LOCAL/SANDBOX and fail-closed for external consequential effects. Existing release guards remain authoritative.

## Risk classes

| Class | Effect | Examples | Minimum authorization |
|---|---|---|---|
| R0 OBSERVE | Read external information | public search, metrics retrieval, repository inspection | Tenant-scoped credentials where data is private; purpose, privacy and rate limits |
| R1 INTERNAL_CREATE | Local artifact generation | code patch in sandbox, internal file, creative assets, research draft | Work-order contract, local sandbox limits, output validation |
| R2 EXTERNAL_DRAFT | Reversible unpublished remote write | CMS draft, Git branch/PR, draft CRM record, staging upload | Scoped adapter, tenant/project authorization, verified target, idempotency, reversible write plan |
| R3 EXTERNAL_RELEASE | Audience-visible or outbound effect | public website publication, production deployment, client email, social post | Human approval bound to exact payload, destination, artifact hash and expiry; read-back verification |
| R4 FINANCIAL | Monetary commitment or financial change | billable API usage, paid hosting, advertising budget, subscription change | Named financial approver, vendor/account/currency/time-bound spend ceiling, reservation and reconciliation |
| R5 SENSITIVE_DESTRUCTIVE | Critical irreversible or sensitive mutation | delete production records, transfer ownership, revoke privileged access, substantial refund | Step-up authentication, independent approver, recovery/compensation analysis, explicit blast radius |
| R6 GOVERNANCE_CHANGE | Change who/what may authorize future effects | alter policy, approver roles, production credentials, trust configuration | Privileged independent review, immutable audit, policy version pin, staged rollout and rollback |

An action may satisfy multiple classes: choose the strongest applicable controls. Risk is derived server-side from operation + target + environment + sensitivity + reversibility + audience + financial exposure + blast radius. Caller-supplied class never lowers effective risk. R0 reads of protected data may require stronger approval; R2 draft writes may be high risk if they expose data or trigger notifications. Classify provider behavior rather than HTTP verb.

## Mandatory action descriptor
```json
{
  "action_id": "uuid",
  "tenant_id": "server-derived",
  "project_id": "server-derived",
  "actor_id": "server-derived",
  "adapter_id": "registered-version",
  "operation": "provider.operation",
  "effect_class": "R0|R1|R2|R3|R4|R5|R6",
  "target": {"provider": "string", "account": "string", "resource": "string", "environment": "string"},
  "artifact_ref": "project-artifact@version",
  "payload_sha256": "64-hex",
  "approval_ref": "server-issued-or-null",
  "policy_version": "external-action-risk/v1",
  "expires_at": "ISO8601",
  "idempotency_key": "tenant+target+operation+payload+policy",
  "budget": {"currency": "USD", "max_amount": "decimal-string", "period": "ISO8601-interval"},
  "reconciliation": {"read_back_operation": "string", "expected_state_hash": "64-hex"},
  "compensation": {"available": false, "operation": null}
}
```
For nonbillable actions, budget is null. Secrets and sensitive payloads belong in protected storage; logs retain references/digests, not raw values.

## Execution state machine
PROPOSED -> VALIDATED -> APPROVAL_PENDING (if required) -> AUTHORIZED -> PREPARED -> DISPATCHING -> RECONCILING -> EXECUTED_VERIFIED | EXECUTED_UNVERIFIED | NOT_EXECUTED | FAILED | UNKNOWN.
An ambiguous timeout enters UNKNOWN and reconciles provider state before retry. A provider receipt alone is EXECUTED_UNVERIFIED; an independent read-back is needed for EXECUTED_VERIFIED. Local artifact success is not external delivery.

## Enforcement
1. Resolve authenticated actor, tenant, project, memberships, and allowed resources on server.
2. Resolve registered adapter contract and canonical effect classification; refuse unregistered operations.
3. Validate exact artifact version, dependency hashes, destination, policy version, approvals, expiration, separation of duties and financial ceiling.
4. Reserve idempotency and budget before dispatch; persist intent and permit.
5. Dispatch only if a reviewed live adapter is explicitly enabled for this operation and environment. Preserve existing LIVE_GATED behavior until such implementation passes security review.
6. Persist receipt; independently read external state; reconcile unknown outcomes before retries; record spend only from reconciled provider facts.
7. Invalidate approvals when payload, artifact, destination, permission, or policy changes. Preserve append-only evidence.
8. Escalate policy mutations (R6) and unresolvable ambiguous outcomes. No generic self-approval in production.

## Policy examples
- Public web search: R0; private analytics retrieval: R0 plus data-access checks.
- Local SVG/logo output: R1; CMS draft: R2; published page: R3.
- Git PR: R2; merge to production with auto-deploy: R3 or higher.
- API call with paid usage: R4 overlay even if read-only.
- Delete a draft: R2 or R5 depending on recoverability and sensitivity.
- Change approval rules: R6, even without an immediate external API call.

## Integration points (verify exact symbols before implementation)
- `services/langgraph/agency/execution_fabric/contracts.py`: risk classification and eligibility overlay; retain existing LOCAL/SANDBOX guard.
- `services/langgraph/agency/skills/dispatcher.py`: canonical capability and adapter metadata validation.
- `services/langgraph/api/routes/approvals.py`: exact-subject approvals and separation of duties.
- `services/langgraph/persistence/`: tenant-scoped intents, receipts, and approval/audit records.
- `services/langgraph/agency/project_os/`: artifact lineage, release boundary, provider adapters.
- `apps/web/`: show risk, destination, payload diff, cost ceiling, approver, and proof status.

## Acceptance tests
1. Cross-tenant and client-supplied authority injection rejected.
2. R0 private read requires scoped access; paid read gets R4 controls.
3. R1 output never implies external publication.
4. R2 provider draft creation deduplicates on retry and is verified remotely.
5. R3 approval becomes stale after content or destination change.
6. R4 cannot exceed per-action and aggregate reserved spend caps.
7. R5 requires step-up and independent approval; missing recovery evidence escalates.
8. R6 governance edits cannot authorize themselves.
9. Timeout after provider success reconciles without duplicate effect.
10. Disabled/missing adapter stays blocked despite approved action.
11. Audit receipts are tenant-scoped, immutable, hash-linked, and independently verifiable.
12. Production mode remains disabled until explicit reviewed adapter activation and smoke tests.

## Delivery sequence
Phase A: additive risk schema + pure classification policy + unit tests.
Phase B: audit/read-only adapter and sandbox draft adapter with integration tests.
Phase C: approval UI and evidence/read-back receipts.
Phase D: one scoped production provider with reviewed rollout.
Phase E: financial and destructive adapters only after independent approval and reconciliation tests.

## Non-goals
No automatic live publication, spending, account mutation, migration, or production authorization is granted by this specification. No claim of deployed functionality is made.
