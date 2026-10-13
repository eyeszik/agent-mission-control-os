# ACE v100: architecture parity and merge gate evidence

Branch: `feature/ace-v100-request-accut-pilot` · PR #138.
This register distinguishes existing code, this increment, and unverified requirements.
**No production feature activation or merge is authorized by this document.**

## Scope-specific implementation map

| Pillar | Current evidence | Newly added or hardened | Completion gate |
|---|---|---|---|
| 1 Durable external effects | `agency/reliability/outbox.py`, `persistence/durable_runs.py`, existing outbox tests | Live-fence check before new intent reservation; stable scoped operation-key utility in `agency/ace_controls.py` | Verify provider-specific reconciliation and compensation across ALL external adapters; simulate provider committed then response lost; no generic at-most-once claim |
| 2 Leases/fencing | `persistence/durable_runs.py` existing CAS claim and fenced transition; `tests/test_abc_v6.py` | `renew_lease` CAS heartbeat and regression tests for stale/expired workers and expired intent creation | Exercise concurrent PostgreSQL workers, heartbeat under clock skew, and fault scenarios |
| 3 Cross-language contracts | Existing `packages/shared`, Pydantic models, ontology parity CI | Opt-in strict Pydantic `Mission`, `Task`, `Capability`, `EvidenceItem`, `AuditRecord` and JSON round-trip tests | Generate cross-language JSON Schema and Zod parity, migrate all supported boundaries without breaking changes |
| 4 Model-agnostic routing | Existing LLM and media providers, `agency/visual/router.py`, provider semantics tests | Deterministic `route_capability` produces allowlisted complexity-compatible fallback candidates | Wire live adapters, quotas, token-bucket backpressure, error classification, circuit breakers, and provider-specific contract tests |
| 5 Evidence/confidence | Existing `persistence/proofs.py`, `quality/request_accut.py` | Strict `confidence_gate`, `seal_record`, `verify_chain`; ACCUT quarantine semantics | Persist signed audit chain with protected key rotation, source provenance, critical evidence gates integrated in final publication |
| 6 Security | Existing authorization in `security/approval_authority.py`, SSRF and payload validation in `agency/actions/safety.py` | Sensitive key, bearer-token and raw prompt redaction in `security/pii.py` | Full boundary review, tenant isolation proof, log sink inventory, SSRF DNS rebinding verification, supply-chain audits |
| 7 Observability | Existing opt-in `agency/durable/observability.py` with OpenTelemetry-shaped spans | Heartbeat CAS increments version; new pure control functions avoid sensitive telemetry | Wire real tracing/context propagation, metrics for fence rejects/lease/outbox/routing, observable verified dashboards |
| 8 Fault injection | Existing `tests/test_abc_v6.py`, `tests/test_execution_fabric.py` and CI | Zombie fence, expired-intent, pure DAG/route/evidence tamper tests | Network split, timeout-after-effect, property-based fuzzing, load tests and chaos automation in CI |

## Invariants

- Failed evidence gates produce QUARANTINE, not ACCEPT.
- Canonical operation keys include tenant, project, action and payload; retry attempt numbers do not change operation identity.
- Provider calls are NOT performed by `ace_controls.py`; it is a pure planning and validation layer.
- Authenticated evidence records are verifiable only when the signing key is protected, rotated and retained. HMAC records are NOT automatically a persistent trustworthy audit trail.
- A durable intent and fencing token do not themselves guarantee exactly-once provider execution. External idempotency and verification are required; uncertain outcomes are reconciled before re-dispatch.
- Background outbox delivery is normally at-least-once unless the provider participates in deduplication or an equivalent transactional protocol.
- Never claim this PR satisfies the complete ACE v100 merge gate until all outstanding rows have code links and passing CI/fault evidence.

## Checks

CI base: `.github/workflows/ci.yml` (Python/pytest, PostgreSQL migrations/tests, frontend contracts and build, browser smoke, dependency audit).
New tests:
- `services/langgraph/tests/test_ace_controls.py` strict schemas, roundtrips, DAG, routing, evidence verification.
- `services/langgraph/tests/test_ace_privacy.py` nested secret and bearer redaction.
- `services/langgraph/tests/test_abc_v6.py` heartbeat, stale fencing and expired-intent rejection.
- Existing `test_request_accut.py` quality threshold and quarantine.

A test result is VERIFIED only for the exact commit SHA that ran. Cancelled earlier CI attempts do not count as PASS. If the current commit fails, repair and re-run; do not merge.

## Rollback

All new opt-in contracts can be removed without affecting active provider dispatch. Revert modifications to `persistence/durable_runs.py` and `security/pii.py` if regressions appear, preserving existing pre-PR semantics. This is a code rollback, not compensation for external effects.

## Research

User-supplied Abhishek Anand (2025), *Accelerating Data Engineering Productivity with Agent-Based Automation and Natural-Language Interface*, DOI 10.70315/uloap.ulirs.2025.0204008: REQUEST, ACCUT, Quarantine Pattern and low-risk shadow-mode pilot. External guarantees require independent verification against platform/provider documentation.
