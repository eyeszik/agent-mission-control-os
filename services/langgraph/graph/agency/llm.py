import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
PROMPT_TEMPLATE_VERSION = "agency-v1"
MAX_PROVIDER_ATTEMPTS = 3


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


def generate_structured(
    prompt: str,
    fallback: dict,
    *,
    schema_version: str = "agency-json-v1",
    max_attempts: int = MAX_PROVIDER_ATTEMPTS,
) -> GenerationOutcome:
    """
    Generate structured JSON with explicit provenance and degradation semantics.

    Provider absence/failure may return deterministic fallback data for local UX,
    but that result is always marked FALLBACK_DEGRADED and must not authorize
    release/delivery.
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
    for attempt in range(1, attempts + 1):
        try:
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(model=model, temperature=0.4)
            response = llm.invoke(
                prompt + "\n\nRespond with only one valid JSON object and no surrounding commentary."
            )
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
        attempts=attempts,
        started_at=started_at,
        completed_at=_now(),
        fallback_used=True,
        error_class=last_error or "ProviderFailed",
    )
