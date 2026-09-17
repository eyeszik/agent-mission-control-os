"""Skill runtime — the dispatch layer between a role and an external tool.

N3 (``agency/kernel/roles.py``) says which artifact types a role may produce
and which capabilities it holds. It says nothing about *invoking a tool*:
until this module, a role's ``capabilities`` field was declarative only —
nothing checked it before letting code call an integration like
``services.langgraph.integrations.zo.ask_zo``. Any node could import and call
it directly, so the capability declaration was decorative.

This module makes that check real. A skill is registered once with the
capability it requires; ``dispatch_skill`` refuses to invoke it unless the
calling role's contract holds that capability, and raises rather than
executing when it doesn't — the same fail-closed posture as
``assert_role_may_produce``.

Two distinct failure tiers, matching the rest of this codebase's convention
(compare ``roles.py`` vs. ``graph/agency/llm.py``):

* **Authorization failures** (unknown role, unknown skill, role lacks the
  required capability) are programming/configuration errors. They raise
  ``RoleContractError`` or ``SkillDispatchError`` rather than returning a
  value a caller could forget to check.
* **Execution failures** (the handler raised once dispatch was authorized)
  are runtime conditions a caller must be able to handle without a pipeline
  node crashing. They come back as a ``SkillOutcome`` with
  ``status="FAILED"``, mirroring how ``generate_structured`` returns a
  degraded ``GenerationOutcome`` instead of propagating a provider error.

Scope boundary: dispatch authorization is capability-gated only. It does not
evaluate ``min_evidence``, ``requires_human_approval``, or
``external_side_effect`` -- those govern *artifact production and release*
(N2/N3 guards) and apply once, at the point a role's output is persisted or
released, not at every tool call a role makes while producing it. A skill
whose handler itself has an external side effect (spend, publication) still
needs that release-time gate; this module does not substitute for one, and
today's only registered skill (``zo_ask``) is a read-only query with none.

Registering a skill also does not expose it over HTTP. Dispatch is a
Python-level primitive for graph nodes to call directly; whether a given
skill should ever be reachable from an API route is a separate decision this
module deliberately leaves open.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from services.langgraph.agency.kernel.ontology import Capability
from services.langgraph.agency.kernel.roles import RoleContractError, get_role
from services.langgraph.integrations.zo import ask_zo, zo_available

logger = logging.getLogger(__name__)

SKILL_RUNTIME_VERSION = "amc-agency-skills/v1"


class SkillDispatchError(RuntimeError):
    """Raised when a skill cannot be dispatched: unknown skill, or the
    invoking role's contract does not hold the skill's required capability.

    This is distinct from ``RoleContractError`` (raised by ``get_role`` for an
    unknown role_id) rather than a subclass of it, because the two modules
    own different vocabularies. A caller that wants to catch every dispatch-
    time authorization failure in one place should catch both:
    ``except (RoleContractError, SkillDispatchError):``.
    """


@dataclass(frozen=True)
class Skill:
    """One invocable capability, bound to the N3 capability that gates it."""

    skill_id: str
    capability: Capability
    description: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    # Optional cheap check for whether the backing integration is currently
    # reachable (credentialed + enabled) -- distinct from whether the skill is
    # *registered*. None means "no such check is meaningful for this skill."
    availability_check: Callable[[], bool] | None = None


@dataclass(frozen=True)
class SkillOutcome:
    """The result of one dispatched skill invocation.

    ``result`` and ``error_message`` are deliberately excluded from
    ``provenance()``, the same way ``GenerationOutcome.provenance()`` excludes
    ``data`` -- the audit trail records that a call happened and how it
    resolved, not the (potentially large, potentially sensitive) payload
    itself.
    """

    skill_id: str
    role_id: str
    capability: str
    status: str  # "SUCCESS" | "FAILED"
    result: dict[str, Any] | None
    error_class: str | None
    error_message: str | None
    started_at: str
    completed_at: str

    @property
    def succeeded(self) -> bool:
        return self.status == "SUCCESS"

    def provenance(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "role_id": self.role_id,
            "capability": self.capability,
            "status": self.status,
            "error_class": self.error_class,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ask_zo_handler(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("payload['prompt'] must be a non-empty string")
    kwargs: dict[str, Any] = {}
    if "timeout_seconds" in payload:
        kwargs["timeout_seconds"] = payload["timeout_seconds"]
    return ask_zo(prompt, **kwargs)


SKILL_REGISTRY: dict[str, Skill] = {
    skill.skill_id: skill
    for skill in (
        Skill(
            skill_id="zo_ask",
            # zo.computer's ask endpoint answers an open question against
            # external/current information. Of N3's existing capabilities,
            # research_synthesis (held by market_researcher) is the closest
            # fit. This is a judgment call about the mapping, not a fact
            # asserted about zo.computer's API -- revisit if a more specific
            # capability turns out to be warranted.
            capability=Capability.research_synthesis,
            description="Ask zo.computer's Mission Control endpoint a question.",
            handler=_ask_zo_handler,
            availability_check=zo_available,
        ),
    )
}


def get_skill(skill_id: str) -> Skill:
    try:
        return SKILL_REGISTRY[skill_id]
    except KeyError as exc:
        raise SkillDispatchError(
            f"Unknown skill '{skill_id}'. Known skills: " + ", ".join(sorted(SKILL_REGISTRY))
        ) from exc


def dispatch_skill(role_id: str, skill_id: str, payload: dict[str, Any] | None = None) -> SkillOutcome:
    """Invoke ``skill_id`` on behalf of ``role_id``.

    Raises ``RoleContractError`` for an unknown role and ``SkillDispatchError``
    for an unknown skill or a role that lacks the skill's required capability
    -- both before the handler ever runs. Once authorized, the handler's own
    failure is captured and returned as a ``SkillOutcome`` rather than raised,
    so one failed tool call cannot crash the calling pipeline node.
    """
    contract = get_role(role_id)  # raises RoleContractError on unknown role
    skill = get_skill(skill_id)  # raises SkillDispatchError on unknown skill

    if skill.capability not in contract.capabilities:
        raise SkillDispatchError(
            f"Role '{role_id}' may not invoke skill '{skill_id}'; it requires capability "
            f"'{skill.capability.value}', which role '{role_id}' does not hold. "
            f"Declared capabilities: {', '.join(sorted(item.value for item in contract.capabilities))}"
        )

    started_at = _now()
    try:
        result = skill.handler(dict(payload or {}))
    except Exception as exc:  # the handler's failure is data, not a crash
        logger.warning(
            "skill_dispatch_failed",
            extra={"skill_id": skill_id, "role_id": role_id, "error_class": type(exc).__name__},
        )
        return SkillOutcome(
            skill_id=skill_id,
            role_id=role_id,
            capability=skill.capability.value,
            status="FAILED",
            result=None,
            error_class=type(exc).__name__,
            error_message=str(exc),
            started_at=started_at,
            completed_at=_now(),
        )

    return SkillOutcome(
        skill_id=skill_id,
        role_id=role_id,
        capability=skill.capability.value,
        status="SUCCESS",
        result=result,
        error_class=None,
        error_message=None,
        started_at=started_at,
        completed_at=_now(),
    )


def skill_registry_snapshot() -> dict[str, Any]:
    """Introspection surface, parallel to ``role_snapshot``/``ontology_snapshot``."""
    return {
        "skill_runtime_version": SKILL_RUNTIME_VERSION,
        "skills": [
            {
                "skill_id": skill.skill_id,
                "capability": skill.capability.value,
                "description": skill.description,
                "available": skill.availability_check() if skill.availability_check else None,
            }
            for skill in sorted(SKILL_REGISTRY.values(), key=lambda item: item.skill_id)
        ],
    }
