"""Network-free provider fakes for agency generation tests.

``generate_structured`` builds its HTTP client through ``llm._http_client``; the
``provider_http`` fixture (conftest) swaps in an ``httpx.MockTransport`` so tests
exercise the real adapter dialects without touching the network. Response shapes
follow the providers' official Python SDK types (openai, anthropic, google-genai).
"""

from __future__ import annotations

import json

import httpx


class FakeProviderHTTP:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responses: list = []
        self.timeouts: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]

    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]


def openai_reply(content: str, *, prompt_tokens: int = 0, completion_tokens: int = 0,
                 finish_reason: str = "stop", usage: bool = True, refusal: str | None = None) -> httpx.Response:
    body: dict = {"choices": [{"finish_reason": finish_reason,
                               "message": {"role": "assistant", "content": content, "refusal": refusal}}]}
    if usage:
        body["usage"] = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                         "total_tokens": prompt_tokens + completion_tokens}
    return httpx.Response(200, json=body)


def gemini_reply(text: str, *, prompt_tokens: int = 0, candidate_tokens: int = 0, thought_tokens: int = 0,
                 finish_reason: str = "STOP", usage: bool = True, thought: str | None = None) -> httpx.Response:
    parts = ([{"text": thought, "thought": True}] if thought else []) + [{"text": text}]
    body: dict = {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish_reason}]}
    if usage:
        body["usageMetadata"] = {"promptTokenCount": prompt_tokens, "candidatesTokenCount": candidate_tokens,
                                 "thoughtsTokenCount": thought_tokens,
                                 "totalTokenCount": prompt_tokens + candidate_tokens + thought_tokens}
    return httpx.Response(200, json=body)


def anthropic_reply(text: str, *, input_tokens: int = 0, output_tokens: int = 0,
                    stop_reason: str = "end_turn") -> httpx.Response:
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}], "stop_reason": stop_reason,
                                     "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}})
