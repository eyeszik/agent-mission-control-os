"""Command-line entry point into the agency kernel.

What this does and does not do is the whole point of the module. It **plans**
against the kernel: it resolves the artifacts a brief asks for to the roles N3
says may produce them, checks the evidence floor and consumed inputs those
contracts declare, and walks the N2 engagement matrix applying the real release
guards. It does not generate anything. No copy, no imagery, no assets -- a plan
is a statement about what the kernel would permit, not a claim that work
happened.

That distinction is why this reports blockers as its primary output. A run that
cannot reach `launched` because no human has approved it is the interesting
answer, not a failure of the tool, and the exit code says so: non-zero when the
requested phase is unreachable, so a script or CI job can act on it.

Everything it asserts comes from the kernel rather than from this file:

* ``resolve_artifact_type`` rejects a type the ontology does not define.
* ``ROLE_REGISTRY`` decides which role produces what, and what it consumes.
* ``assert_evidence_sufficient`` applies the role's own evidence floor.
* ``transition_failures`` applies the real lifecycle guards, with stable codes.

If the kernel changes, this changes with it; there is no second copy of the
rules here to drift.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from typing import Any, Iterable

from pydantic import BaseModel, Field, ValidationError

from services.langgraph.agency.kernel.lifecycle import (
    ENGAGEMENT_TRANSITIONS,
    TransitionContext,
    transition_failures,
    validate_matrices,
)
from services.langgraph.agency.kernel.models import EngagementStatus
from services.langgraph.agency.kernel.ontology import (
    ArtifactType,
    OntologyError,
    owning_department,
    resolve_artifact_type,
)
from services.langgraph.agency.kernel.registry import validate_merge_matrix
from services.langgraph.agency.kernel.roles import (
    ROLE_REGISTRY,
    RoleContract,
    validate_registry,
)

CLI_VERSION = "amc-agency-cli/v1"

# Phases that represent progress. The interrupt states (blocked, degraded,
# paused, review_required, failed, cancelled) are reachable from almost
# everywhere, so routing through them would produce a "path" that is really a
# description of how the engagement can go wrong.
PROGRESS_PHASES: tuple[EngagementStatus, ...] = (
    EngagementStatus.intake,
    EngagementStatus.discovery,
    EngagementStatus.research,
    EngagementStatus.strategy,
    EngagementStatus.brand,
    EngagementStatus.product,
    EngagementStatus.build,
    EngagementStatus.launch_ready,
    EngagementStatus.launched,
    EngagementStatus.growth,
    EngagementStatus.optimizing,
    EngagementStatus.complete,
)


class RunFacts(BaseModel):
    """What is known to be true about the run, fed to the lifecycle guards.

    Mirrors ``TransitionContext``. Anything absent is unproven, which is the
    fail-closed direction: an unstated approval is a missing approval.
    """

    generation_mode: str | None = None
    approval_exists: bool = False
    approval_resolved: bool = False
    approval_decision: str | None = None
    brand_safety_passed: bool | None = None
    spend_authorized: bool = False
    brand_safety_advisory: bool = False

    model_config = {"extra": "forbid"}

    def to_context(self, *, external_side_effect: bool) -> TransitionContext:
        return TransitionContext(
            generation_mode=self.generation_mode,
            approval_exists=self.approval_exists,
            approval_resolved=self.approval_resolved,
            approval_decision=self.approval_decision,
            brand_safety_passed=self.brand_safety_passed,
            external_side_effect=external_side_effect,
            spend_authorized=self.spend_authorized,
            brand_safety_advisory=self.brand_safety_advisory,
        )


class ProjectBrief(BaseModel):
    """The input document. Artifact names are validated against the ontology."""

    project_name: str = Field(min_length=1)
    target_artifacts: list[str] = Field(min_length=1)
    # Artifact types already in hand, so a consumed input is not reported as a
    # gap just because this brief does not also ask for it.
    available_inputs: list[str] = Field(default_factory=list)
    target_phase: str = EngagementStatus.launched.value
    evidence_count: int = Field(default=0, ge=0)
    facts: RunFacts = Field(default_factory=RunFacts)

    model_config = {"extra": "forbid"}


class BriefError(ValueError):
    """Raised when a brief cannot be interpreted against the kernel."""


def _resolve_types(values: Iterable[str], field: str) -> list[ArtifactType]:
    resolved: list[ArtifactType] = []
    for value in values:
        try:
            resolved.append(resolve_artifact_type(value))
        except OntologyError as exc:
            # OntologyError already enumerates the known types; don't repeat them.
            raise BriefError(f"{field}: {exc}") from exc
    return resolved


def producing_roles(artifact_type: ArtifactType) -> list[RoleContract]:
    return sorted(
        (contract for contract in ROLE_REGISTRY.values() if artifact_type in contract.produces),
        key=lambda contract: contract.role_id,
    )


def shortest_progress_path(
    start: EngagementStatus, target: EngagementStatus
) -> list[EngagementStatus] | None:
    """Fewest legal moves from ``start`` to ``target`` through progress phases."""
    if start == target:
        return [start]
    allowed = set(PROGRESS_PHASES) | {target}
    queue: deque[list[EngagementStatus]] = deque([[start]])
    seen = {start}
    while queue:
        path = queue.popleft()
        for nxt in sorted(ENGAGEMENT_TRANSITIONS[path[-1]], key=lambda item: item.value):
            if nxt not in allowed or nxt in seen:
                continue
            extended = path + [nxt]
            if nxt == target:
                return extended
            seen.add(nxt)
            queue.append(extended)
    return None


def build_plan(brief: ProjectBrief) -> dict[str, Any]:
    """Resolve a brief against the kernel. Never raises for a *blocked* plan."""
    targets = _resolve_types(brief.target_artifacts, "target_artifacts")
    available = _resolve_types(brief.available_inputs, "available_inputs")

    try:
        target_phase = EngagementStatus(brief.target_phase)
    except ValueError as exc:
        known = ", ".join(item.value for item in EngagementStatus)
        raise BriefError(f"target_phase: unknown engagement status '{brief.target_phase}'. Known: {known}") from exc

    satisfied = set(targets) | set(available)
    steps: list[dict[str, Any]] = []
    unproducible: list[str] = []
    external_side_effect = False

    for artifact_type in targets:
        roles = producing_roles(artifact_type)
        if not roles:
            unproducible.append(artifact_type.value)
            continue
        contract = roles[0]
        external_side_effect = external_side_effect or contract.external_side_effect
        missing = sorted(
            item.value for item in contract.consumes if item not in satisfied
        )
        steps.append(
            {
                "artifact_type": artifact_type.value,
                "department": owning_department(artifact_type).value,
                "role_id": contract.role_id,
                "min_evidence": contract.min_evidence,
                "evidence_satisfied": brief.evidence_count >= contract.min_evidence,
                "requires_human_approval": contract.requires_human_approval,
                "external_side_effect": contract.external_side_effect,
                "missing_inputs": missing,
            }
        )

    context = brief.facts.to_context(external_side_effect=external_side_effect)
    path = shortest_progress_path(EngagementStatus.intake, target_phase)

    transitions: list[dict[str, Any]] = []
    reached = EngagementStatus.intake
    blocked_at: dict[str, Any] | None = None

    if path is None:
        blocked_at = {
            "from": EngagementStatus.intake.value,
            "to": target_phase.value,
            "failures": [
                {
                    "code": "unreachable_phase",
                    "message": (
                        f"no path of progress phases leads from 'intake' to "
                        f"'{target_phase.value}'"
                    ),
                }
            ],
        }
    else:
        for current, nxt in zip(path, path[1:]):
            failures = transition_failures("engagement", current, nxt, context)
            entry = {
                "from": current.value,
                "to": nxt.value,
                "permitted": not failures,
                "failures": [
                    {"code": failure.code, "message": failure.message} for failure in failures
                ],
            }
            transitions.append(entry)
            if failures:
                blocked_at = entry
                break
            reached = nxt

    blocking_steps = [
        step for step in steps if step["missing_inputs"] or not step["evidence_satisfied"]
    ]

    return {
        "cli_version": CLI_VERSION,
        "project_name": brief.project_name,
        "target_phase": target_phase.value,
        "evidence_count": brief.evidence_count,
        "production_plan": steps,
        "unproducible_artifacts": unproducible,
        "lifecycle_path": [item.value for item in path] if path else [],
        "transitions": transitions,
        "reached_phase": reached.value,
        "blocked_at": blocked_at,
        "clear": blocked_at is None and not unproducible and not blocking_steps,
    }


def _render_plan(plan: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"Project        {plan['project_name']}")
    lines.append(f"Target phase   {plan['target_phase']}")
    lines.append("")

    lines.append("Production plan")
    if not plan["production_plan"]:
        lines.append("  (no producible artifacts requested)")
    for step in plan["production_plan"]:
        flags = []
        if step["requires_human_approval"]:
            flags.append("human-approval")
        if step["external_side_effect"]:
            flags.append("external-side-effect")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        lines.append(
            f"  {step['artifact_type']:<24} {step['role_id']:<22} "
            f"({step['department']}){suffix}"
        )
        if not step["evidence_satisfied"]:
            lines.append(
                f"      needs >= {step['min_evidence']} evidence item(s); brief declares "
                f"{plan.get('evidence_count', 0)}"
            )
        for missing in step["missing_inputs"]:
            lines.append(f"      missing input: {missing}")

    for artifact_type in plan["unproducible_artifacts"]:
        lines.append(f"  {artifact_type}: no role in the registry produces this type")

    lines.append("")
    lines.append("Lifecycle")
    for entry in plan["transitions"]:
        mark = "ok  " if entry["permitted"] else "BLOCK"
        lines.append(f"  {mark} {entry['from']} -> {entry['to']}")
        for failure in entry["failures"]:
            lines.append(f"        {failure['code']}: {failure['message']}")

    lines.append("")
    if plan["clear"]:
        lines.append(f"Reached {plan['reached_phase']}; no blockers. Nothing has been generated.")
    else:
        lines.append(f"Stopped at {plan['reached_phase']}. Blockers above must clear first.")
    return "\n".join(lines)


def _load_brief(path: str) -> ProjectBrief:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise BriefError(f"brief not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BriefError(f"brief is not valid JSON: {exc}") from exc

    try:
        return ProjectBrief.model_validate(payload)
    except ValidationError as exc:
        raise BriefError(f"brief does not match the expected shape:\n{exc}") from exc


def _cmd_plan(args: argparse.Namespace) -> int:
    plan = build_plan(_load_brief(args.input))
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(_render_plan(plan))
    return 0 if plan["clear"] else 1


def _cmd_roles(args: argparse.Namespace) -> int:
    contracts = sorted(ROLE_REGISTRY.values(), key=lambda item: (item.department.value, item.role_id))
    if args.department:
        contracts = [item for item in contracts if item.department.value == args.department]
        if not contracts:
            print(f"no roles in department '{args.department}'", file=sys.stderr)
            return 1
    for contract in contracts:
        print(f"{contract.role_id}  ({contract.department.value})")
        print(f"  mandate    {contract.mandate}")
        print(f"  produces   {', '.join(sorted(item.value for item in contract.produces))}")
        if contract.consumes:
            print(f"  consumes   {', '.join(sorted(item.value for item in contract.consumes))}")
        print(
            f"  gates      min_evidence={contract.min_evidence} "
            f"human_approval={contract.requires_human_approval} "
            f"external_side_effect={contract.external_side_effect}"
        )
    return 0


def _cmd_validate(_args: argparse.Namespace) -> int:
    problems = validate_matrices() + validate_registry() + validate_merge_matrix()
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"kernel validation: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print("kernel validation: N1 ontology, N2 lifecycle, N3 roles, and N4 merge matrix agree")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agency",
        description=(
            "Plan work against the agency kernel. Plans only -- this generates no assets."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Resolve a project brief against the kernel.")
    plan.add_argument("-i", "--input", required=True, help="Path to a project brief JSON file.")
    plan.add_argument("--json", action="store_true", help="Emit the plan as JSON.")
    plan.set_defaults(handler=_cmd_plan)

    roles = sub.add_parser("roles", help="List N3 role contracts.")
    roles.add_argument("-d", "--department", help="Filter to one department.")
    roles.set_defaults(handler=_cmd_roles)

    validate = sub.add_parser("validate", help="Run the kernel's structural self-checks.")
    validate.set_defaults(handler=_cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except BriefError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
