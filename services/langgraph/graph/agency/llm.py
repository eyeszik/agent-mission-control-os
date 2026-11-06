import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional

import httpx

from services.langgraph.agency.ace_controls import Capability
from services.langgraph.agency.model_profiles import (
    ModelProfile,
    ProfileError,
    deployment_profile,
    pinned_profile,
    usable_routes,
)
from services.langgraph.agency.model_router import (
    NON_RETRYABLE_OUTPUT,
    HttpModelAdapter,
    ModelRouter,
    ProviderFailure,
)
from services.langgraph.core.config import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"  # kept for compatibility; the default now lives in model_profiles
PROMPT_TEMPLATE_VERSION = "agency-v1"
MAX_PROVIDER_ATTEMPTS = 3

# Cost bounds for every provider call (overridable per deployment).
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_OUTPUT_TOKENS = 2000
DEFAULT_MAX_TOKENS_PER_RUN = 60000
BUDGET_EXHAUSTED = "TokenBudgetExhausted"
ADAPTER_MAX_OUTPUT_TOKENS = 8192  # HttpModelAdapter's per-call ceiling


def _env_number(name: str, default: float, *, minimum: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


def call_timeout_seconds() -> float:
    return _env_number("AMC_LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, minimum=1.0)


def max_output_tokens() -> int:
    return int(_env_number("AMC_LLM_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS, minimum=64))


def max_tokens_per_run() -> int:
    return int(_env_number("AMC_MAX_TOKENS_PER_RUN", DEFAULT_MAX_TOKENS_PER_RUN, minimum=1))


def estimate_prompt_tokens(prompt: str) -> int:
    # Conservative upper-bound estimate (~4 characters per token) used only to
    # decide whether another attempt can still fit inside the run budget.
    return len(prompt) // 3 + 1


def tokens_spent(provenance: list[dict] | None) -> int:
    """Total tokens already consumed by a run, from its generation provenance.

    Calls whose usage the provider did not report count at their estimate
    (``unreported_token_estimate``), so unknown usage never reads as zero."""
    total = 0
    for item in provenance or []:
        usage = item.get("usage") or {}
        total += int(usage.get("total_tokens") or 0)
        total += int(item.get("unreported_token_estimate") or 0)
    return total


@dataclass(frozen=True)
class GenerationOutcome:
    data: dict
    mode: str
    provider: Optional[str]
    model: Optional[str]
    schema_version: str
    prompt_version: str
    prompt_hash: str
    attempts: int
    started_at: str
    completed_at: str
    fallback_used: bool
    error_class: Optional[str] = None
    usage: Optional[dict] = None
    # Provider routes tried, in order; more than one means a configured fallback was used.
    route: tuple[str, ...] = ()
    profile_hash: Optional[str] = None
    # False when any provider call's usage is unknown; then the estimate below applies.
    usage_reported: bool = True
    unreported_token_estimate: int = 0

    @property
    def degraded(self) -> bool:
        return self.mode != "PROVIDER_SUCCESS"

    def provenance(self, task: str) -> dict:
        return {
            "task": task,
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "schema_version": self.schema_version,
            "prompt_version": self.prompt_version,
            "prompt_hash": self.prompt_hash,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "fallback_used": self.fallback_used,
            "error_class": self.error_class,
            "usage": self.usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "route": list(self.route),
            "profile_hash": self.profile_hash,
            "usage_reported": self.usage_reported,
            "unreported_token_estimate": self.unreported_token_estimate,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json_content(content: object) -> dict:
    if not isinstance(content, str):
        raise ValueError("provider response content is not a string")
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("provider response must be a JSON object")
    return parsed


def _add_usage(total: dict, usage: Mapping[str, int]) -> None:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    total["input_tokens"] += input_tokens
    total["output_tokens"] += output_tokens
    total["total_tokens"] += input_tokens + output_tokens


def _error_class(code: str) -> str:
    """``OUTPUT_TRUNCATED`` -> ``OutputTruncated``, matching the existing error_class style."""
    return "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", code) if part) or "ProviderFailed"


def _http_client(timeout: float) -> httpx.Client:
    """Seam for tests: they swap in an ``httpx.MockTransport``."""
    return httpx.Client(timeout=timeout)


def run_profile(run_metadata: Optional[Mapping]) -> ModelProfile:
    """The run's pinned profile; runs created before pinning use the deployment default."""
    return pinned_profile(run_metadata) or deployment_profile()


def generate_structured(
    prompt: str,
    fallback: dict,
    *,
    schema_version: str = "agency-json-v1",
    max_attempts: int = MAX_PROVIDER_ATTEMPTS,
    run_tokens_spent: int = 0,
    run_metadata: Optional[Mapping] = None,
    authorization_ref: Optional[str] = None,
) -> GenerationOutcome:
    """
    Generate structured JSON with explicit provenance and degradation semantics.

    The provider and model come from the run's pinned model profile
    (``run_metadata.model_profile``; older runs use the deployment default), and
    every call goes through the canonical ``ModelRouter``. Fallback providers are
    tried only when the profile lists them.

    Provider absence/failure may return deterministic fallback data for local UX,
    but that result is always marked FALLBACK_DEGRADED and must not authorize
    release/delivery. An invalid model selection degrades with its own error
    class; it never silently switches provider.

    Every attempt is bounded by a request timeout and an output-token cap, and
    must fit inside the run's remaining token budget (``run_tokens_spent`` is
    what earlier stages already used). Retries are owned here: the router makes
    one call per route per attempt and the adapters do not retry. Retries debit
    the same budget; once it cannot cover another attempt the outcome degrades
    with ``TokenBudgetExhausted`` instead of calling the provider again. A
    truncated or refused output is not retried.
    """

    started_at = _now()
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def degraded(error_class: str, *, provider=None, model=None, attempted=0, usage=None,
                 route=(), profile_hash=None, usage_reported=True, unreported=0) -> GenerationOutcome:
        return GenerationOutcome(
            data=fallback,
            mode="FALLBACK_DEGRADED",
            provider=provider,
            model=model,
            schema_version=schema_version,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            prompt_hash=prompt_hash,
            attempts=attempted,
            started_at=started_at,
            completed_at=_now(),
            fallback_used=True,
            error_class=error_class,
            usage=usage,
            route=tuple(route),
            profile_hash=profile_hash,
            usage_reported=usage_reported,
            unreported_token_estimate=unreported,
        )

    try:
        profile = run_profile(run_metadata)
    except ProfileError as exc:
        return degraded(_error_class(exc.code))
    routes = usable_routes(profile)
    if not routes:
        return degraded("ProviderNotConfigured", profile_hash=profile.profile_hash)

    timeout = call_timeout_seconds()
    adapters = {r.provider: HttpModelAdapter(r.provider, credential=key, client=_http_client(timeout), timeout=timeout)
                for r, key in routes}
    try:
        return _generate_via_router(
            prompt_hash=prompt_hash, profile=profile, routes=routes, adapters=adapters, timeout=timeout,
            authorization_ref=authorization_ref, max_attempts=max_attempts, run_tokens_spent=run_tokens_spent,
            prompt=prompt, schema_version=schema_version, started_at=started_at, degraded=degraded,
        )
    finally:
        for adapter in adapters.values():
            adapter.client.close()


def _generate_via_router(*, prompt_hash, profile, routes, adapters, timeout, authorization_ref, max_attempts,
                         run_tokens_spent, prompt, schema_version, started_at, degraded) -> GenerationOutcome:
    output_cap = min(max_output_tokens(), ADAPTER_MAX_OUTPUT_TOKENS)
    capabilities = tuple(
        Capability(provider_id=r.provider, model_id=r.model, capabilities=frozenset({"structured_output"}),
                   complexity_ceiling=5, priority=i, rate_limit_per_minute=6000, cost_per_million_tokens=0)
        for i, (r, _key) in enumerate(routes)
    )
    router = ModelRouter(capabilities=capabilities, adapters=adapters, max_attempts=1, sleep=lambda _s: None)
    allowed = frozenset(adapters)
    authorization = authorization_ref or f"agency-generation:{prompt_hash}"

    last_error: Optional[str] = None
    attempts = max(1, min(max_attempts, MAX_PROVIDER_ATTEMPTS))
    budget = max_tokens_per_run()
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    full_prompt = prompt + "\n\nRespond with only one valid JSON object and no surrounding commentary."
    per_call = estimate_prompt_tokens(full_prompt) + output_cap
    unreported = 0  # estimated tokens for calls whose usage is unknown
    usage_reported = True
    attempted = 0
    tried: list[str] = []
    last_provider, last_model = profile.primary.provider, profile.primary.model
    for attempt in range(1, attempts + 1):
        remaining = budget - run_tokens_spent - usage["total_tokens"] - unreported
        # One attempt may call every allowed route once.
        if remaining < per_call * len(routes):
            last_error = BUDGET_EXHAUSTED
            logger.warning(
                "Agency run token budget exhausted",
                extra={"prompt_hash": prompt_hash, "run_tokens_spent": run_tokens_spent, "budget": budget},
            )
            break
        attempted = attempt
        try:
            result = router.invoke(
                prompt=full_prompt, capability="structured_output", complexity=1,
                allowed_providers=allowed, authorization_ref=authorization,
                max_output_tokens=output_cap, json_output=True, temperature=0.4,
            )
        except ValueError:
            # The adapter refused the request before sending it (e.g. a model id its
            # dialect cannot address). Nothing was sent, so nothing is retried.
            last_error = "InvalidModelInvocation"
            break
        except ProviderFailure as exc:
            cause = exc.__cause__ if isinstance(exc.__cause__, ProviderFailure) else exc
            # A request may have been billed even though it failed; its usage is unknown.
            unreported += per_call * len(routes)
            usage_reported = False
            tried += [r.provider for r, _key in routes]
            last_error = _error_class(cause.reason)
            logger.warning(
                "Agency provider attempt failed",
                extra={"attempt": attempt, "error_class": last_error, "prompt_hash": prompt_hash},
            )
            if cause.reason in NON_RETRYABLE_OUTPUT:
                break
            continue
        tried += list(result.route)
        last_provider, last_model = result.provider, result.model
        if result.usage:
            _add_usage(usage, result.usage)
        else:
            unreported += per_call
            usage_reported = False
        # Earlier routes in this attempt failed; their usage is unknown.
        if len(result.route) > 1:
            unreported += per_call * (len(result.route) - 1)
            usage_reported = False
        try:
            data = _parse_json_content(result.text)
        except Exception as exc:  # schema failures share the bounded retry policy
            last_error = type(exc).__name__
            logger.warning(
                "Agency provider attempt failed",
                extra={"attempt": attempt, "error_class": last_error, "prompt_hash": prompt_hash},
            )
            continue
        return GenerationOutcome(
            data=data,
            mode="PROVIDER_SUCCESS",
            provider=result.provider,
            model=result.model,
            schema_version=schema_version,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            prompt_hash=prompt_hash,
            attempts=attempt,
            started_at=started_at,
            completed_at=_now(),
            fallback_used=False,
            usage=dict(usage),
            route=tuple(tried),
            profile_hash=profile.profile_hash,
            usage_reported=usage_reported,
            unreported_token_estimate=unreported,
        )

    return degraded(last_error or "ProviderFailed", provider=last_provider, model=last_model, attempted=attempted,
                    usage=dict(usage), route=tried, profile_hash=profile.profile_hash,
                    usage_reported=usage_reported, unreported=unreported)
