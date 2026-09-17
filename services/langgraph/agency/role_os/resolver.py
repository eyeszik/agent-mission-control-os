from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .registry import RoleOSRegistry, RuntimeRole


class RoleResolutionError(RuntimeError):
    pass


STOPWORDS = {
    "and", "of", "the", "for", "to", "a", "an", "in", "with", "role", "work",
    "manager", "director", "senior", "junior", "lead", "specialist", "associate",
}

ALIASES = {
    "copywriting": "copywriter",
    "copy": "copywriter",
    "branding": "brand",
    "engineering": "engineer",
    "development": "developer",
    "analytics": "analytics",
    "measurement": "measurement",
    "researching": "research",
    "designing": "design",
    "launch": "release",
    "publishing": "release",
    "publish": "release",
}

SENIORITY_PREFERENCE = {
    "IC": 6,
    "SENIOR_IC": 5,
    "MANAGEMENT": 4,
    "LEADERSHIP": 3,
    "EXECUTIVE": 2,
    "JUNIOR": 1,
}


@dataclass(frozen=True)
class RoleMatch:
    role_id: str
    title: str
    department: str
    family: str
    score: int
    coverage: float
    matched_tokens: tuple[str, ...]


def _tokens(values: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for value in values:
        slug = value.strip().lower().replace("&", " and ")
        for tok in re.findall(r"[a-z0-9]+", slug):
            if tok in STOPWORDS or len(tok) <= 1:
                continue
            out.add(ALIASES.get(tok, tok))
    return out


def _slug(value: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", value.lower()))


class RoleResolver:
    """Deterministic metadata resolver; it does not grant authority."""

    def __init__(self, registry: RoleOSRegistry):
        self.registry = registry

    def resolve(
        self,
        required_capabilities: list[str],
        *,
        department_hint: str | None = None,
        family_hint: str | None = None,
        limit: int = 5,
    ) -> list[RoleMatch]:
        if not required_capabilities:
            raise RoleResolutionError("required_capabilities must not be empty")
        query_tokens = _tokens(required_capabilities)
        if not query_tokens:
            raise RoleResolutionError("required_capabilities contain no resolvable tokens")

        query_slugs = {_slug(x) for x in required_capabilities}
        matches: list[RoleMatch] = []
        for role in self.registry.roles.values():
            role_tokens = set(role.capabilities)
            # Add exact canonical tokens that may have been normalized differently.
            role_tokens |= _tokens([role.title, role.skill_name, role.department, role.family])
            matched = query_tokens & role_tokens
            coverage = len(matched) / len(query_tokens)
            if not matched:
                continue

            score = len(matched) * 100
            if query_tokens.issubset(role_tokens):
                score += 250
            if role.skill_name in query_slugs:
                score += 1000
            if _slug(role.title) in query_slugs:
                score += 900
            if department_hint and role.department == department_hint:
                score += 180
            if family_hint and role.family == family_hint:
                score += 220
            score += SENIORITY_PREFERENCE.get(role.organizational_seniority, 0)

            matches.append(RoleMatch(
                role_id=role.role_id,
                title=role.title,
                department=role.department,
                family=role.family,
                score=score,
                coverage=round(coverage, 6),
                matched_tokens=tuple(sorted(matched)),
            ))

        matches.sort(key=lambda m: (-m.score, -m.coverage, m.role_id))
        if not matches:
            raise RoleResolutionError(f"no role matches capabilities: {required_capabilities}")
        return matches[: max(1, limit)]
