# ACE v100 — Remaining Integration Work and Execution Contract

Status: **INCOMPLETE / RELEASE BLOCKED**. Baseline: merged PR #138; final-head run 38455575224 failed in both backend jobs on `test_ace_privacy.py`. This branch repairs that regression, but **passing CI alone is not a production release authorization**.

## Operational rules
- Never silently merge, deploy, activate live effects, or expand capabilities. Use draft PRs, human-reviewed promotion, and staged rollout.
- Reuse existing `services/langgraph/persistence/durable_runs.py`, `agency/reliability/outbox.py`, `persistence/proofs.py`, `security/approval_authority.py`, `agency/ace_controls.py`, `quality/request_accut.py`, and `agency/durable/observability.py`. Avoid competing ledgers or schedulers.
- Every change must link an acceptance test and exact commit SHA. `PASS` requires current-head CI, not a previous commit. Failed or unavailable evidence remains **UNVERIFIED**.
- Preserve tenant isolation and backward compatibility. All new behavior is opt-in until live adapter and rollback evidence is accepted.

## Priority 0 — Restore a trustworthy mainline
1. [x] Identify exact CI regression: escaped literal `\\n` between Authorization and Bearer evades `detect_pii`.
2. [x] Normalize escaped line breaks before sensitive-pattern detection and redaction; preserve nested redaction semantics.
3. [x] Run both backend jobs (SQLite and PostgreSQL) on the **new branch head** and demonstrate all tests green; confirm no unrelated regressions. *Verified for merged `master` `493877f7`: [`docs/ace-v100/evidence/493877f7…json`](ace-v100/evidence/493877f7763aedd213d3781ff4b615f261af26cf.json).*
4. [x] Recheck frontend contract, typecheck, Vitest, build, browser HITL smoke, dependency audit, and integrity manifest for the **same SHA**. *Verified for `493877f7` (same evidence file). Collector: `scripts/collect_release_evidence.py`.*
5. [ ] Require branch protection / rulesets to reject failing required checks; verify whether admins can bypass. Any policy change requires authorized repository administrator. *UNVERIFIED (Increment 02): classic protection not readable by the integration (HTTP 403); no repository rulesets apply to `master`.*

## Priority 1 — Runtime correctness and external effects
6. [ ] Inventory **every** external adapter/action and map each to read-only, compensatable, irreversible, or approval-required effects. Record provider-specific idempotency semantics, timeout behavior, retry budget, and reconciliation API. Gate: no unmapped live action.
7. [ ] Wire stable `tenant/project/action/payload` operation keys through every dispatcher and durable outbox entry; never derive identity from retry attempt. Gate: repeated delivery causes at most one provider effect **where provider supports idempotency**.
8. [ ] Implement a durable `UNKNOWN_OUTCOME` transition when provider response is lost after mutation; query authoritative provider state before retry. Gate: injected timeout-after-commit never triggers blind duplicate mutation. *Increment 02: holds for the ACE v12 gateway (sandbox adapters), and R3+ dispatch is now held while any outcome is unconfirmed (`test_ace100_edge_cases.py` E01/E04). Open for live adapters, which do not exist.*
9. [ ] Implement per-provider compensation workflows with explicit eligibility, ownership, human approval and irreversible-failure paths. Gate: compensation fault matrix and receipts for each supported effect type.
10. [ ] Validate PostgreSQL compare-and-swap fencing, lease renewal, expiry, zombie worker rejection, crash recovery and multi-worker races under skew and partitions. Gate: concurrent integration tests against real PostgreSQL.
11. [ ] Make outbox publish, effect receipt, audit receipt and checkpoint correlation durable and recoverable; define retention and replay behavior. Gate: kill/restart and duplicate-delivery fault tests.

## Priority 2 — Policy, identity and approvals
12. [ ] Bind capability checks to the actual action boundary, not only planners; enforce tenant/project scope, deny-by-default and explicit actor identity.
13. [ ] Require signed, expiring, single-use approval artifacts for high-risk actions; invalidate approvals when payload, environment or capability changes. Gate: replay, expiry, cross-tenant, scope escalation tests.
14. [ ] Implement policy versions, emergency disable, audit history and escalation. Gate: revoked capability prevents execution even with a queued old plan.
15. [ ] Validate SSRF protections including DNS rebinding, redirects, IP literals, link-local metadata and private address ranges. Gate: adversarial integration tests.

