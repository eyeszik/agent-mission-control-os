"""Evaluator and localized repair loop.

The evaluator exposes scores, failed requirements, repair targets, and
unresolved limitations. It never exposes hidden chain-of-thought; reasoning is
represented as explicit validation results. Repair is local (it touches only the
failed dimension) and bounded to at most three automatic cycles.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .camera import scene_path_conflicts, validate_camera
from .continuity import handshake_gaps, propagate
from .schemas import CameraState, ShotIR

MAX_REPAIR_CYCLES = 3


class Dimension(str, Enum):
    identity = "identity"
    camera = "camera"
    performance = "performance"
    physics = "physics"
    continuity = "continuity"
    prompt_clarity = "prompt_clarity"


class Finding(BaseModel):
    dimension: Dimension
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    detail: str = ""
    repair_target: str | None = None

    model_config = {"extra": "forbid"}


class EvaluationResult(BaseModel):
    shot_id: str
    findings: list[Finding] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @property
    def passed(self) -> bool:
        return all(f.passed for f in self.findings)

    @property
    def scores(self) -> dict[str, float]:
        return {f.dimension.value: f.score for f in self.findings}

    def repair_targets(self) -> list[Dimension]:
        return [f.dimension for f in self.findings if not f.passed and f.repair_target]


def evaluate_shot(shot: ShotIR, previous: ShotIR | None = None) -> EvaluationResult:
    findings: list[Finding] = []

    # identity
    has_identity = bool(
        (isinstance(shot.character_state, dict) and (shot.character_state.get("subject") or shot.character_state.get("present")))
        or shot.identity_refs
    )
    findings.append(
        Finding(
            dimension=Dimension.identity,
            score=1.0 if has_identity else 0.4,
            passed=has_identity,
            detail="identity present" if has_identity else "no subject/identity reference",
            repair_target=None if has_identity else "strengthen_identity_lock",
        )
    )

    # camera
    camera_problems = validate_camera(shot) + scene_path_conflicts(shot)
    findings.append(
        Finding(
            dimension=Dimension.camera,
            score=1.0 if not camera_problems else 0.3,
            passed=not camera_problems,
            detail="; ".join(camera_problems) or "camera valid",
            repair_target=None if not camera_problems else "simplify_camera_path",
        )
    )

    # performance (only graded when a shot carries a speaking/acting beat)
    if shot.dialogue or shot.performance.objective or shot.performance.beat_sequence:
        visible = bool(shot.performance.visible_fields() or shot.performance.beat_sequence)
        findings.append(
            Finding(
                dimension=Dimension.performance,
                score=1.0 if visible else 0.5,
                passed=visible,
                detail="observable performance" if visible else "abstract emotion without observable behaviour",
                repair_target=None if visible else "observable_behaviour",
            )
        )

    # physics
    if shot.physics:
        ok = all(event.trigger and event.primary_consequence for event in shot.physics)
        findings.append(
            Finding(
                dimension=Dimension.physics,
                score=1.0 if ok else 0.5,
                passed=ok,
                detail="causal physics" if ok else "physics missing trigger or consequence",
                repair_target=None if ok else "clarify_physics",
            )
        )

    # continuity
    if previous is not None:
        gaps = handshake_gaps(previous, shot)
        findings.append(
            Finding(
                dimension=Dimension.continuity,
                score=1.0 if not gaps else 0.4,
                passed=not gaps,
                detail="; ".join(gaps) or "continuity intact",
                repair_target=None if not gaps else "inherit_previous_state",
            )
        )

    return EvaluationResult(shot_id=shot.id, findings=findings)


def repair_shot(shot: ShotIR, previous: ShotIR | None = None) -> tuple[ShotIR, list[str]]:
    """Apply up to :data:`MAX_REPAIR_CYCLES` local repairs. Returns the repaired
    shot and the log of applied repairs. Only failed dimensions are touched."""

    log: list[str] = []
    current = shot
    for _ in range(MAX_REPAIR_CYCLES):
        result = evaluate_shot(current, previous)
        if result.passed:
            break
        changed = False
        for finding in result.findings:
            if finding.passed or not finding.repair_target:
                continue
            repaired = _apply_repair(current, previous, finding.repair_target)
            if repaired is not None and repaired is not current:
                current = repaired
                log.append(f"{current.id}:{finding.dimension.value}:{finding.repair_target}")
                changed = True
        if not changed:
            break
    return current, log


def _apply_repair(shot: ShotIR, previous: ShotIR | None, target: str) -> ShotIR | None:
    if target == "strengthen_identity_lock":
        refs = shot.identity_refs or [f"identity:{shot.id}"]
        return shot.model_copy(update={"identity_refs": refs})
    if target == "simplify_camera_path":
        # Collapse an underspecified move to a valid static camera.
        return shot.model_copy(update={"camera": CameraState()})
    if target == "observable_behaviour":
        perf = shot.performance
        if not perf.beat_sequence:
            perf = perf.model_copy(
                update={"beat_sequence": ["notice", "process", "decide", "act", "react"]}
            )
        return shot.model_copy(update={"performance": perf})
    if target == "clarify_physics":
        fixed = [
            event.model_copy(update={"settle": event.settle or "motion settles"})
            for event in shot.physics
        ]
        return shot.model_copy(update={"physics": fixed})
    if target == "inherit_previous_state" and previous is not None:
        return propagate(previous, shot)
    return None
