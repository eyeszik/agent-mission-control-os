"""Publication provider contract and the fail-closed provider registry.

Provider contract: ``prepare → validate → preview → publish → verify`` plus
``update`` and ``remove``. Attempt states::

    SPEC → VALIDATED → AUTHORIZED → APPROVED → EXECUTING → READBACK
         → RECONCILED → VERIFIED

with BLOCKED / FAILED / UNCERTAIN as exits. UNCERTAIN means the provider call
may or may not have happened (timeout, dropped connection); it is resolved by
*reading back* with the same idempotency key, never by blindly retrying.

The only provider shipped is :class:`DryRunProvider`. ``AMC_PUBLICATION_MODE``
``live`` resolves to *no* provider unless one has been registered by reviewed
code, and production configuration already rejects ``live`` outright
(``app/config.py``). Nothing here can make an unavailable provider look active.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol

from .vocabulary import PUBLICATION_TRANSITIONS, ProviderMode, PublicationState, can_transition
from .workspace import canonical_json, sha256_bytes


class PublicationBlocked(RuntimeError):
    """The configured mode or provider cannot execute this publication."""


class ProviderUncertain(RuntimeError):
    """The provider call's outcome is unknown and must be read back."""


@dataclass(frozen=True)
class PublicationRequest:
    tenant_id: str
    project_id: str
    content_item_id: str
    version: int
    channel: str
    body: Mapping[str, Any]
    idempotency_key: str

    def request_hash(self) -> str:
        return sha256_bytes(canonical_json({
            "content_item_id": self.content_item_id,
            "version": self.version,
            "channel": self.channel,
            "body": dict(self.body),
        }))


@dataclass(frozen=True)
class ProviderResult:
    external_ref: str
    observed: Mapping[str, Any]


class PublicationProvider(Protocol):
    name: str
    mode: ProviderMode

    def prepare(self, request: PublicationRequest) -> dict[str, Any]: ...

    def validate(self, prepared: Mapping[str, Any]) -> list[str]: ...

    def preview(self, prepared: Mapping[str, Any]) -> dict[str, Any]: ...

    def publish(self, prepared: Mapping[str, Any], *, idempotency_key: str) -> ProviderResult: ...

    def verify(self, *, idempotency_key: str) -> Optional[ProviderResult]: ...

    def update(self, external_ref: str, prepared: Mapping[str, Any]) -> ProviderResult: ...

    def remove(self, external_ref: str) -> bool: ...


@dataclass
class DryRunProvider:
    """Exercises the full contract without leaving the process.

    It "publishes" into an in-memory ledger keyed by idempotency key, so a
    repeated publish is deduplicated exactly as a real idempotent provider
    must be, and ``verify`` reads back what was recorded.
    """

    name: str = "dry-run"
    mode: ProviderMode = ProviderMode.DRY_RUN
    max_body_chars: int = 20_000
    ledger: dict[str, ProviderResult] = field(default_factory=dict)

    def prepare(self, request: PublicationRequest) -> dict[str, Any]:
        return {
            "channel": request.channel,
            "content_item_id": request.content_item_id,
            "version": request.version,
            "body": dict(request.body),
            "request_hash": request.request_hash(),
        }

    def validate(self, prepared: Mapping[str, Any]) -> list[str]:
        problems = []
        if not prepared.get("channel"):
            problems.append("CHANNEL_REQUIRED")
        if len(canonical_json(prepared.get("body") or {})) > self.max_body_chars:
            problems.append("BODY_TOO_LARGE")
        return problems

    def preview(self, prepared: Mapping[str, Any]) -> dict[str, Any]:
        return {"channel": prepared["channel"], "mode": self.mode.value, "would_publish": dict(prepared["body"])}

    def publish(self, prepared: Mapping[str, Any], *, idempotency_key: str) -> ProviderResult:
        if idempotency_key in self.ledger:
            return self.ledger[idempotency_key]
        result = ProviderResult(
            external_ref=f"dryrun:{prepared['request_hash'][:24]}",
            observed={"channel": prepared["channel"], "request_hash": prepared["request_hash"]},
        )
        self.ledger[idempotency_key] = result
        return result

    def verify(self, *, idempotency_key: str) -> Optional[ProviderResult]:
        return self.ledger.get(idempotency_key)

    def update(self, external_ref: str, prepared: Mapping[str, Any]) -> ProviderResult:
        return ProviderResult(external_ref=external_ref, observed={"request_hash": prepared["request_hash"]})

    def remove(self, external_ref: str) -> bool:
        return any(result.external_ref == external_ref for result in self.ledger.values())


# Live providers must be installed by reviewed code. The registry ships empty.
_LIVE_PROVIDERS: dict[str, PublicationProvider] = {}
_DRY_RUN = DryRunProvider()


def publication_mode() -> ProviderMode:
    value = (os.environ.get("AMC_PUBLICATION_MODE") or "disabled").strip().lower()
    return {"disabled": ProviderMode.DISABLED, "dry_run": ProviderMode.DRY_RUN, "live": ProviderMode.LIVE}.get(
        value, ProviderMode.DISABLED
    )


def resolve_provider(channel: str) -> PublicationProvider:
    mode = publication_mode()
    if mode is ProviderMode.DISABLED:
        raise PublicationBlocked("publication_disabled")
    if mode is ProviderMode.DRY_RUN:
        return _DRY_RUN
    provider = _LIVE_PROVIDERS.get(channel)
    if provider is None or provider.mode is not ProviderMode.LIVE:
        raise PublicationBlocked(f"no reviewed live provider installed for channel {channel!r}")
    return provider


def provider_capabilities() -> dict[str, Any]:
    mode = publication_mode()
    return {
        "mode": mode.value,
        "dry_run_provider": _DRY_RUN.name,
        "live_channels": sorted(_LIVE_PROVIDERS),
        "live_available": mode is ProviderMode.LIVE and bool(_LIVE_PROVIDERS),
        "status": "DRY_RUN_ONLY" if not _LIVE_PROVIDERS else "EXTERNAL_ACTIVATION_REQUIRED",
    }


def next_state(current: PublicationState | str, target: PublicationState | str) -> PublicationState:
    current_state = PublicationState(current).value
    target_state = PublicationState(target).value
    if not can_transition(PUBLICATION_TRANSITIONS, current_state, target_state):
        raise ValueError(f"illegal publication transition {current_state} -> {target_state}")
    return PublicationState(target_state)