## Priority 3 — Contracts, graph and model execution
16. [ ] Export versioned canonical JSON Schemas from Pydantic and validate TypeScript/Zod parity against shared positive/negative fixtures in CI. Gate: contract diff fails on incompatible changes.
17. [ ] Integrate typed DAG validation into scheduling: cycle rejection, prerequisites, task ownership, idempotency classification, deadlines, budget and cancellation propagation. Gate: determinism and invalid-graph property tests.
18. [ ] Integrate capability-based model routing with live adapters, bounded retries, circuit breakers, tenant quotas, concurrency budgets and fallback restrictions. Gate: deterministic simulated outage, throttling and incompatible-capability tests.
19. [ ] Implement distributed, not merely process-local, provider quota coordination where multi-instance operation requires it. Gate: multi-worker burst and starvation tests.

## Priority 4 — Evidence, data quality and privacy
20. [ ] Wire REQUEST intent and ACCUT checks into actual ingest, transform, publish and quarantine transitions; block promotion on missing accuracy evidence. Gate: shadow comparison plus controlled production-like replay.
21. [ ] Persist HMAC-chained provenance with key IDs, protected KMS-backed custody, rotation and verification after restart; implement access-controlled append-only storage and tamper alarms. Gate: cross-tenant/tamper/rotation tests.
22. [ ] Define evidence completeness, source provenance, confidence threshold, freshness and conflict resolution at publication boundary. Gate: unsupported conclusions are quarantined.
23. [ ] Classify and redact secrets/PII across request/response, structured logs, receipts, traces, exceptions, replay bundles and exports. Gate: seeded secret never reaches any persistent sink. *Increment 02: the action boundary now refuses base64/percent-encoded credentials before storage (E08). Other sinks remain to be inventoried.*
24. [ ] Define encryption, retention, deletion, access controls, data residency and privacy review. Gate: evidence-backed threat-model approval.

## Priority 5 — Operations, product and release
25. [ ] Propagate W3C trace context across queued work and provider calls; emit cardinality-bounded metrics for outbox lag, lease churn, stale fences, uncertain effects, quarantines, cost and approvals. Gate: live collector ingestion and dashboards.
26. [ ] Build a human-approval console with accessible status, clear action consequences, deny/revoke flows and immutable receipt links. Gate: keyboard/mobile accessibility and real approval E2E tests.
27. [ ] Provide operator runbooks: pause, resume, reconcile, compensate, rotate keys, incident triage, recovery and tenant offboarding. Gate: dry-run by a second operator.
28. [ ] Execute load, fuzz, fault injection, network partition, duplicate delivery, provider outage and recovery tests; measure latency/cost budgets and SLOs. Gate: published exact-SHA evidence.
29. [ ] Generate agent-readable `AGENTS.md` guidance, architecture diagrams, API contracts and migration guide. Validate instructions against actual repository paths and permissions.
30. [ ] Stage rollout: shadow → internal sandbox → canary → limited live; require explicit approval at every transition, reversible feature flags, monitoring, rollback drill and security sign-off. Gate: signed release decision.

## Execution DAG
`P0 baseline CI → P1 effect inventory → P1 durable reconciliation/fencing → P2 authorization → P3 schemas/DAG/router → P4 quality/provenance/privacy → P5 telemetry/UX/chaos → independent review → approved canary → approved production`.

Independent tasks may proceed in parallel only when their prerequisite contracts are stable. Every external mutation must carry `effect_id`, `tenant_id`, `project_id`, `action_id`, `operation_key`, `approval_ref` (when required), `fencing_token`, `provider_receipt`, `status`, `reconciliation_state`, `trace_id` and a redacted evidence reference.

## Definition of done
**Fully integrated** means every supported live adapter is covered, exact-head CI is green, production-like fault and security gates are independently verified, telemetry and rollback work in the target environment, and an authorized human explicitly approves activation. A passing unit test, merged PR, schema declaration or architecture document alone does not satisfy this definition.

## Source and verification notes
- Internal evidence: merged PR #138; CI run 38455575224; `docs/ACE_V100_MERGE_GATE.md`; `services/langgraph/tests/test_ace_privacy.py`.
- User-supplied Abhishek Anand paper is conceptual inspiration for REQUEST/ACCUT/quarantine/shadow mode, not independent proof of this repository's behavior.
- External OpenTelemetry Python context propagation guidance: https://opentelemetry.io/docs/languages/python/propagation/
- Stack Overflow For Agents connection required approval and was not used as technical evidence. Hey Terminal has no verified device execution. Product Design and Agent Ready are advisory workflows, not evidence of an implemented UI.
