"""Bounded retry for the Drive and Notion clients.

At most ``MAX_RETRIES`` retries after the first attempt, on 429, 5xx or a
transport error, with exponential backoff, full jitter and ``Retry-After``
honoured. Error messages carry the method, URL path and status only, never a
request body or header, so a credential cannot leak through an exception.
"""

from __future__ import annotations

import random
import time
from typing import Callable
from urllib.parse import urlsplit

import httpx

MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 16.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class ApiError(RuntimeError):
    """An API call failed after the allowed retries, or with a non-retryable status."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    ok_status: frozenset[int] = frozenset(),
    **kwargs,
) -> httpx.Response:
    """Send a request, retrying transient failures; raise ``ApiError`` otherwise.

    A 2xx response, or one whose status is in ``ok_status`` (for example 308
    during a resumable upload), is returned.
    """
    path = urlsplit(url).path
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if attempt == MAX_RETRIES:
                raise ApiError(f"{method} {path} failed: {type(exc).__name__}") from None
            sleep(_backoff(attempt, None))
            continue
        if response.is_success or response.status_code in ok_status:
            return response
        if response.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
            sleep(_backoff(attempt, _retry_after_seconds(response)))
            continue
        raise ApiError(f"{method} {path} returned {response.status_code}", status=response.status_code)
    raise AssertionError("unreachable")  # pragma: no cover


def _backoff(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(retry_after, MAX_DELAY_SECONDS)
    ceiling = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * (2 ** attempt))
    return random.uniform(0, ceiling)
