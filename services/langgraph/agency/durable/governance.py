"""G0-G4 governance vocabulary, mapped to the code that enforces each level.

    G0 read, inspect, analyze, simulate
    G1 local workspace write, test, render
    G2 internal project artifact persistence
    G3 externally visible or user-impacting action
    G4 financial, legal, destructive, privileged or irreversible action

The matrix is not the enforcement. Every row names the symbol that enforces
it, and ``resolve_enforcers`` imports each one so a renamed or deleted
enforcer fails a test instead of leaving a stale claim. ``decide`` is the
single answer for this slice: G3 and G4 are never allowed here, because no
reviewed live adapter exists (publication registry ships empty, paid media is
planning-only). An approval does not change that; it only allows G2 release.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional

GOVERNANCE_VERSION = "amc-governance/v1"


class Level(str, Enum):
    G0 = "G0"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"


ACTION_LEVELS: dict[str, Level] = {
    "read": Level.G0, "inspect": Level.G0, "plan": Level.G0, "simulate": Level.G0,
    "render.local": Level.G1, "test": Level.G1, "workspace.write": Level.G1,
    "artifact.persist": Level.G2, "approval.request": Level.G2, "release.internal": Level.G2,
    "publish": Level.G3, "send": Level.G3, "deploy": Level.G3, "notify.external": Level.G3,
    "spend": Level.G4, "purchase": Level.G4, "delete.production": Level.G4, "credential.change": Level.G4,
    "legal.commit": Level.G4,
}

MATRIX: tuple[dict, ...] = (
    {"level": "G0", "scope": "read, inspect, analyze, simulate", "requires": ["authenticated principal"],
     "enforced_by": ["services.langgraph.security.auth:Principal",
                     "services.langgraph.agency.intake.release:artifact_release_verdict"],
     "note": "SIMULATION output is refused by the release verdict (SIMULATION_NOT_RELEASABLE)."},
    {"level": "G1", "scope": "local workspace write, test, render", "requires": ["project access", "local capability probe"],
     "enforced_by": ["services.langgraph.agency.visual.capabilities:probe_all",
                     "services.langgraph.agency.visual.router:route",
                     "services.langgraph.agency.visual.renderers:render_blender"],
     "note": "Renders run in a network-isolated namespace when unshare is available; no hosted generation API."},
    {"level": "G2", "scope": "internal project artifact persistence", "requires": ["tenant + project authorization",
                                                                                  "compare-and-set version"],
     "enforced_by": ["services.langgraph.persistence.projects:create_project_artifact",
                     "services.langgraph.persistence.projects:revise_project_artifact",
                     "services.langgraph.persistence.durable_runs:transition"],
     "note": "Release of a G2 artifact additionally needs a current, separately-decided approval bound to its hash."},
    {"level": "G3", "scope": "externally visible or user-impacting", "requires": ["reviewed live adapter", "human approval"],
     "enforced_by": ["services.langgraph.integrations.publication:prepare_publication"],
     "note": "Blocked: no live publication adapter is installed; AMC_PUBLICATION_MODE beyond dry_run fails readiness."},
    {"level": "G4", "scope": "financial, legal, destructive, privileged, irreversible",
     "requires": ["reviewed live adapter", "explicit spend/legal authorization"],
     "enforced_by": ["services.langgraph.integrations.paid_media:spend_execution_available"],
     "note": "Blocked: spend_execution_available() is constantly False."},
)


@dataclass(frozen=True)
class Decision:
    action: str
    level: Level
    allowed: bool
    reasons: tuple[str, ...]
    dispatched: bool = False  # this module never performs the action


def level_of(action: str) -> Level:
    # Unknown actions are treated as the most consequential class, not the least.
    return ACTION_LEVELS.get(action, Level.G4)


def decide(action: str, *, authenticated: bool, project_access: bool, simulation: bool = False,
           approval_current: Optional[bool] = None) -> Decision:
    level = level_of(action)
    reasons: list[str] = []
    if not authenticated:
        reasons.append("UNAUTHENTICATED")
    if level is not Level.G0 and not project_access:
        reasons.append("NO_PROJECT_ACCESS")
    if level is not Level.G0 and simulation and action != "render.local":
        reasons.append("SIMULATION_HAS_NO_EFFECTS")
    if action == "release.internal" and approval_current is not True:
        reasons.append("APPROVAL_NOT_CURRENT")
    if level is Level.G3:
        reasons.append("G3_NO_REVIEWED_LIVE_ADAPTER")
    if level is Level.G4:
        reasons.append("G4_NO_REVIEWED_LIVE_ADAPTER" if action in ACTION_LEVELS else "UNKNOWN_ACTION_TREATED_AS_G4")
    return Decision(action=action, level=level, allowed=not reasons, reasons=tuple(reasons))


def resolve_enforcers() -> dict[str, bool]:
    """Import every named enforcer. A missing one maps to False rather than being assumed present."""
    out: dict[str, bool] = {}
    for row in MATRIX:
        for ref in row["enforced_by"]:
            module, _, attr = ref.partition(":")
            try:
                out[ref] = hasattr(importlib.import_module(module), attr)
            except ImportError:
                out[ref] = False
    return out


def as_document() -> dict:
    return {"schema_version": GOVERNANCE_VERSION, "levels": list(MATRIX),
            "action_levels": {k: v.value for k, v in sorted(ACTION_LEVELS.items())},
            "unknown_action_level": "G4",
            "production_external_effects": "BLOCKED: no reviewed live adapter; approval alone never unlocks G3/G4"}


__all__ = ["ACTION_LEVELS", "Decision", "GOVERNANCE_VERSION", "Level", "MATRIX", "as_document", "decide", "level_of",
           "resolve_enforcers"]
