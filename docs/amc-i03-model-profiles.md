# AMC I03: pinned model profiles, Gemini, and agency generation through the model router

**Status:** BUILD_COMPLETE locally for this increment (sandbox and fake-transport evidence only).
It is not RELEASE_ELIGIBLE, DEPLOYMENT_VERIFIED or RUNTIME_ACTIVE, and it authorizes no external action.
**Base:** `master` at `990847ef725c835b77dadab705369bb39c1006f4`.
No live provider was called while building this increment. No external effect was performed.

## Task contract

| Field | Value |
|---|---|
| Objective | Route agency generation through the canonical model router, add Gemini, and make the provider selectable and pinned per run. A Gemini-only configuration must work without `OPENAI_API_KEY`. |
| Non-goals | Nango, live action adapters, workers, storage, creative renderers, deployment. These are later increments (see the plan below). |
| Actor and tenant | Unchanged. The run is created by the authenticated principal, and the pin is written server-side. |
| Deliverables | `agency/model_profiles.py`; the Gemini dialect in `agency/model_router.py`; the `graph/agency/llm.py` refactor; the run pin in `api/routes/agency.py`; tests; docs. |
| Acceptance | `test_amc_i03_model_profiles.py` (23 tests), the rewritten provider and budget tests, the full backend suite, and the 7 verifier gates. |
| Authorized effects | Local files and tests only. No provider call, deployment, spend or communication. |
| Stop conditions | A failed gate after 3 evidence-driven corrections, or any need for a live credential. |

## What changed

| Area | Change | Files |
|---|---|---|
| Canonical routing | `generate_structured` no longer builds a LangChain client. Every call goes through `ModelRouter`/`HttpModelAdapter`. `generate_structured` owns retries: the router makes one call per route per attempt, and the adapters do not retry. Every retry debits the same run token budget. | `graph/agency/llm.py` |
| Gemini | A new `gemini` dialect calls `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` with the `x-goog-api-key` header. It sends `contents[].parts[].text` and `generationConfig.{maxOutputTokens,temperature,responseMimeType}`, and reads `candidates[0].content.parts[].text` (skipping thought parts), `finishReason`, `promptFeedback.blockReason` and `usageMetadata`. Gemini model ids are checked before they become a URL path segment. Tool calls are not implemented for Gemini and are refused, never simulated. | `agency/model_router.py` |
| Truncation and refusal | All dialects now recognise a response cut off at the output cap (`OUTPUT_TRUNCATED`) and a refusal or safety/policy stop (`OUTPUT_REFUSED`). Neither is retried, and both degrade the outcome. | `agency/model_router.py` |
| Unknown usage | A response without usage reports `{}`. The outcome then has `usage_reported: false` and an `unreported_token_estimate`, which `tokens_spent` counts. The same applies to failed calls that may have been billed. Unknown usage never reads as zero. | `agency/model_router.py`, `graph/agency/llm.py` |
| Model profiles | `ModelProfile` holds the primary route plus explicitly allowed fallbacks. Precedence is authorized run, then project, then tenant, then deployment default. The deployment default comes from `AMC_LLM_PROVIDER` (default `openai`), the model variable for each provider, and `AMC_LLM_FALLBACK_PROVIDERS` (default none). | `agency/model_profiles.py` |
| Run pinning | A new agency run stores `metadata.model_profile`: the profile plus its hash, or the selection error. Every stage, and every resume, uses the pin, never the current environment. A pin that no longer matches its hash is refused. | `api/routes/agency.py`, `graph/agency/nodes.py` |
| Revocation recheck | Credentials are never pinned. Each call looks them up again, and drops a route whose key is gone or whose provider is in `AMC_LLM_DISABLED_PROVIDERS`. | `agency/model_profiles.py` |
| Clear failure | An unknown provider, a missing model or an invalid model id degrades with its own error class (`InvalidProviderSelection`, `ModelNotConfigured`, `InvalidModelId`, `InvalidModelInvocation`, `ProfilePinMismatch`). It never switches silently to another configured provider. Degraded output still blocks delivery, as before. | `graph/agency/llm.py` |

The OpenAI request is the same Chat Completions call as before: the same endpoint, model, `temperature`, `max_tokens` and timeout. `test_openai_default_is_unchanged` pins that.

## Provenance of provider facts

