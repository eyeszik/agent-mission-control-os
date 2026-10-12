# Runbooks

All procedures assume the sandbox-only deployment this change ships. None of them enables LIVE execution, and
none should be read as a way to.

## R1. Emergency freeze

**When:** you suspect a misbehaving action, a compromised account, or anything you want to stop at once.

1. Choose the scope:
   - **Workspace:** Settings → Incident freeze → reason → "Freeze workspace". Or call `POST /actions/freezes`
     with `{"scope_kind": "TENANT", "reason": "…"}`.
   - **One project:** the same, with `"scope_kind": "PROJECT", "scope_ref": "<project_id>"`.
   - **The whole deployment:** set `AMC_ACTIONS_FREEZE=1` and restart the API.
2. Who may freeze: owner, admin, operator, approver or reviewer.
3. Effect: every new dispatch is refused with 423. Reconciliation (`Check outcome`, the recovery sweep) keeps
   working, so in-flight work can still be resolved.
4. Lifting needs an owner or admin, and not the person who froze it (`POST /actions/freezes/{id}/lift`). A
   system freeze is lifted only by unsetting the variable.

## R2. Work stuck in "Outcome unknown" or "Dispatching"

1. Missions → Recovery workbench lists UNKNOWN, RECONCILING, NEEDS_HUMAN and FAILED actions, with retry
   eligibility and the evidence that decides it.
2. For one action, use "Check outcome" (`POST /actions/{id}/reconcile`). It reads the provider back by effect
   key. It never re-sends.
3. For everything stale, run `POST /actions/recovery/sweep` (owner, admin, operator, approver or reviewer). This
   reconciles leases that expired mid-dispatch and expires overdue actions.
4. NEEDS_HUMAN: compare the expected state and payload hash with the sandbox record in the evidence view. Then
   reconcile again, or leave it FAILED. Never mark it done by hand. There is no route to do so.
5. FAILED and retry-eligible: "Retry" (`POST /actions/{id}/retry`), at most 3 attempts in total.

## R3. Budget ceilings

There is no API to change ceilings; that is deliberate. An operator with database access sets them:

```bash
python -c "from services.langgraph.persistence.actions import set_budget_policy as s; \
s(tenant_id='<tenant>', scope_kind='PROJECT', scope_ref='<project_id>', currency='USD', ceiling_minor=50000, actor='<operator>')"
```

- **Scopes:** `ACTION` (with `scope_ref='*'`), `PROJECT`, `CLIENT`, `TENANT_DAY`, `TENANT_MONTH`.
- **Without any applicable policy**, spend is blocked with `NO_BUDGET_POLICY`.
- **Before changing a ceiling**, check it with Settings → Policy simulator (`POST /actions/budget/simulate`).
- **Committed amounts** are the amounts read back from the sandbox ledger. No real settlement exists or is
  claimed.

## R4. Delivery-manifest signing key

- Set `AMC_DELIVERY_SIGNING_KEY` to a random value of at least 32 characters, held in the platform's secret
  store. Never commit it.
- Without it, manifests are produced `UNSIGNED` with the reason. They are still hash-verifiable via
  `POST /agency-os/deliverables/verify-manifest`.
- **Rotation:** set the new key and restart. Manifests signed with the old key then fail signature verification,
  though their hash still verifies. Keep the old key where your process requires re-verification of earlier
  manifests.

## R5. Client offboarding

1. Clients → open the client → offboarding report (`GET /agency-os/clients/{id}/offboarding`). It lists open
   actions, missions and pending approvals.
2. An owner or admin starts offboarding (`POST …/offboarding`). New work for the client's projects is blocked from now on.
3. Close or cancel the open work, then an owner or admin archives (`POST …/archive`). Archiving refuses while
   open work remains or before offboarding has started. Records are kept for audit; nothing is deleted.

## R6. Requests to "turn on" a provider or LIVE

There is no switch. `live_enablement()` returns `DISABLED` whatever is configured. Setting `AMC_ACTIONS_LIVE` is
reported as ignored. Enabling a real provider requires all of the following:

- a reviewed adapter implementing describe/validate/prepare/execute/observe/reconcile/compensate against the real
  API;
- a code change to the LIVE gate;
- verified identity and step-up authentication for R5;
- credentials held outside the repository;
- the production activation checklist in `docs/production-activation.md`.

Each of these is a separate, approved change.

## R7. Suspected tampering

- **Action history:** the evidence view shows the chain as broken (`chain.intact = false`). Freeze the project
  (R1), then preserve the database.
- **Artifact bytes:** export excludes the item with `CONTENT_HASH_MISMATCH`. Re-produce the artifact and get it
  approved again.
- **Manifest:** `verify-manifest` reports `hash_matches` or `signature_valid` as false.
