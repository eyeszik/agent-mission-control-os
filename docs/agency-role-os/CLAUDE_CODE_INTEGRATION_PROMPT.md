# Claude Code Integration Prompt: Agency Role OS → Agent Mission Control

You are the release/integration engineer for `eyeszik/agent-mission-control-os`.

## Immutable inputs
- Base commit: `64c5a29d66cf6129792e5bb8dc310212ec5efa8c`
- Prepared branch: `roleos-release-candidate-2026-09-25`
- Agency source ZIP SHA-256: `d98182dd14b4c1493232d59d2783ce05e8dfb120ebeeb865c88317d06075a757`
- Uploaded (3) and (4) ZIPs are byte-identical.
- Source role files: 1,097; sealed RoleOS runtime roles: 1,097.
- Do not deploy production, enable publication, or enable paid-media spend.

## Precedence
1. Current repository security/auth/production gates and canonical schemas.
2. `docs/production-activation.md`, `CLAUDE.md`, repository verifier scripts.
3. Prepared RoleOS integration files and 28-record disposition ledger.
4. Agency source role content.
5. `references/imported_specs/` is advisory/provenance context unless current code/tests independently verify a claim.

Never treat role seniority, prompt prose, imported architecture claims, numeric confidence, or model output as runtime authority.

## Required integration
Preserve the existing LangGraph workflow and project it into RoleOS through `MissionWorkOrderAdapter`:
- brief_intake → P4 → account-manager
- brand_strategy → P5 → brand-strategist
- creative_concepting → P7 → creative-director
- copywriting → P7 → copywriter
- design_brief → P8 → art-director
- campaign_assembly → P9 → creative-producer
- brand_safety_qa → P10 → qa-engineer
- hitl_gate → P11 → account-director (HUMAN)
- delivery → P11 → project-manager

P12 launch is external launch, not internal/client package delivery.

Do not bypass WorkOrderCompiler. HITL must remain non-executable without explicit authority plus exact approval evidence.

## Invalidation contract
Keep every ledger class. For the current branding pipeline, release-demanded classes are:
`SPEC_CHANGE`, `MODEL_PARAM_CHANGE`, `TOOL_RESULT_CHANGE`, `SCHEMA_CHANGE`, `ACL_SECRET_CHANGE`.

`MEMORY_WRITE` and `CLOCK_WINDOW_ADVANCE` remain recorded as HOOK_GAP evidence but non-demanded until the pipeline actually declares those dependencies. Never globally bypass `run_compile_gate`.

## Tools / approvers
Reuse existing tool surfaces only:
- LangGraph workflow: internal executor.
- OpenAI: environment-configured; provider-success required for release.
- Zo: only when existing mode/secret/capability gate permits.
- Publication: keep disabled/dry-run only.
- Paid media: keep disabled.

Never request/commit secrets. Never hardcode production user IDs. Approval reviewer identity must remain server-derived from authenticated `principal.user_id`.

## Required verification
```bash
pnpm install --frozen-lockfile
pnpm --filter @amc/shared build
python -m pip install -e "./services/langgraph[dev]"
python -m pytest services/langgraph/tests/test_role_os_runtime.py services/langgraph/tests/test_role_os_release_candidate.py -q
python -m pytest services/langgraph/tests/test_runs.py services/langgraph/tests/test_delivery_gate.py services/langgraph/tests/test_provider_semantics.py services/langgraph/tests/test_proofs.py services/langgraph/tests/test_runtime_operator_actions.py -q
python -m pytest services/langgraph/tests -q
pnpm --filter @amc/shared test
pnpm --filter @amc/web test
pnpm --filter @amc/shared typecheck
pnpm --filter @amc/web typecheck
pnpm --filter @amc/shared build
pnpm --filter @amc/web build
make gates
```

Run Playwright release smoke when CI/runtime dependencies are available. Never convert SKIP/NOT_APPLICABLE into PASS.

## Staging acceptance
Prove: run creation → protected artifacts → needs_approval → authenticated approval → completed delivery → COMPLETE proof → delivered outbox. Also prove degraded output, missing demanded evidence, rejected/stale approval remain blocked, and recovery/compensation/replay paths work.

## Definition of done
Report exact base/head SHAs, changed files, 28/28 disposition status, exact test/gate results, staging state sequence, recovery evidence, tools enabled/disabled, and unresolved external requirements. Conclude only `READY_FOR_HUMAN_DEPLOYMENT_APPROVAL` or `BLOCKED:<reasons>`.

Do not merge `master`, deploy, provision production secrets, or claim genuine acceptance. Genuine acceptance must come from an authenticated authorized human reviewing the exact tested revision.