The Google AI documentation site was not reachable from this environment (the network proxy refused it). Provider facts were therefore taken from the providers' official Python SDKs, downloaded from PyPI and read as source. They were not used as runtime dependencies.

| Claim | Source | Limitation |
|---|---|---|
| Gemini endpoint `v1beta`, host `generativelanguage.googleapis.com`, header `x-goog-api-key`, path `models/{model}:generateContent` | `google-genai` 2.31.0: `_api_client.py` (base URL, API version, API-key header); `models.py` (`{model}:generateContent`); `_transformers.t_model` (adds the `models/` prefix) | This is the SDK's view of the Developer API (not Vertex). No live call was made. |
| Gemini request fields `contents`, `generationConfig`, `maxOutputTokens`, `responseMimeType`, `temperature` | `google-genai` 2.31.0 `models.py`: `_GenerateContentParameters_to_mldev` and its config converter | As above. |
| Gemini response fields `candidates`, `finishReason`, `promptFeedback`, `usageMetadata` (`promptTokenCount`, `candidatesTokenCount`, `thoughtsTokenCount`, `totalTokenCount`), and the `FinishReason` and `BlockedReason` enums | `google-genai` 2.31.0 `models.py` (`_GenerateContentResponse_from_mldev`, `_Candidate_from_mldev`), `types.py` (enums, camelCase alias generator in `_common.py`) | Counting thinking tokens as output is a conservative budgeting choice, not a billing claim. |
| `GOOGLE_API_KEY` read before `GEMINI_API_KEY` | `google-genai` 2.31.0 `_api_client.py` | |
| OpenAI `finish_reason` values (`stop`, `length`, `tool_calls`, `content_filter`, `function_call`) and `message.refusal` | `openai` 3.31.0: `types/chat/chat_completion.py`, `chat_completion_message.py` | |
| Anthropic `stop_reason` values, including `max_tokens`, `refusal` and `model_context_window_exceeded` | `anthropic` 1.15.0: `types/stop_reason.py` | |

Tests use fixture model ids such as `gemini-fixture-model`. This increment names no real Gemini model and gives Gemini no default: `AMC_GEMINI_MODEL` must be set. No price or cost comparison is made or recorded. Pricing metadata, measured usage, estimated cost and settled billing remain separate open work (see the plan below).

## Configuration

```bash
# Gemini only, no OpenAI key needed:
AMC_LLM_PROVIDER=gemini
GEMINI_API_KEY=<secret>      # or GOOGLE_API_KEY, which takes precedence
AMC_GEMINI_MODEL=<model id>

# Optional, off by default: try OpenAI if Gemini fails.
AMC_LLM_FALLBACK_PROVIDERS=openai

# Refuse a provider immediately, including for runs that already pinned it.
AMC_LLM_DISABLED_PROVIDERS=gemini
```

Container secrets take effect only after a redeploy. Saving a key grants no spending authority, and every run stays bounded by `AMC_MAX_TOKENS_PER_RUN`.

## Known limits of this increment

- **No route writes run, project or tenant profiles.** `resolve_profile` implements the precedence, but nothing writes those levels yet. Writing them needs an authorized, audited settings API, which is planned.
- **The OpenAI path no longer goes through `langchain_openai`.** Environment overrides that LangChain honoured, such as `OPENAI_BASE_URL`, are therefore not applied. The repository neither documents nor sets them. `langchain-openai` is still used by `graph/nodes/planner.py` and `quality/grounded_evaluator.py`, which stay OpenAI-only and are unchanged.
- **Fallback is per attempt and per process.** A fallback route is tried only when it is listed. Circuit state is not shared across workers.
- **Failed calls have unknown usage.** They count at a conservative estimate (prompt estimate plus output cap). That can over-count: it never under-counts.

## Capability register (reverified at `990847ef`)

`Status` uses the evidence labels from the brief. "Repair" is the smallest next step, not a commitment.

