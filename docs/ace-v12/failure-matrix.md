# Failure matrix

What happens when each part fails, the state it leaves behind, how it recovers, and the test that proves it.
"Re-sent" means the effect is executed again. The gateway never re-sends without first reading the provider back.

| Failure | Detected by | Resulting state | Recovery | Re-sent? | Test |
|---|---|---|---|---|---|
| Unknown capability id | catalogue lookup | 404 `NOT_IMPLEMENTED` | none needed | — | `test_t03_unknown_operation_is_not_implemented` |
| Reserved EXT/ART id | catalogue lookup | `NOT_IMPLEMENTED` (namespace `VOID_DETECTED`) | none; never described | — | `test_t02_reserved_namespaces_are_void_and_never_described` |
| Invalid arguments | adapter `validate` | 422, nothing stored | fix the request | — | `test_t05_typed_args_are_validated` |
| Secret in the payload | `assert_no_secrets` | 422 `SECRET_IN_PAYLOAD`, nothing stored | remove the secret | — | `test_t48_i16_secrets_are_refused_and_never_stored` |
| LIVE requested | LIVE gate | 409 `LIVE_GATED` | none in this change | — | `test_t52_i04_i20_live_is_gated_whatever_is_set` |
| Above the autonomy ceiling, no approval path | autonomy dial | `BLOCKED` | an owner raises the dial, then propose again | — | `test_t16_autonomy_caps_what_runs_without_a_person` |
| Approval rejected | `settle` | `REJECTED` | propose a revised action | — | `test_t19_a_rejection_is_terminal_and_never_dispatches` |
| Approvals decided but not valid (self, same reviewer, wrong role) | `check_approvals` | `BLOCKED` with the reason | propose again, with independent reviewers | — | `test_t20_…`, `test_t21_…`, `test_t22_…` |
| Payload, target, policy or dependency changed after approval | binding hash | refused at dispatch; approval reported stale | new approval on the new binding | — | `test_t18_…`, `test_t23_…`, `test_e11_…` |
| Action expired | preflight / expiry sweep | `EXPIRED`; reservation released | propose again | — | `test_t24_i06_expired_actions_and_late_approvals_never_dispatch` |
| Freeze active | preflight | dispatch refused (423) | lift (second owner/admin) | — | `test_i19_…` |
| No budget policy | reservation | `BLOCKED` `NO_BUDGET_POLICY` | operator sets a policy | — | `test_t41_no_ceiling_means_no_spend` |
| Ceiling exceeded | reservation under lock | `BLOCKED` | raise the ceiling or wait for the window | — | `test_t42_per_action_ceiling`, `test_t43_…` |
| Two dispatches race | lease + CAS on `version` | exactly one effect | loser gets 409 | No | `test_t35_e01_concurrent_dispatch_makes_exactly_one_effect` |
| Tool missing on host | adapter `ToolUnavailable` | `FAILED` `TOOL_UNAVAILABLE`, not retry-eligible | install the tool | — | `test_t50_i08_missing_tools_never_report_success` |
| Transient failure before any effect | adapter | `FAILED`, retry-eligible | `retry` (≤ 3 attempts) | Yes, safely: nothing was applied | `test_t39_i15_retries_are_bounded` |
| Timeout before the effect | adapter `OutcomeUnknown` | `UNKNOWN` → reconcile → `FAILED` `NOT_APPLIED` | `retry` | Only after the read-back shows nothing | `test_t37_…` |
| Timeout after the effect | adapter `OutcomeUnknown` | `UNKNOWN` → reconcile → `COMPLETED` | read-back by effect key | No | `test_t36_e02_i09_timeout_after_effect_reconciles_without_resending` |
| Worker crash mid-dispatch | lease expiry | stale `DISPATCHING` | `recover_stale` / `POST /actions/recovery/sweep` reads back | No | `test_t38_e08_crash_mid_dispatch_is_recovered_by_read_back` |
| Provider unreadable or state mismatch | observation | `NEEDS_HUMAN` | a person inspects; reconcile again | No | `test_t40_mismatch_and_unreadable_providers_escalate_to_a_person` |
| Provider claims success, nothing stored | independent read-back | not `COMPLETED` | reconcile | No | `test_i13_success_needs_an_independent_read_back` |
| Spend applied, then refunded | compensation by an approver | evidence of compensation recorded | — | — | `test_t45_refunds_are_compensation_with_evidence` |
| History row edited | chain verification | evidence shows the chain broken | investigate | — | `test_i12_tampering_with_history_is_detected` |
| Stored artifact bytes changed | export re-verification | item excluded `CONTENT_HASH_MISMATCH` | re-produce and re-approve | — | `test_i13_export_rereads_stored_bytes_and_excludes_tampered_ones` |
| Brief needs a missing provider | mission preview | `PROVIDER_GAP` | install a provider (not in this change) | — | `test_t56_provider_gap_and_missing_brand_are_reported_not_faked` |
| Brief asks to publish or spend | intent compiler | `NonActionReceipt`, never dispatched | a governed action, separately approved | — | `test_t55_external_effects_in_a_brief_are_never_dispatched` |
| Client offboarding with open work | offboarding report | new work blocked | close or cancel open work, then archive | — | `test_offboarding_blocks_new_work_until_open_work_is_closed` |
| Browser offline | `navigator.onLine` | banner; requests fail visibly | retry when online; idempotency keys make retries safe | No duplicates | browser drive (see test evidence) |

At-least-once delivery: a sandbox effect may be attempted more than once, but the effect key dedupes it at the
provider. Exactly-once is not claimed.
