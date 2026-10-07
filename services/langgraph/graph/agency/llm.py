import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from services.langgraph.core.config import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
PROMPT_TEMPLATE_VERSION = "agency-v1"
MAX_PROVIDER_ATTEMPTS = 3

# Cost bounds for every provider call (overridable per deployment).
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_OUTPUT_TOKENS = 2000
DEFAULT_MAX_TOKENS_PER_RUN = 60000
BUDGET_EXHAUSTED = "TokenBudgetExhausted"


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
    """Total tokens already consumed by a run, from its generation provenance."""
    total = 0
    for item in provenance or []:
        usage = item.get("usage") or {}
        total += int(usage.get("total_tokens") or 0)
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


def _add_usage(total: dict, response: object) -> None:
    metadata = getattr(response, "usage_metadata", None) or {}
    input_tokens = int(metadata.get("input_tokens") or 0)
    output_tokens = int(metadata.get("output_tokens") or 0)
    total["input_tokens"] += input_tokens
    total["output_tokens"] += output_tokens
    total["total_tokens"] += int(metadata.get("total_tokens") or (input_tokens + output_tokens))


def generate_structured(
    prompt: str,
    fallback: dict,
    *,
    schema_version: str = "agency-json-v1",
    max_attempts: int = MAX_PROVIDER_ATTEMPTS,
    run_tokens_spent: int = 0,
) -> GenerationOutcome:
    """
    Generate structured JSON with explicit provenance and degradation semantics.

    Provider absence/failure may return deterministic fallback data for local UX,
    but that result is always marked FALLBACK_DEGRADED and must not authorize
    release/delivery.

    Every attempt is bounded by a request timeout and an output-token cap, and
    must fit inside the run's remaining token budget (``run_tokens_spent`` is
    what earlier stages already used). Retries debit the same budget; once it
    cannot cover another attempt the outcome degrades with
    ``TokenBudgetExhausted`` instead of calling the provider again.
    """

    started_at = _now()
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("AMC_OPENAI_MODEL", DEFAULT_MODEL)

    if not api_key:
        return GenerationOutcome(
            data=fallback,
            mode="FALLBACK_DEGRADED",
            provider=None,
            model=None,
            schema_version=schema_version,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            prompt_hash=prompt_hash,
            attempts=0,
            started_at=started_at,
            completed_at=_now(),
            fallback_used=True,
            error_class="ProviderNotConfigured",
        )

    last_error: Optional[str] = None
    attempts = max(1, min(max_attempts, MAX_PROVIDER_ATTEMPTS))
    budget = max_tokens_per_run()
    output_cap = max_output_tokens()
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    full_prompt = prompt + "\n\nRespond with only one valid JSON object and no surrounding commentary."
    attempted = 0
    for attempt in range(1, attempts + 1):
        remaining = budget - run_tokens_spent - usage["total_tokens"]
        if remaining < estimate_prompt_tokens(full_prompt) + output_cap:
            last_error = BUDGET_EXHAUSTED
            logger.warning(
                "Agency run token budget exhausted",
                extra={"prompt_hash": prompt_hash, "run_tokens_spent": run_tokens_spent, "budget": budget},
            )
            break
        attempted = attempt
        try:
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=model,
                temperature=0.4,
                timeout=call_timeout_seconds(),
                max_retries=0,  # retries are owned (and budgeted) here
                max_tokens=output_cap,
            )
            response = llm.invoke(full_prompt)
            _add_usage(usage, response)
            data = _parse_json_content(response.content)
            return GenerationOutcome(
                data=data,
                mode="PROVIDER_SUCCESS",
                provider="openai",
                model=model,
                schema_version=schema_version,
                prompt_version=PROMPT_TEMPLATE_VERSION,
                prompt_hash=prompt_hash,
                attempts=attempt,
                started_at=started_at,
                completed_at=_now(),
                fallback_used=False,
                usage=dict(usage),
            )
        except Exception as exc:  # provider and schema failures share bounded retry policy
            last_error = type(exc).__name__
            logger.warning(
                "Agency provider attempt failed",
                extra={"attempt": attempt, "error_class": last_error, "prompt_hash": prompt_hash},
            )

    return GenerationOutcome(
        data=fallback,
        mode="FALLBACK_DEGRADED",
        provider="openai",
        model=model,
        schema_version=schema_version,
        prompt_version=PROMPT_TEMPLATE_VERSION,
        prompt_hash=prompt_hash,
        attempts=attempted,
        started_at=started_at,
        completed_at=_now(),
        fallback_used=True,
        error_class=last_error or "ProviderFailed",
        usage=dict(usage),
    )
