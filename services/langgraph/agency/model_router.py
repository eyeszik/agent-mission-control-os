"""Explicitly authorized multi-provider model routing with bounded backpressure.

No adapter is contacted when this module is imported. Remote calls require an
operation-specific authorization reference and an allowlisted provider. This
module does not promise remote effect exactly-once semantics or global quota
coordination across independent worker processes.

Dialects were checked against the providers' official Python SDKs (google-genai
2.31.0, openai 3.31.0 and anthropic 1.15.0 from PyPI): request and response
field names, the Gemini API-key header and model path, and the finish/stop
reasons. A response cut off at the output cap is ``OUTPUT_TRUNCATED``; a
refusal or a safety/policy stop is ``OUTPUT_REFUSED``; neither is retried. A
response without usage reports ``{}``: unknown, never zero.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import random
import re
import threading
import time
from typing import Any, Callable, Mapping, Sequence

import httpx

from services.langgraph.agency.ace_controls import Capability, route_capability


class ProviderFailure(RuntimeError):
    def __init__(self, provider: str, status: int | None, reason: str) -> None:
        self.provider, self.status, self.reason = provider, status, reason
        super().__init__(f"{provider}: {reason} ({status})")


class NoEligibleProvider(ProviderFailure):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.input_schema, dict):
            raise ValueError("nonempty tool name and object schema required")
        if self.input_schema.get("type") != "object":
            raise ValueError("tool input schema must declare object")


@dataclass(frozen=True)
class ToolInvocation:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelResult:
    provider: str
    model: str
    text: str
    tool_calls: tuple[ToolInvocation, ...]
    usage: dict[str, int]
    attempts: int
    route: tuple[str, ...]


def _tool_message(raw: Any) -> tuple[ToolInvocation, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ProviderFailure("router", None, "MALFORMED_TOOL_CALLS")
    calls = []
    for item in raw:
        if not isinstance(item, dict):
            raise ProviderFailure("router", None, "MALFORMED_TOOL_CALL")
        func = item.get("function", item)
        if not isinstance(func, dict) or not isinstance(func.get("name"), str):
            raise ProviderFailure("router", None, "MALFORMED_TOOL_NAME")
        args = func.get("arguments", func.get("input", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError as exc:
                raise ProviderFailure("router", None, "MALFORMED_TOOL_ARGUMENTS") from exc
        if not isinstance(args, dict):
            raise ProviderFailure("router", None, "MALFORMED_TOOL_ARGUMENTS")
        calls.append(ToolInvocation(name=func["name"], arguments=args))
    return tuple(calls)


# Terminal, non-retryable output outcomes (same prompt and cap would repeat them).
NON_RETRYABLE_OUTPUT = frozenset({"OUTPUT_TRUNCATED", "OUTPUT_REFUSED"})
# Gemini model ids become a URL path segment; refuse anything that could change the path.
_GEMINI_MODEL = re.compile(r"^(?:models/)?[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_GEMINI_TRUNCATED = frozenset({"MAX_TOKENS"})
_OPENAI_TRUNCATED = frozenset({"length"})
_ANTHROPIC_TRUNCATED = frozenset({"max_tokens", "model_context_window_exceeded"})


def _counts(**values: Any) -> dict[str, int]:
    return {k: int(v or 0) for k, v in values.items()}


class HttpModelAdapter:
    """Provider dialect and endpoint allowlist; no arbitrary URL invocation."""

    ENDPOINTS = {
        "openai": "https://api.openai.com/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/messages",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
        "ollama": "http://127.0.0.1:11434/api/chat",
    }
    CREDENTIALED = frozenset({"openai", "anthropic", "gemini"})

    def __init__(self, provider: str, *, credential: str | None,
                 client: httpx.Client | None = None, timeout: float = 45.0) -> None:
        if provider not in self.ENDPOINTS or timeout <= 0:
            raise ValueError("unsupported provider or timeout")
        if provider in self.CREDENTIALED and not credential:
            raise PermissionError("provider credentials unavailable")
        self.provider = provider
        self.credential = credential
        self.client = client if client is not None else httpx.Client(timeout=timeout)
        self.timeout = timeout

    def _url(self, model: str) -> str:
        if self.provider != "gemini":
            return self.ENDPOINTS[self.provider]
        if not _GEMINI_MODEL.match(model) or ".." in model:
            raise ValueError("invalid gemini model id")
        name = model if model.startswith("models/") else f"models/{model}"
        return self.ENDPOINTS["gemini"].format(model=name)

    def invoke(self, *, model: str, prompt: str, tools: Sequence[ToolSpec],
               max_output_tokens: int, temperature: float = 0,
               json_output: bool = False) -> tuple[str, tuple[ToolInvocation, ...], dict[str, int]]:
        if not model or not prompt or not 1 <= max_output_tokens <= 8192 or not 0 <= temperature <= 2:
            raise ValueError("invalid model invocation")
        if self.provider == "gemini" and tools:
            raise ValueError("tool calls are not implemented for the gemini dialect")
        url = self._url(model)
        headers = {"content-type": "application/json"}
        # Keep trace context off payloads and logs, and only use the configured
        # global propagator. No credential content is attached to spans.
        try:
            from opentelemetry.propagate import inject
            inject(headers)
        except ImportError:
            pass
        if self.provider == "openai":
            headers["authorization"] = f"Bearer {self.credential}"
            body: dict[str, Any] = {
                "model": model, "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_output_tokens, "temperature": temperature,
            }
            if tools:
                body["tools"] = [
                    {"type": "function", "function": {
                        "name": t.name, "description": t.description, "parameters": t.input_schema,
                    }} for t in tools
                ]
        elif self.provider == "anthropic":
            headers["x-api-key"] = str(self.credential)
            headers["anthropic-version"] = "2023-06-01"
            body = {
                "model": model, "max_tokens": max_output_tokens,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            }
            if tools:
                body["tools"] = [
                    {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                    for t in tools
                ]
        elif self.provider == "gemini":
            headers["x-goog-api-key"] = str(self.credential)
            config: dict[str, Any] = {"maxOutputTokens": max_output_tokens, "temperature": temperature}
            if json_output:
                config["responseMimeType"] = "application/json"
            body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}
        else:
            body = {
                "model": model, "messages": [{"role": "user", "content": prompt}],
                "stream": False, "options": {"temperature": temperature, "num_predict": max_output_tokens},
            }
            if json_output:
                body["format"] = "json"
            if tools:
                body["tools"] = [
                    {"type": "function", "function": {
                        "name": t.name, "description": t.description, "parameters": t.input_schema,
                    }} for t in tools
                ]
        try:
            response = self.client.post(url, json=body, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise ProviderFailure(self.provider, None, "TIMEOUT_UNCONFIRMED") from exc
        except httpx.TransportError as exc:
            raise ProviderFailure(self.provider, None, "TRANSPORT_UNCONFIRMED") from exc
        if response.status_code >= 400:
            raise ProviderFailure(self.provider, response.status_code, "HTTP_PROVIDER_ERROR")
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("response not an object")
            stop: str | None = None
            if self.provider == "openai":
                choice = payload["choices"][0]
                message = choice["message"]
                if message.get("refusal") or choice.get("finish_reason") == "content_filter":
                    stop = "OUTPUT_REFUSED"
                elif choice.get("finish_reason") in _OPENAI_TRUNCATED:
                    stop = "OUTPUT_TRUNCATED"
                text = message.get("content") or ""
                calls = _tool_message(message.get("tool_calls"))
                usage = payload.get("usage")
                tokens = _counts(input_tokens=usage.get("prompt_tokens"),
                                 output_tokens=usage.get("completion_tokens")) if usage else {}
            elif self.provider == "anthropic":
                if payload.get("stop_reason") == "refusal":
                    stop = "OUTPUT_REFUSED"
                elif payload.get("stop_reason") in _ANTHROPIC_TRUNCATED:
                    stop = "OUTPUT_TRUNCATED"
                blocks = payload["content"]
                text = "\n".join(x["text"] for x in blocks if x.get("type") == "text")
                calls = _tool_message([
                    {"name": x["name"], "input": x["input"]}
                    for x in blocks if x.get("type") == "tool_use"
                ])
                usage = payload.get("usage")
                tokens = _counts(input_tokens=usage.get("input_tokens"),
                                 output_tokens=usage.get("output_tokens")) if usage else {}
            elif self.provider == "gemini":
                candidates = payload.get("candidates") or []
                if not candidates:
                    if (payload.get("promptFeedback") or {}).get("blockReason"):
                        raise ProviderFailure(self.provider, None, "OUTPUT_REFUSED")
                    raise ValueError("no candidates")
                candidate = candidates[0]
                finish = candidate.get("finishReason")
                if finish in _GEMINI_TRUNCATED:
                    stop = "OUTPUT_TRUNCATED"
                elif finish not in (None, "STOP"):
                    stop = "OUTPUT_REFUSED"
                parts = (candidate.get("content") or {}).get("parts") or []
                # Thought summaries are not the answer.
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                calls = ()
                usage = payload.get("usageMetadata")
                # Thinking tokens are counted as output so budgets stay conservative.
                tokens = _counts(
                    input_tokens=usage.get("promptTokenCount"),
                    output_tokens=int(usage.get("candidatesTokenCount") or 0)
                    + int(usage.get("thoughtsTokenCount") or 0),
                ) if usage else {}
            else:
                if payload.get("done_reason") == "length":
                    stop = "OUTPUT_TRUNCATED"
                message = payload["message"]
                text = message.get("content") or ""
                calls = _tool_message(message.get("tool_calls"))
                reported = "prompt_eval_count" in payload or "eval_count" in payload
                tokens = _counts(input_tokens=payload.get("prompt_eval_count"),
                                 output_tokens=payload.get("eval_count")) if reported else {}
            if not isinstance(text, str) or any(v < 0 for v in tokens.values()):
                raise ValueError("invalid model result")
        except (TypeError, KeyError, IndexError, ValueError, AttributeError) as exc:
            raise ProviderFailure(self.provider, None, "INVALID_PROVIDER_RESPONSE") from exc
        if stop:
            raise ProviderFailure(self.provider, response.status_code, stop)
        return text, calls, tokens


class ModelRouter:
    """Bounded retry with jitter, circuit cooldown and per-process spacing.

    Model fallback only uses explicitly allowed providers satisfying the exact
    capability and task complexity. Process-local quotas are NOT distributed
    rate limits; production schedulers must additionally enforce global limits.
    """

    def __init__(
        self, *, capabilities: Sequence[Capability],
        adapters: Mapping[str, HttpModelAdapter],
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
        max_attempts: int = 3, cooldown_seconds: float = 60.0,
        max_wait_seconds: float = 30.0,
    ) -> None:
        if not 1 <= max_attempts <= 5 or cooldown_seconds <= 0 or max_wait_seconds < 0:
            raise ValueError("invalid bounded router policy")
        self.capabilities = tuple(capabilities)
        self.adapters = dict(adapters)
        self.sleep, self.clock, self.jitter = sleep, clock, jitter
        self.max_attempts = max_attempts
        self.cooldown_seconds, self.max_wait_seconds = cooldown_seconds, max_wait_seconds
        self._lock = threading.Lock()
        self._open_until: dict[str, float] = {}
        self._next_request_at: dict[str, float] = {}

    def _acquire_slot(self, capability: Capability) -> None:
        with self._lock:
            now = self.clock()
            wait = max(0.0, self._next_request_at.get(capability.provider_id, now) - now)
            if wait > self.max_wait_seconds:
                raise ProviderFailure(capability.provider_id, 429, "LOCAL_BACKPRESSURE")
            self._next_request_at[capability.provider_id] = (
                now + wait + 60.0 / capability.rate_limit_per_minute
            )
        if wait:
            self.sleep(wait)

    def invoke(
        self, *, prompt: str, capability: str, complexity: int,
        allowed_providers: frozenset[str], authorization_ref: str,
        tools: Sequence[ToolSpec] = (), max_output_tokens: int = 1024,
        json_output: bool = False, temperature: float = 0,
    ) -> ModelResult:
        if not authorization_ref.strip():
            raise PermissionError("operation-specific model invocation authorization required")
        with self._lock:
            now = self.clock()
            unavailable = frozenset(
                provider for provider, until in self._open_until.items() if until > now
            )
        options = route_capability(
            required=capability, complexity=complexity,
            providers=self.capabilities, allowed_providers=allowed_providers,
            disabled=unavailable,
        )
        if not options:
            raise NoEligibleProvider("router", None, "NO_ELIGIBLE_CAPABILITY")
        attempts = 0
        route: list[str] = []
        last_failure: ProviderFailure | None = None
        for candidate in options:
            adapter = self.adapters.get(candidate.provider_id)
            if adapter is None:
                continue
            route.append(candidate.provider_id)
            for attempt in range(self.max_attempts):
                try:
                    self._acquire_slot(candidate)
                    attempts += 1
                    kwargs: dict[str, Any] = {"temperature": temperature}
                    if json_output:
                        kwargs["json_output"] = True
                    text, calls, usage = adapter.invoke(
                        model=candidate.model_id, prompt=prompt, tools=tools,
                        max_output_tokens=max_output_tokens, **kwargs,
                    )
                    with self._lock:
                        self._open_until.pop(candidate.provider_id, None)
                    return ModelResult(
                        provider=candidate.provider_id, model=candidate.model_id,
                        text=text, tool_calls=calls, usage=usage,
                        attempts=attempts, route=tuple(route),
                    )
                except ProviderFailure as exc:
                    last_failure = exc
                    temporary = exc.status in {429, 503} or exc.reason in {
                        "TIMEOUT_UNCONFIRMED", "TRANSPORT_UNCONFIRMED"
                    }
                    if temporary and attempt + 1 < self.max_attempts:
                        # Full-jitter bounded exponential delay.
                        backoff = min(8.0, 0.5 * 2 ** attempt) * max(0.0, min(1.0, self.jitter()))
                        if backoff:
                            self.sleep(backoff)
                        continue
                    with self._lock:
                        self._open_until[candidate.provider_id] = self.clock() + self.cooldown_seconds
                    break
        # The last provider failure is chained so callers can see why (e.g. truncation).
        raise NoEligibleProvider("router", None, "ALL_AUTHORIZED_ROUTES_UNAVAILABLE") from last_failure
