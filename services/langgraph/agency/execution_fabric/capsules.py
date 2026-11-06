"""Brand context capsules and taint-tracked data capsules.

A :class:`BrandContextCapsule` is the one hash-sealed set of brand facts every
brand-domain skill receives. Its hash is part of each request's input hash, so
a changed palette or name changes every dependent execution key (semantic
drift cannot silently reuse an old result).

A :class:`DataCapsule` wraps any text that crosses into a skill payload with
its provenance and the repository's own prompt-injection scan
(``compiled.role_sources.scan_for_injection``). Flagged content is quarantined:
the fabric refuses to dispatch rather than passing it on. Content is data,
never instructions, whatever it says.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.langgraph.agency.compiled.role_sources import scan_for_injection
from services.langgraph.agency.execution.canonical import canonical_hash

_HEX6 = re.compile(r"^#[0-9a-f]{6}$")
PALETTE_ROLES = ("primary", "secondary", "surface", "text")


class BrandContextCapsule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    brand_name: str = Field(min_length=1, max_length=120)
    palette: dict[str, str]
    heading_font: str = Field(default="Inter", min_length=1, max_length=80)
    body_font: str = Field(default="Inter", min_length=1, max_length=80)
    voice: tuple[str, ...] = ()
    locale: str = Field(default="en", pattern=r"^[a-z]{2}(-[A-Z]{2})?$")

    @field_validator("palette")
    @classmethod
    def _palette(cls, value: dict[str, str]) -> dict[str, str]:
        missing = [role for role in PALETTE_ROLES if role not in value]
        if missing:
            raise ValueError(f"palette lacks roles {missing}")
        normalized = {}
        for role, hex_value in sorted(value.items()):
            text = str(hex_value).strip().lower()
            if not _HEX6.match(text):
                raise ValueError(f"palette[{role}] must be a 6-digit hex colour")
            normalized[role] = text
        return normalized

    @field_validator("brand_name", "heading_font", "body_font")
    @classmethod
    def _plain(cls, value: str) -> str:
        if any(ch in value for ch in "<>\"'`{};\\"):
            raise ValueError("brand fields may not contain markup or code delimiters")
        return value.strip()

    @property
    def capsule_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


Trust = Literal["SERVER_INPUT", "UPSTREAM_ARTIFACT", "CLIENT_INPUT"]


class DataCapsule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_ref: str
    trust: Trust
    content_hash: str
    injection_flags: tuple[str, ...]

    @property
    def quarantined(self) -> bool:
        return bool(self.injection_flags)


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def capsule_for(source_ref: str, value: Any, trust: Trust) -> DataCapsule:
    flags = sorted({flag for text in _strings(value) for flag in scan_for_injection(text)})
    return DataCapsule(source_ref=source_ref, trust=trust, content_hash=canonical_hash(value), injection_flags=tuple(flags))


def quarantine_reasons(capsules: Iterable[DataCapsule]) -> tuple[str, ...]:
    return tuple(sorted(
        f"INJECTION_QUARANTINED:{c.source_ref}:{flag}" for c in capsules for flag in c.injection_flags
    ))


__all__ = ["BrandContextCapsule", "DataCapsule", "PALETTE_ROLES", "capsule_for", "quarantine_reasons"]
