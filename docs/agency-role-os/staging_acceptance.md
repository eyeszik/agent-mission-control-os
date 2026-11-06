# Agency RoleOS Release-Candidate Staging Acceptance

## Machine gates

1. RoleOS registry verifies and resolves exactly 1,097 source roles.
2. The AMC profile exactly matches the nine live LangGraph stages in order.
3. Every stage compiles to a sealed RoleOS role and valid P0-P15 phase.
4. HITL is not execution-ready without explicit authority and exact approval evidence.
5. Missing demanded provenance/model/schema/ACL evidence remains release-blocking.
6. MEMORY_WRITE and CLOCK_WINDOW_ADVANCE hook gaps remain observable but are non-demanded for this pipeline until such dependencies are actually introduced.
7. Provider-success staging reaches needs_approval, authenticated approval resolves, resume reaches completed, and proof terminal candidate is COMPLETE.
8. Degraded output remains blocked after approval.
9. Rejected/stale approvals remain blocked.
10. Recovery, outbox replay, retry, compensation, stale-approval regeneration, lineage remediation, and idempotency tests pass.
11. Backend/shared/web tests, typecheck/build, E2E smoke, dependency audit and all repository verifier gates pass.
12. Integrity manifest matches every tracked changed boundary file.

## Human gates

Production acceptance is not synthetic. An authenticated authorized human must review the exact tested revision and explicitly approve deployment. Production secrets, Supabase identity membership and deployment bindings remain out of source control. External publication and paid-media execution remain disabled.
