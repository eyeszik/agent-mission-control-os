"""Bind a request to exactly one accessible Project OS project, or say why not.

Hard filters run before any matching:

1. tenant scope: only the principal's tenant is ever loaded;
2. access: ``Principal.can_access_project`` (server-derived, never client input);
3. lifecycle: an ARCHIVED project cannot receive new work.

Projects removed by a filter are counted, never named, so a receipt cannot
reveal that another project exists. Ranking is a lexicographic tier, not a
score: an explicit project id beats a name/slug/brand match, which beats the
project of the active conversation. Ties, or a named project that differs from
the active one, are AMBIGUOUS and pause the mission for one question. Projects
are never merged.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from services.langgraph.agency.project_os.models import ProjectWorkspaceV2
from services.langgraph.security.auth import Principal

from .contracts import CompiledIntent, ProjectCandidate, ProjectResolutionReceipt

SCAN_LIMIT = 200
TIER_EXPLICIT_ID = 0
TIER_NAME_MATCH = 1
TIER_ACTIVE_CONTEXT = 2

ProjectLister = Callable[[str], Iterable[ProjectWorkspaceV2]]


def _default_lister(tenant_id: str) -> list[ProjectWorkspaceV2]:
    from services.langgraph.persistence.projects import list_project_workspaces

    return list_project_workspaces(tenant_id, limit=SCAN_LIMIT)


def _phrase(text: str, phrase: Optional[str]) -> bool:
    if not phrase or len(phrase.strip()) < 3:
        return False
    words = [re.escape(w) for w in re.split(r"[\s\-_]+", phrase.strip()) if w]
    return bool(re.search(r"(?<![\w-])" + r"[\s\-_]+".join(words) + r"(?![\w-])", text, re.I))


def resolve_project(
    principal: Principal,
    intent: CompiledIntent,
    *,
    active_project_id: Optional[str] = None,
    now: Optional[datetime] = None,
    lister: ProjectLister = _default_lister,
) -> ProjectResolutionReceipt:
    moment = (now or datetime.now(timezone.utc)).isoformat()
    loaded = [p for p in lister(principal.tenant_id) if p.tenant_id == principal.tenant_id]
    accessible = [p for p in loaded if principal.can_access_project(p.project_id)]
    open_projects = [p for p in accessible if p.lifecycle_state.value != "ARCHIVED"]
    hard_filtered = {
        "inaccessible": len(loaded) - len(accessible),
        "archived": len(accessible) - len(open_projects),
        "scanned": len(loaded),
        "scan_limit": SCAN_LIMIT,
    }
    by_id = {p.project_id: p for p in open_projects}
    reasons: list[str] = []
    found: dict[str, tuple[int, list[str]]] = {}

    def add(project: ProjectWorkspaceV2, tier: int, basis: str) -> None:
        best, bases = found.get(project.project_id, (tier, []))
        found[project.project_id] = (min(best, tier), bases + [basis])

    for pid in intent.explicit_project_ids:
        if pid in by_id:
            add(by_id[pid], TIER_EXPLICIT_ID, "EXPLICIT_ID")
        else:
            # Same reason whether the id is unknown, in another tenant, forbidden
            # or archived: the receipt must not confirm that it exists.
            reasons.append("EXPLICIT_PROJECT_NOT_AVAILABLE")

    text = intent.raw_request
    for project in open_projects:
        if _phrase(text, project.display_name):
            add(project, TIER_NAME_MATCH, "NAME_MATCH")
        if _phrase(text, project.slug):
            add(project, TIER_NAME_MATCH, "SLUG_MATCH")
        if _phrase(text, project.brand_name):
            add(project, TIER_NAME_MATCH, "BRAND_MATCH")
    if active_project_id is not None and active_project_id in by_id:
        add(by_id[active_project_id], TIER_ACTIVE_CONTEXT, "ACTIVE_CONTEXT")
    elif active_project_id is not None:
        reasons.append("ACTIVE_PROJECT_NOT_AVAILABLE")

    candidates = tuple(sorted(
        (ProjectCandidate(project_id=pid, display_name=by_id[pid].display_name, basis=tuple(sorted(set(bases))), rank=tier)
         for pid, (tier, bases) in found.items()),
        key=lambda c: (c.rank, c.project_id),
    ))

    def receipt(status: str, project_id: Optional[str], confirm: bool) -> ProjectResolutionReceipt:
        return ProjectResolutionReceipt(status=status, project_id=project_id, candidates=candidates, hard_filtered=hard_filtered,
                                        reasons=tuple(reasons), needs_confirmation=confirm, tenant_id=principal.tenant_id,
                                        resolved_at=moment)

    if "EXPLICIT_PROJECT_NOT_AVAILABLE" in reasons and not any(c.rank == TIER_EXPLICIT_ID for c in candidates):
        return receipt("DENIED", None, True)
    if not candidates:
        reasons.append("NO_ACCESSIBLE_PROJECT_MATCHED")
        return receipt("UNRESOLVED", None, True)
    best = candidates[0].rank
    top = [c for c in candidates if c.rank == best]
    if len(top) > 1:
        reasons.append(f"TIED_AT_TIER_{best}")
        return receipt("AMBIGUOUS", None, True)
    chosen = top[0]
    active = next((c for c in candidates if "ACTIVE_CONTEXT" in c.basis), None)
    if best == TIER_NAME_MATCH and active is not None and active.project_id != chosen.project_id:
        reasons.append("NAMED_PROJECT_DIFFERS_FROM_ACTIVE_PROJECT")
        return receipt("AMBIGUOUS", None, True)
    reasons.append(f"BOUND_BY_{chosen.basis[0]}")
    return receipt("BOUND", chosen.project_id, False)


__all__ = ["SCAN_LIMIT", "resolve_project"]
