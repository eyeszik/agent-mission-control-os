# Publishing providers and the paid-media boundary

## Provider contract

```python
class PublicationProvider(Protocol):
    name: str
    mode: ProviderMode            # DISABLED | DRY_RUN | LIVE
    def prepare(request) -> dict
    def validate(prepared) -> list[str]
    def preview(prepared) -> dict
    def publish(prepared, *, idempotency_key) -> ProviderResult   # may raise ProviderUncertain
    def verify(*, idempotency_key) -> ProviderResult | None       # read-back
    def update(external_ref, prepared) -> ProviderResult
    def remove(external_ref) -> bool
```

Attempt states:

```
SPEC → VALIDATED → AUTHORIZED → APPROVED → EXECUTING → READBACK → RECONCILED → VERIFIED
                                                     ↘ UNCERTAIN ↗      ↘ FAILED / BLOCKED
```

Every attempt persists three receipts, built from the existing execution-proof models:

- a **DispatchPermit**: work order, snapshot hash, dependency version refs, approval refs and tool contract;
- an **ExecutionReceipt**: args hash, idempotency key, attempt number and returned state;
- an **ObservationReceipt**: expected versus observed postcondition, and whether they match.

**Uncertain outcomes** (a timeout or a dropped connection) are resolved by `verify(idempotency_key)`, never by publishing again:

- **Found:** the attempt is RECONCILED, then VERIFIED.
- **Not found:** the attempt is FAILED with `READBACK_NOT_FOUND`. That is safe to retry, because the provider never recorded the key.

A read-back that does not match the request hash fails the attempt.

## What ships

- **`DryRunProvider`** implements the whole contract in process, including idempotent dedup and read-back. A dry run proves the path. It **does not** move the content item to PUBLISHED, and its event says `dry_run: true`.
- **The live provider registry ships empty.** `AMC_PUBLICATION_MODE=live` resolves to no provider unless reviewed code registers one, and production config already rejects `live`.
- `GET /projects/{id}/publications` lists attempts and receipts and reports `DRY_RUN_ONLY` while no live provider exists.

## Activating a real provider: EXTERNAL_ACTIVATION_REQUIRED

1. Implement `PublicationProvider` for one channel. `publish` must accept and honour the idempotency key; `verify` must look the key up on the provider side.
2. Add contract tests in the style of `test_project_content_calendar.py::_FakeLive`. Cover:
   - publish, then verify;
   - uncertain, then found;
   - uncertain, then not found;
   - a read-back mismatch.
3. Cover the operational controls listed in `production-activation.md` §11:
   - OAuth and least-privilege scopes;
   - token rotation and rate limits;
   - allowlists and the kill switch;
   - reconciliation.
4. Register the provider in `publishing._LIVE_PROVIDERS` through a reviewed change, then lift the production readiness rule for that channel.

## Paid media: IMPLEMENTED_FAIL_CLOSED

`POST /projects/{id}/paid-media/plan` produces a plan with:

- objective, offer, audiences and channels;
- campaign architecture (ad groups per channel × audience);
- a creative matrix;
- tracking (a UTM template);
- budget with even pacing;
- frequency cap and creative-fatigue cadence (labelled `PLANNING_DEFAULT`);
- experiments.

It also shows the future mutation sequence and where each step stands:

```
PLAN (COMPLETE) → ACCOUNT_RESOLUTION → EXACT_MUTATION_PREVIEW → BUDGET_AUTHORIZATION (request-only ledger)
→ HUMAN_APPROVAL (required) → IDEMPOTENT_PROVIDER_WRITE → READBACK → RECONCILIATION → RECEIPT → ANALYTICS
```

Every step after PLAN is `NOT_AVAILABLE`. `spend_authority_granted` is always `false`: no planner or LLM output grants spend. Budget requests still go through the existing `/operations/spend/authorizations` ledger, which records requests and never executes them. `analyze_delivery` recommends changes only from *observed* delivery rows. With no rows it reports `NO_OBSERVED_DATA`.
