# ACE v100 — Increment 01: REQUEST/ACCUT pilot

**Status: opt-in, not a completed ACE v100 implementation.** No existing controllers, databases, workflows, releases, or effect permissions are modified.

## Implemented

- `services/langgraph/quality/request_accut.py`: validated REQUEST intent schema with canonical SHA-256 digest; ACCUT quality thresholds; row-level quarantine reason codes; read-only shadow comparison.
- `services/langgraph/tests/test_request_accut.py`: nine tests covering valid and incomplete intent, accuracy UNKNOWN, duplicate and stale records, invalid timestamps, empty datasets, noncanonical JSON, shadow comparison and invalid thresholds.

The user-supplied paper by Abhishek Anand (2025), *Accelerating Data Engineering Productivity with Agent-Based Automation and Natural-Language Interface*, DOI `10.70315/uloap.ulirs.2025.0204008`, describes REQUEST (Reason, Entities, Questions, Units, Events, Scope, Trade-offs), ACCUT (Accuracy, Correctness, Completeness, Uniqueness, Timeliness), quarantine, shadow-mode pilots, and four logical layers (semantic gateway, agent manager, unified execution environment, feedback). These are design inputs, not demonstrated runtime performance for this repository.

## Example

```python
from datetime import datetime, timezone
from services.langgraph.quality.request_accut import (
    RequestIntent, AccutPolicy, validate_accut, compare_shadow,
)
intent = RequestIntent.from_mapping({
    "reason": "summarize orders", "entities": ["orders"],
    "questions": ["revenue"], "units": ["USD"],
    "events": ["paid"], "scope": "tenant_a",
    "tradeoffs": ["cost over latency"],
})
envelope = intent.envelope()
policy = AccutPolicy(("id", "amount"), "id", 60, min_accuracy=0)
result = validate_accut(
    [{"id": "1", "amount": 5, "observed_at": "2026-10-13T00:00:00Z"}],
    policy, observed_at=datetime(2026, 10, 13, tzinfo=timezone.utc),
)
shadow = compare_shadow({"count": 1}, {"count": 1})
```

## Safety and validation

- Accuracy is UNKNOWN (`null`) until a verified independent oracle is provided; positive accuracy thresholds therefore block. `min_accuracy=0` deliberately disables that dimension for a bounded pilot only.
- Correctness defaults to checking required fields. Callers needing actual business correctness must provide a domain-specific `valid_row` predicate.
- Quarantine reports indices and reason codes, not sensitive row values. When rows are quarantined but all numeric thresholds pass, the result is QUARANTINE (not ACCEPT); consumers must explicitly decide how to handle such records.
- Empty datasets, missing timestamps and invalid thresholds fail closed.
- Shadow comparison does not promote, mutate, or authorize any production effect.
- All functions are inert until explicitly imported and wired into a caller.

Local focused validation before commit: `PYTHONPATH=. python -m pytest services/langgraph/tests/test_request_accut.py -q` — **9 passed** in a temporary patch workspace. This is not evidence that repository-wide CI or production tests passed.

## Deferred ACE v100 requirements

Typed mission/DAG orchestration; durable external-effect receipts and reconciliation; fencing tokens; full cross-language contract parity; model capability routing; evidence debt and calibrated confidence; policy time capsules; production shadow traffic; model skill dispatch; quota budgets; tenant-integrated security review; failover/canary release; CI-wide verification. Inspect existing implementations and avoid duplicating current idempotency, checkpoint and governance code.

**Important:** Existing `generate_idempotency_key(..., attempt=...)` changes identity with attempt. External effects require stable operation identity and provider reconciliation across retries; this increment does not alter those semantics.

## Rollback

Remove the three new files in this increment. Existing behavior is unchanged because this module is not connected to the production execution path.
