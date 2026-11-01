# UNBOUND v3 validation and acceptance evidence

Status: **PARTIAL**. This report covers incremental development, not production release.
Baseline #199 head: `6bfc3c9a83abc5b5c495a8d511d2a27c56c6c26b`;
current increment base: master merge `d93c8b8b` (identical source tree).
Candidate source identities are recorded in `v3-sources.json`; the containing feature
commit supplies the final Git revision. Python 3.11.17, Node24.19.0, pnpm10.29.3,
SQLite; loopback FastAPI/Next.js; no provider keys/models or production credentials.

## Observed checks

| ID | Command / selector | Expected | Observed | Status |
|---|---|---|---|---|
| T01 baseline | `python -m pytest services/langgraph/tests/test_innovation_contracts.py services/langgraph/tests/test_innovation_api.py -q` | Preserve v1 fixture path | 64 passed in27.01s before increment | VERIFIED |
| T01/02/05/07/08/10/11/12/13/14/15/16/17/18/19/22/23 | `AMC_DB_PATH=/tmp/unbound-v3-combined-final.db python -m pytest services/langgraph/tests/test_innovation_contracts.py services/langgraph/tests/test_innovation_api.py services/langgraph/tests/test_innovation_generation.py services/langgraph/tests/test_innovation_generation_api.py services/langgraph/tests/test_innovation_experiment.py services/langgraph/tests/test_ace_model_router.py services/langgraph/tests/test_amc_i03_model_profiles.py services/langgraph/tests/test_execution_fabric.py services/langgraph/tests/test_approval_authority.py -q` | Contract, provider-mock, actual local calculation, recovery, scope, existing fabric/authority regressions | 193 passed in23.62s | VERIFIED within tested scope |
| Shared contracts | `pnpm --filter @amc/shared test` | Existing plus versioned wire fixtures | 263 passed across20files | VERIFIED |
| Web unit | `pnpm --filter @amc/web test` | Existing plus API client cases | 97 passed across17files | VERIFIED |
| Type checking | `pnpm --filter @amc/shared typecheck`; `pnpm --filter @amc/web typecheck` | No type errors | Both passed | VERIFIED |
| Shared build | `pnpm --filter @amc/shared build` | Dist exports available | Passed | VERIFIED |
| T20 mobile E2E | `E2E_API_BASE_URL=http://127.0.0.1:8001 E2E_BASE_URL=http://127.0.0.1:3001 pnpm --filter @amc/web exec playwright test e2e/innovation.spec.ts e2e/innovation-capabilities.spec.ts` | Historical simulation + actual local receipt reload + missing-provider intent,390px | 3 passed in9.1s | VERIFIED local only |
| T03 real model invocation | Approved, configured actual provider | Actual invocation receipt | No usable model/credentials or invocation authorization available | BLOCKED |
| T04 independent brief relevance | Two real outputs plus relevance judgments | Brief-specific relevant differences | Mock tests prove differing prompts only | UNVERIFIED |
| T06 live synthesis | Live wildcard/hybrid/meta cohort | Counts, emergent mechanisms, parent refs | Only historical simulated cohort exists | BLOCKED |
| T09 actual research | Source-qualified retrieval receipts | Sources and conflicts inspected | No research adapter/in-scope retrieval performed | BLOCKED |
| T21 hosted CI | Exact incremental commit | All required checks conclude | Pending until separately observed | UNVERIFIED |
| Quality pilot | >=90% generation validity,>=80% independent relevance | Actual denominator/rubric/reviewers | No pilot | NOT_MEASURED |

## Actual experiment receipt

A real API/browser invocation produced `fabric-abfbc0cba6240d936a253389` with source
`art-proj_1-ir-a72c4f7586e6b32d960abeae25ed259a:v2`. Its exported read projection is the
clearly scoped regression fixture `packages/shared/tests/fixtures/innovation-local-computation.json`.
Its actual counts:39 disclosed inputs,39 exact-string retained representations,35 normalized
retained representations; redundant retained items baseline4/candidate0. One canonical permit,
one execution receipt and one matching observation receipt were present. The preregistered
lexical rule classified SUPPORTED. Inputs are authored simulation mechanisms plus four disclosed
synthetic case/whitespace variants; this is not market or semantic-originality evidence.
No experiment approval/release was fabricated; safe-local policy permits this fixed computation.

## Failures and repairs retained

- First generation API cohort found strict profile tuple serialization incompatible with
  FastAPI's response validation; the envelope now retains Python model values until the
  response model serializes JSON. Subsequent isolated generation cohort:13 passed.
- Concurrent local test processes contended on a shared default SQLite database. Failed
  logs were retained; final validation uses its own AMC_DB_PATH and passes. This does not
  demonstrate PostgreSQL concurrency behavior or erase the observed contention.
- First v3 browser cohort:1 failed,2 passed. The actual fabric computation returned200;
  frontend rejected `fabric-...` receipt IDs as UUIDs. Added a narrow feature projection
  of canonical proof schemas using the actual fabric ID format, preserved the original
  agency schema, and checked a real Python response fixture. Final browser cohort:3 passed.
- Tests assert wrong-purpose/self/stale approval refusal, including when the existing
  local development self-approval override is enabled. Unknown model outcomes remain
  RECONCILING and are not re-dispatched after lease expiry.

## Coverage limits and security assessment

No actual external model invocation, live research, independent semantic/relevance review,
commercial validation, generated-code execution, full accessibility audit, production
migration, public HTTPS, active durable worker deployment, or human release approval was
performed. No calibrated confidence score or release recommendation is supplied.
The finite refusal suite does not prove universal security. Existing auth, approval,
artifact ownership, CAS and source readback remain authoritative.

No new dependency was installed. Model input is serialized as untrusted data, no tools are
passed, and model output is strict data only. Remote providers fail closed despite keys
because paid-spend enforcement is absent. Canonical Ollama adapter now forwards output
limits/JSON mode and rejects truncation. All provider tests use explicitly fictional actors,
models and mock transport; they are not real live-provider receipts.

No dollar cost or model token expenditure was measured; monetary cost is UNKNOWN. The
provider stage admits one call,8192 output tokens,60000 prompt bytes,30-second timeout,
zero paid-API ceiling, no fallback and no automatic retry. Local experiment admission is
64 strings of2000characters maximum with one fabric invocation and no network/generated code.
Exact aggregate tool/token usage is not available; no unobservable cost cap is claimed.

Final production frontend build passed (`pnpm --filter @amc/web build`), without
publishing it. All seven `make gates` checks passed on final source bytes; the integrity
manifest covers317criticalfiles. Python compileall and git diff whitespace checks passed.
The browser schema repair did not alter the global agency UUID contract; a separate
fabric-ID projection and actual computation response fixture cover the feature boundary.

CI for this new increment is pending until its exact head and final conclusions are
observed. Earlier #199 CI success is never substituted for incremental CI evidence.
