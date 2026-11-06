# Security controls and threat model

Scope: the action plane (`agency/actions`), Agency OS services (`agency/agency_os`) and their routes. Every row
names the control in code and the test that exercises it. A threat with no test is listed as such; none is
claimed as mitigated without one.

## Secure defaults

| Default | Where |
|---|---|
| LIVE refused for every action, whatever is configured | `governance.live_enablement()` always returns `DISABLED`; `AMC_ACTIONS_LIVE` is read only to report that it is ignored |
| Autonomy `DRAFT`: only R0/R1 run without a person | `governance.autonomy`; raising needs owner/admin |
| No budget policy means no spend | `NO_BUDGET_POLICY` at reservation; policies are operator-managed, not exposed through the API |
| Step-up authentication absent, so R5 is blocked | `STEP_UP_UNAVAILABLE` |
| Delivery manifests unsigned unless a key of 32 characters or more is configured | `AMC_DELIVERY_SIGNING_KEY`; otherwise `UNSIGNED` with the reason |
| Authority from the server only | `Principal` from `security.auth`; tenant and approver roles from `amc.tenant_memberships`; client-supplied tenant, reviewer, approval or grant fields are ignored |

## Threats

| Threat | Control | Tests |
|---|---|---|
| Prompt injection in arguments | `scan_for_injection` flags the request; the flag never changes risk or approvals | `test_t30_i18_injection_in_args_is_flagged_not_obeyed` |
| Malicious tool output / retrieved content | Fetched content is stored as data in the sandbox record; risk is computed from the descriptor and request facts only | `test_t29_i18_retrieved_content_cannot_change_policy` |
| Memory or documents treated as permission | No code path reads authority from memory, briefs or artifacts; the intake compiler marks publish/spend/send as `FORBIDDEN_TO_INFER` | `test_t55_external_effects_in_a_brief_are_never_dispatched` |
| Privilege escalation: self-approval | Requester can never decide their own action; governance approvals exclude the requester and the actor | `test_t20_i14_requester_cannot_approve_their_own_action`, `test_t21_i14_governance_needs_an_independent_privileged_reviewer` |
| Privilege escalation: one person supplying every approval | `SAME_REVIEWER_FOR_MULTIPLE_APPROVALS` | `test_t22_financial_approval_is_separate_and_privileged` |
| Privilege escalation: role | Spend and governance approvals restricted to owner/admin through server-written `approval_policy` enforced in `/approvals/{id}/decide`; read-only roles cannot act; autonomy raise and freeze lift need owner/admin | `test_t22_…`, `test_t27_read_only_roles_cannot_act`, `test_i19_freeze_blocks_dispatch_and_lifting_needs_a_second_person` |
| Confused deputy | The gateway acts with the identity and scope of the caller, re-checked at dispatch; ownership changes are re-checked before dispatch | `test_t17_i03_identity_and_scope_are_server_derived`, `test_e05_ownership_change_is_rechecked_before_dispatch` |
| Tenant leakage | Every read and write is tenant-scoped; another tenant gets 404, not 403; idempotency keys are tenant-scoped | `test_t25_i01_another_tenant_sees_and_does_nothing`, `test_t28_i01_idempotency_keys_are_tenant_scoped`, `test_t32_evidence_and_recovery_views_are_tenant_scoped`, `test_clients_and_analytics_are_tenant_scoped_and_evidence_only` |
| Project scope bypass | Project access checked on propose, dispatch and every view; cross-project dependencies refused | `test_t26_project_scope_is_enforced`, `test_t31_cross_project_dependencies_are_refused` |
| Approval tampering | Approval `subject_hash` must equal the current `binding_hash` (payload, target, tenant, project, environment, policy version, dependency hashes, expiry) | `test_t18_i05_approval_is_bound_to_the_exact_binding`, `test_t23_i06_i07_dependency_drift_blocks_an_approved_action`, `test_t24_i06_expired_actions_and_late_approvals_never_dispatch`, `test_e11_policy_change_mid_mission_revokes_the_permit` |
| Audit tampering | `action_transitions` is hash-chained per action and verified on every evidence read | `test_i12_tampering_with_history_is_detected` |
| Replay | Idempotency key per tenant; same key with a different body is refused; effect key dedupes at the provider | `test_t33_idempotent_replay_and_key_reuse`, `test_t34_e01_concurrent_proposals_with_one_key_make_one_action`, `test_t35_e01_concurrent_dispatch_makes_exactly_one_effect` |
| SSRF | `check_public_url`: https on port 443 only; no credentials in the URL; IP literals and numeric host encodings refused; internal host names blocked. Names are not DNS-resolved, because the sandbox fetcher makes no network request at all; a live fetcher would also need resolve-and-pin, which is not implemented | `test_t47_ssrf_targets_are_refused` |
| Unsafe uploads / path traversal | `safe_relative_path`; stored SVG is re-checked by `svg_safety` at verification | `test_t49_path_traversal_is_refused`; SVG safety is covered by the existing intake suites |
| Secret exposure | Payloads with secret-like values are refused before storage (`SECRET_IN_PAYLOAD`); views are PII-redacted | `test_t48_i16_secrets_are_refused_and_never_stored`, `test_t51_i16_views_are_redacted` |
| Artifact exfiltration | Exports require project write scope; the manifest is returned to the caller and recorded; nothing is sent anywhere | `test_acceptance_journey_brief_to_verified_export` |
| Artifact substitution at rest | Export re-reads the stored bytes and re-verifies their hash | `test_i13_export_rereads_stored_bytes_and_excludes_tampered_ones` |
| Forged delivery manifest | HMAC-SHA256 over the canonical manifest when a key is configured; `verify-manifest` recomputes the hash and signature | `test_t53_signed_manifests_verify_and_detect_tampering` |
| Fake success from a provider | Completion requires an independent read-back that matches the bound payload hash and expected state | `test_i13_success_needs_an_independent_read_back`, `test_t40_mismatch_and_unreadable_providers_escalate_to_a_person` |
| Missing provider reported as success | Missing tools fail with `TOOL_UNAVAILABLE` and no outcome; provider gaps are listed, never simulated | `test_t50_i08_missing_tools_never_report_success`, `test_t56_provider_gap_and_missing_brand_are_reported_not_faked` |
| Provider drift | Capability drift radar compares declared support with a live probe | `test_drift_radar_and_expiry_radar` |
| Runaway spend | Ceilings per action, project, client, day and month; atomic reservation under a lock; observed amount committed | `test_t41_…` to `test_t46_…`, `test_t43_i10_e06_concurrent_reservations_cannot_exceed_a_ceiling` |
| Graph replay re-executing an effect | No LangGraph node calls the gateway (LangGraph resumes interrupted nodes from the start) | `test_i02_no_graph_node_dispatches_through_the_gateway` |
| Emergency | Freeze at system (`AMC_ACTIONS_FREEZE`), tenant or project scope stops every new dispatch; reconciliation continues | `test_i19_system_freeze`, `test_i19_freeze_blocks_dispatch_and_lifting_needs_a_second_person` |
| Browser preflight hiding a failed write | Every HTTP method a route uses is allowed by CORS | `test_t58_every_route_method_passes_the_cors_preflight` |
| Supply-chain compromise | No new runtime dependency was added. Security-boundary files are hash-pinned in `manifest.json` and checked by `verify_manifest.py` | `scripts/verify_manifest.py` (CI gate) |

## Retention and deletion

- Clients are offboarded, then archived. Offboarding blocks new work until open work is closed
  (`test_offboarding_blocks_new_work_until_open_work_is_closed`). Archiving keeps records for audit.
- Asset deletion is R5 and is blocked (`STEP_UP_UNAVAILABLE`). No deletion path runs in this change.
- `action_sandbox_effects` holds only sandbox state and is never presented as delivered.

## Audit access

`GET /actions/{id}/evidence` is tenant- and project-scoped. It returns the hash-chained transitions, policy
decisions, dispatch permits, execution and observation receipts, approvals, reservation, the sandbox record and
the claims with their proofs. `live_execution` is always `"DISABLED"`.

## Known limits

- Delivery is at-least-once. Exactly-once is not claimed; idempotency keys dedupe at the provider.
- Step-up authentication does not exist, so R5 cannot run even in the sandbox.
- The new `/actions` and `/agency-os` routes have no request rate limiter. Spend is bounded by budget ceilings, not by rate.
- External references (OWASP, NIST) could not be fetched from this environment. Controls are derived from the
  repository's own code and tests.
