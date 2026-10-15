# ACE v100 — Increment 02: uncertainty debt at dispatch, exact-SHA evidence, edge-case matrix

**Status: integrated into the governed action path (sandbox only). Not a production release.**
Base: `master` at `493877f7763aedd213d3781ff4b615f261af26cf`.
This increment adds no live adapter, enables no live effect and grants no authority.

## What changed

| Area | Change | Files | Tests |
|---|---|---|---|
| Uncertainty debt at the real dispatch boundary (runbook 8, 12; brief P1/P2) | Before any R3+ dispatch, the ACE v12 gateway's `preflight` runs the existing pure `ace_release.assess_uncertainty` over the tenant's unresolved effects (UNKNOWN, RECONCILING, NEEDS_HUMAN). The default policy tolerates none, so no new risky effect starts while an earlier one is unconfirmed. The block is a *hold*: the waiting action stays AUTHORIZED and dispatches once reconciliation resolves the debt. A snapshot that may be truncated counts as incomplete and blocks. Other tenants never count. | `agency/actions/governance.py` (`uncertainty`), `agency/actions/gateway.py` (`preflight`) | `test_ace100_uncertainty.py` (6), updated `test_ace12_actions.py::test_t40` |
| Debt visibility | `GET /actions/uncertainty` returns the policy, the assessment and the unresolved actions. Counts are tenant-wide; only actions in projects the caller may access are listed. A Zod twin and a recorded fixture keep the contract in parity. The Overview Safety state shows the hold. | `api/routes/actions.py`, `packages/shared/src/schemas/agencyOs.ts`, `packages/shared/tests/fixtures/ace12.json`, `apps/web/components/agency/views/OverviewView.tsx` | `test_ace12_contracts.py`, `packages/shared/tests/agencyOs.test.ts` |
| Exact-SHA release evidence (brief P7; edge cases 10, 11) | `ace_evidence.gate_results_from_check_runs` maps GitHub check runs to release gates. A run whose `head_sha` is not the commit under review is rejected, and the latest attempt of a re-run decides. Gates that no CI job proves on its own (fault injection, security regression, evidence integrity) stay UNVERIFIED. `production_status` compiles the brief's release decision and moves a field only when evidence supports it. `scripts/collect_release_evidence.py` writes unsigned, fail-closed evidence. | `agency/ace_evidence.py`, `scripts/collect_release_evidence.py` | `test_ace100_evidence.py` (11) |
| Partial compensation failure (edge case 7) | A compensation whose provider read-back fails used to escape as an unhandled error, with nothing recorded. It is now recorded as `UNCONFIRMED` and returns `409 COMPENSATION_UNCONFIRMED`. Running it again reads the provider back and never applies the compensation twice. A success is recorded as `CONFIRMED`. | `agency/actions/gateway.py` (`compensate`) | `test_ace100_edge_cases.py::test_e07` |
| Encoded credentials (edge case 8; runbook 23) | The gateway refused plain credentials but accepted base64- or percent-encoded ones, which then sat raw in stored action arguments. Encoded forms are now decoded and checked, and plain `Bearer` tokens are recognised. Ordinary encoded content is still accepted. | `agency/actions/safety.py` | `test_ace100_edge_cases.py::test_e08` |

## Critical edge cases (INJECT → ASSERT → RECOVER → VERIFY)

Each case runs through real code paths against sandbox providers in `services/langgraph/tests/test_ace100_edge_cases.py`. The CI run of that file on an exact commit is the record.

| # | Edge case | Injected fault | Safe outcome asserted | Recovery and verification |
|---|---|---|---|---|
| E01 | Provider commits, acknowledgement lost | `timeout_after_effect` | UNKNOWN, one effect, never re-sent, new R3 work held | Read-back adopts the effect: COMPLETED, still one effect, chain intact |
| E02 | Stale worker races a new leaseholder | Lease expires mid-dispatch | Recovery takes over; the stale worker's late write is rejected by the version fence | Retry completes; one effect; chain intact |
| E03 | Duplicate delivery, concurrent dispatch | Four simultaneous dispatches | Exactly one COMPLETED; no unexpected exception | One effect; chain intact |
| E04 | Provider without reliable reconciliation | Read-back unreachable | NEEDS_HUMAN after bounded attempts; never re-sent; new R3 work held | Provider readable again → COMPLETED; held work then runs |
| E05 | Approval expires or is replayed | Dispatch after expiry; decide twice; reuse across actions | EXPIRED; second decision 409; one action's approval never authorizes another | Only the approved binding runs; one effect |
| E06 | Cross-tenant effect or evidence collision | Same Idempotency-Key and payload in two tenants | Two actions, two effects keyed per tenant | Each tenant's evidence is 404 to the other |
| E07 | Compensation partially fails | Refund applied, read-back lost | 409 COMPENSATION_UNCONFIRMED; reservation not refunded on a guess | Rerun → CONFIRMED; one refunded effect; reservation REFUNDED once |
| E08 | Encoded credentials reach a sink | base64 and double percent-encoded bearer token | 422 SECRET_IN_PAYLOAD | Nothing stored; ordinary encoded content still accepted |
| E09 | Python and Zod validation differ | — | Action-state and debt-state enums equal on both sides | Recorded fixture parsed by Zod (`agencyOs.test.ts`) |
| E10 | CI evidence belongs to another SHA | Green run for a different commit | Gate UNVERIFIED, not PASS | Release not permitted |
| E11 | Signing or monitoring fails at release | Signing key unavailable; telemetry unverified | Promotion unauthorized; release not permitted | Permitted only with both restored |

## Evidence collected in this session

`docs/ace-v100/evidence/493877f7763aedd213d3781ff4b615f261af26cf.json` was collected from real GitHub check runs:

- All five CI jobs succeeded on that exact SHA.
- `overall_status`: `MERGED_NOT_PRODUCTION_VERIFIED`.
- `release_permitted`: `false`.
- Fault injection, security regression and evidence integrity: UNVERIFIED, because no independent evidence exists.

## Blocked or unavailable here (not attempted, not claimed)

| Phase | Gap | Why it cannot be closed from this session |
|---|---|---|
| P5 Operations | Datadog ingestion, live collector, dashboards | No collector endpoint, Datadog credentials or target environment is available. The repository has opt-in OTel instrumentation (`agency/durable/observability.py`), but ingestion has not been observed. |
| P6 Live canary | Reversible live effects per action class | No live provider adapter exists, LIVE has no enabling switch, and no authorization was given. Every adapter is a sandbox fake. |
| P7 Release | Signed human approval, signing-key custody | The key must be held outside the repository and the approval must come from an authorized human. Neither can be produced here. |
| Runbook 5 | Branch protection rejects failing checks | Classic protection is not readable by this integration (HTTP 403). No repository rulesets apply to `master`. Unverified. |
| Runbook 11, 19, 21, 24 | Durable outbox/receipt correlation, distributed quotas, KMS custody, privacy review | Outside this increment. |
| Edge case 7, residual | An UNCONFIRMED compensation is recorded and safe to rerun, but it does not yet count toward uncertainty debt | Counting it needs a queryable marker. Kept out to avoid a schema change in this increment. |

## Rollback

Revert this increment's commits. No migration and no new table. The gateway hold, the compensation recording and
the encoded-secret check are code-only. `ace12.json` gains one fixture key.