| Capability | Status | Evidence | Smallest repair, and what it needs |
|---|---|---|---|
| Agency generation with OpenAI, Anthropic, Gemini or Ollama | VERIFIED (fake transport) | This increment; `test_amc_i03_model_profiles.py` | Live smoke per provider. Needs a key, an explicit authorization and a budget. |
| Run, project and tenant model selection | PROPOSED | `resolve_profile` exists, no writer | Authorized settings API with audit and compare-and-set. |
| LIVE external actions | LIVE_GATED | `actions/governance.live_enablement()` returns `DISABLED` and gives its reasons | Reviewed provider adapters for each operation, plus authorization. |
| CMS, email, ads, storage and identity adapters | SIMULATED | `actions/adapters.py`: `SandboxCmsDraft`, `SandboxCmsPublish`, `SandboxEmailSend`, `SandboxAdsSpend`, `SandboxStorageDelete`, `SandboxGovernanceGrant` | Choose providers, then implement each behind the gateway. Needs a provider choice from the owner. |
| Step-up authentication | PROVIDER_GAP | `gateway.py`: `STEP_UP_UNAVAILABLE` blocker | Server-verified step-up bound to actor, session and action, with expiry and replay tests. Needs an identity-provider decision. |
| Budget management API | PROPOSED | `/actions/budget` has only GET and `simulate` | Authorized, audited allocation endpoint with compare-and-set. |
| Shared action rate limits | PROPOSED | No limiter in `agency/actions` | Route and provider limits with retry timing. |
| Node/Next.js sandbox | PROVIDER_GAP | `execution_fabric/adapters/code_sandbox.py`: allowlist is `py_compile` only | Node adapter through the existing fabric, with a locked dependency install separate from the build. |
| Async agency runs (job id, SSE, cancel) | PROPOSED | `create_agency_run` runs the graph inline (`_run_and_record_events`) | Run it through durable jobs. |
| Always-on worker | NOT_MEASURED | `durable/build_dag.runtime_active` requires a deployed worker; none is deployed | Deploy plus heartbeat evidence. Needs deployment authorization. |
| R2 object storage | PROVIDER_GAP | `project_os/storage.py`: `R2StorageAdapter` reports `UNVERIFIED_EXTERNAL_BINDING` | Reviewed client with integrity read-back. |
| Hosted media generation | LIVE_GATED | `vnexus/media_fabric.py`: hosted providers DISABLED, no network code | Reviewed adapter for each provider. |
| Local diffusion and Three.js | DEPENDENCY_REQUIRED | `agency/visual`: probed and blocked when absent | Licensed weights and runtime on the host. |
| Delivery contracts | Implemented, default `off` | `AMC_CONTRACT_MODE` | Shadow, then enforce rollout, as an operator decision. |
| Signed release evidence | DEPENDENCY_REQUIRED | `ace_release.SignedEvidenceBundle` needs an externally held key | Key custody. Needs the owner. |
| Nango-delegated connections | SOURCE_REQUIRED | No Nango code in this repository; `eyeszik/nango` is not attached to this session | Attach the repository and confirm the deployment mode and licence. |
| Telephony | SOURCE_REQUIRED | None in this repository | Provider and use-case selection. |
| VNEXUS original 14 prompts; EXT-/ART- ids | SOURCE_REQUIRED | Absent by design (`docs/vnexus-ace.md`, `VOID_DETECTED`) | Source material from the owner. Never invented. |

## Plan for the rest of the specification (dependency order)

| # | Increment | Depends on | Blocked on |
|---|---|---|---|
| I04 | Authorized model-profile settings API (project and tenant), readiness panel rows, pricing-metadata versioning with measured, estimated and settled cost kept separate | I03 | Nothing |
| I05 | Async agency runs on durable jobs (job id, progress, SSE, cancellation, lease recovery) | I03 | Nothing |
| I06 | Action-plane hardening: budget allocation API, shared rate limits, approval change preview, effect receipts | Existing ACE v12 | Nothing |
| I07 | Node sandbox through the fabric (locked install separate from the build, three-build cap, credit settlement) | I05 | Nothing |
| I08 | Nango credential references (AMC grants; Nango holds tokens; server-verified connect; authenticated webhooks) | I04 | The `eyeszik/nango` repository attached to this session, the deployment mode and licence |
| I09 | Step-up authentication | I06 | Identity-provider decision |
| I10 | Reviewed live adapters, one provider at a time | I06, I08, I09 | Provider choices, credentials, explicit authorization |
| I11 | Storage, creative and brand-operations items in §8 | I05 | Licensed dependencies and models, provider choices |
| I12 | Activation package and exact-revision smoke | All | Deployment accounts and authorization |

## Rollback

Revert this increment's commit. There is no migration and no schema change.

Runs created by this increment carry `metadata.model_profile`. Older code ignores it and reads `OPENAI_API_KEY` and `AMC_OPENAI_MODEL`, so those runs continue on OpenAI after a revert.
