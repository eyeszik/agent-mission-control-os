"""Model profiles for agency generation: selection, pinning and revocation checks.

A profile names the provider and model a run generates with, plus any fallback
routes someone explicitly allowed. Selection precedence is authorized run, then
project, then tenant, then the deployment default (``resolve_profile``). Only the
deployment default is configured today, from the environment; the run, project
and tenant levels are accepted by ``resolve_profile`` but no route writes them yet.

A run pins its profile in ``metadata.model_profile`` when it is created. Later
stages and resumes use the pin, never the current environment, so a config change
cannot switch a run's model halfway. Credentials are never pinned: each call looks
them up again and drops any route whose credential is gone or whose provider is in
``AMC_LLM_DISABLED_PROVIDERS``.

An explicit selection that is invalid (unknown provider, missing model) is a
``ProfileError``. Callers turn it into a clearly labelled degraded outcome, never a
silent switch to another provider. With no fallback configured there is none.

Pure module: no network, no persistence.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Literal, Mapping, Optional

from pydantic import Field, field_validator

from services.langgraph.agency.ace_controls import StrictModel

Provider = Literal["openai", "anthropic", "gemini", "ollama"]
PROVIDERS: tuple[str, ...] = ("openai", "anthropic", "gemini", "ollama")
PROFILE_SCHEMA = "amc.model-profile/v1"

# Checked in order. google-genai reads GOOGLE_API_KEY before GEMINI_API_KEY; so do we.
CREDENTIAL_ENV: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "ollama": (),  # local loopback only
}
MODEL_ENV: dict[str, str] = {
    "openai": "AMC_OPENAI_MODEL",
    "anthropic": "AMC_ANTHROPIC_MODEL",
    "gemini": "AMC_GEMINI_MODEL",
    "ollama": "AMC_OLLAMA_MODEL",
}
# The pre-existing OpenAI default, kept so existing deployments behave as before.
# No other provider gets a default model: it must be configured explicitly.
LEGACY_OPENAI_MODEL = "gpt-4o-mini"


class ProfileError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


class ModelRoute(StrictModel):
    provider: Provider
    # Provider model ids (e.g. "ft:..." or "name:tag") but nothing that can walk a URL path.
    model: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")

    @field_validator("model")
    @classmethod
    def _no_traversal(cls, value: str) -> str:
        if ".." in value or "//" in value:
            raise ValueError("model id must not contain '..' or '//'")
        return value


class ModelProfile(StrictModel):
    schema_version: Literal["amc.model-profile/v1"] = PROFILE_SCHEMA
    source: Literal["run", "project", "tenant", "deployment"]
    primary: ModelRoute
    # Explicitly allowed fallbacks, in order. Empty means no fallback.
    fallbacks: tuple[ModelRoute, ...] = ()

    @property
    def routes(self) -> tuple[ModelRoute, ...]:
        return (self.primary, *self.fallbacks)

    @property
    def profile_hash(self) -> str:
        body = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode()).hexdigest()


def _route(provider: str, env: Mapping[str, str]) -> ModelRoute:
    provider = provider.strip().lower()
    if provider not in PROVIDERS:
        raise ProfileError("INVALID_PROVIDER_SELECTION", f"unknown provider {provider!r}")
    model = (env.get(MODEL_ENV[provider]) or "").strip()
    if not model and provider == "openai":
        model = LEGACY_OPENAI_MODEL
    if not model:
        raise ProfileError("MODEL_NOT_CONFIGURED", f"{MODEL_ENV[provider]} is not set")
    try:
        return ModelRoute(provider=provider, model=model)
    except ValueError as exc:
        raise ProfileError("INVALID_MODEL_ID", f"{MODEL_ENV[provider]} is not a valid model id") from exc


def deployment_profile(env: Optional[Mapping[str, str]] = None) -> ModelProfile:
    """The deployment default from ``AMC_LLM_PROVIDER`` (default ``openai``) and
    ``AMC_LLM_FALLBACK_PROVIDERS`` (comma-separated, default none)."""
    env = os.environ if env is None else env
    primary = _route(env.get("AMC_LLM_PROVIDER") or "openai", env)
    fallbacks = []
    for name in (env.get("AMC_LLM_FALLBACK_PROVIDERS") or "").split(","):
        if name.strip():
            route = _route(name, env)
            if route != primary and route not in fallbacks:
                fallbacks.append(route)
    return ModelProfile(source="deployment", primary=primary, fallbacks=tuple(fallbacks))


def resolve_profile(*, deployment: ModelProfile, run: Optional[ModelProfile] = None,
                    project: Optional[ModelProfile] = None,
                    tenant: Optional[ModelProfile] = None) -> ModelProfile:
    """Authorized run, then project, then tenant, then deployment default."""
    for source, profile in (("run", run), ("project", project), ("tenant", tenant)):
        if profile is not None:
            return profile.model_copy(update={"source": source})
    return deployment


def pin_metadata(env: Optional[Mapping[str, str]] = None) -> dict:
    """The value a new run stores in ``metadata.model_profile``. An invalid
    deployment selection is pinned as its error so every stage reports it."""
    try:
        profile = deployment_profile(env)
    except ProfileError as exc:
        return {"schema_version": PROFILE_SCHEMA, "error": exc.code}
    return {**profile.model_dump(mode="json"), "profile_hash": profile.profile_hash}


def pinned_profile(metadata: Optional[Mapping]) -> Optional[ModelProfile]:
    """The profile a run pinned, or ``None`` for runs created before pinning.
    Raises ``ProfileError`` for a pinned error or a pin that no longer verifies."""
    pin = (metadata or {}).get("model_profile")
    if pin is None:
        return None
    if not isinstance(pin, Mapping):
        raise ProfileError("INVALID_PROFILE_PIN")
    if pin.get("error"):
        raise ProfileError(str(pin["error"]))
    body = {k: v for k, v in pin.items() if k != "profile_hash"}
    try:
        # Pins are stored as JSON; validate them as JSON (lists become tuples).
        profile = ModelProfile.model_validate_json(json.dumps(body))
    except ValueError as exc:
        raise ProfileError("INVALID_PROFILE_PIN") from exc
    if pin.get("profile_hash") != profile.profile_hash:
        raise ProfileError("PROFILE_PIN_MISMATCH")
    return profile


def credential(provider: str, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    env = os.environ if env is None else env
    for name in CREDENTIAL_ENV[provider]:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return None


def usable_routes(profile: ModelProfile, env: Optional[Mapping[str, str]] = None
                  ) -> tuple[tuple[ModelRoute, Optional[str]], ...]:
    """Routes that may be called right now, each with its credential. Checked at
    every call, so revoking a key or disabling a provider takes effect at once."""
    env = os.environ if env is None else env
    disabled = {p.strip().lower() for p in (env.get("AMC_LLM_DISABLED_PROVIDERS") or "").split(",") if p.strip()}
    usable = []
    for route in profile.routes:
        if route.provider in disabled:
            continue
        key = credential(route.provider, env)
        if CREDENTIAL_ENV[route.provider] and not key:
            continue
        usable.append((route, key))
    return tuple(usable)


__all__ = ["CREDENTIAL_ENV", "LEGACY_OPENAI_MODEL", "MODEL_ENV", "ModelProfile", "ModelRoute", "PROVIDERS",
           "ProfileError", "credential", "deployment_profile", "pin_metadata", "pinned_profile",
           "resolve_profile", "usable_routes"]
