"""zo.computer integration — fail closed by default.

Mirrors the pattern already established by ``publication.py`` and
``paid_media.py``: an explicit mode switch defaults to disabled, and the
credential is read from the process environment only. This module never
accepts an API key as a parameter, never logs it, and never has a code path
that could echo it back in an error message or response payload.
"""

from __future__ import annotations

import os

import httpx

ZO_API_BASE = "https://api.zo.computer"


class ZoIntegrationError(RuntimeError):
    """Raised when a zo.computer call cannot be made or fails upstream."""


def zo_available() -> bool:
    """True only when explicitly enabled and a credential is present.

    Mode defaults to ``disabled`` exactly like ``AMC_PUBLICATION_MODE`` and
    ``AMC_PAID_MEDIA_MODE``, so an unset or misconfigured environment fails
    closed rather than silently attempting a live call.
    """
    mode = (os.environ.get("AMC_ZO_MODE") or "disabled").strip().lower()
    if mode != "live":
        return False
    return bool((os.environ.get("ZO_API_KEY") or "").strip())


def ask_zo(prompt: str, *, timeout_seconds: float = 30.0) -> dict:
    """Send a prompt to zo.computer's Mission Control ask endpoint.

    Raises ``ZoIntegrationError`` when the integration is not enabled/
    credentialed, when the request itself fails, or when zo.computer
    returns a non-2xx response. The bearer token is read from
    ``ZO_API_KEY`` immediately before the call and is never retained,
    logged, or included in any exception message.
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")

    mode = (os.environ.get("AMC_ZO_MODE") or "disabled").strip().lower()
    if mode != "live":
        raise ZoIntegrationError(
            "zo.computer integration is disabled (set AMC_ZO_MODE=live to enable)"
        )

    api_key = (os.environ.get("ZO_API_KEY") or "").strip()
    if not api_key:
        raise ZoIntegrationError("ZO_API_KEY is not configured")

    try:
        response = httpx.post(
            f"{ZO_API_BASE}/zo/ask",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"prompt": prompt},
            timeout=timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise ZoIntegrationError("zo.computer request failed") from exc

    if response.status_code >= 400:
        raise ZoIntegrationError(
            f"zo.computer returned HTTP {response.status_code}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise ZoIntegrationError("zo.computer returned a non-JSON response") from exc
