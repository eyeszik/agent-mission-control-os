"""End-to-end cinematic pipeline.

USER INPUT -> ROUTER -> CINEMATIC CAPABILITY -> PROJECT/SHOT IR ->
PRODUCTION REASONING -> TARGET COMPILER -> MODEL ADAPTER -> EVALUATOR ->
LOCAL REPAIR -> PROMPT COMPRESSION -> FINAL OUTPUT.

Non-generative requests (capability/audit/system-design/workflow) return a
capability manifest and never invent a scene. The pipeline terminates at
validated prompts; it performs no external creative side effect.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from . import GENERATION_FIREWALL
from .adapters import PORTABLE_PROFILE, adapt
from .compilers import compile_i2v, compile_t2i, compile_t2v
from .continuity import build_packets, propagate
from .evaluation import EvaluationResult, evaluate_shot, repair_shot
from .router import RouteDecision, capability_manifest, classify_mode, route_request
from .schemas import (
    Beat,
    CinematicRequest,
    CompiledPrompt,
    Fact,
    FactStatus,
    InputForm,
    InputMode,
    NON_GENERATIVE_MODES,
    ProjectIR,
    PromptTarget,
    Scene,
    ShotIR,
    SourceAuthority,
    Story,
    StoryboardPanel,
)
from .storyboard import panels_to_shots, script_to_storyboard
from .story import scene_to_shots

_VERBS = (
    "waits", "wait", "walks", "walk", "runs", "run", "stands", "stand", "sits",
    "sit", "looks", "look", "turns", "turn", "opens", "open", "holds", "hold",
    "enters", "enter", "drives", "drive", "reaches", "reach", "watches", "watch",
    "speaks", "speak", "moves", "move", "steps", "step", "arrives", "arrive",
)
_SETTING_RE = re.compile(r"\b(?:in|at|on|inside|outside|near|under|through)\s+(.+)$", re.I)


class PipelineResult(BaseModel):
    matched: bool
    route: RouteDecision
    mode: InputMode | None = None
    target: PromptTarget | None = None
    generative: bool = False
    project: ProjectIR | None = None
    prompts: list[CompiledPrompt] = Field(default_factory=list)
    storyboard: list[StoryboardPanel] = Field(default_factory=list)
    evaluations: list[EvaluationResult] = Field(default_factory=list)
    repair_log: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    capability: dict | None = None
    generation_firewall: str = GENERATION_FIREWALL
    notes: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


def run_pipeline(request: CinematicRequest) -> PipelineResult:
    # ``route_request`` is the *discovery* gate an external router uses to decide
    # whether to hand a request here. ``run_pipeline`` is called once that
    # decision is made, so it processes rather than re-gating; the route decision
    # is retained for transparency.
    route = route_request(request.text)
    mode = request.mode or classify_mode(request.text)

    # Non-generative modes: describe the system, never invent a scene.
    if mode in NON_GENERATIVE_MODES:
        return PipelineResult(
            matched=True,
            route=route,
            mode=mode,
            generative=False,
            capability=capability_manifest(),
            notes=["non-generative request: returned capability manifest, no scene generated"],
        )

    project, unresolved = _normalise_project(request)
    shots = _propagate_all(project.shots)
    project = project.model_copy(update={"shots": shots, "packets": build_packets(project)})

    target = _resolve_target(request, mode)

    storyboard: list[StoryboardPanel] = []
    if mode is InputMode.storyboard or target is PromptTarget.storyboard:
        storyboard = script_to_storyboard(project.story) if project.story.scenes else [
            _panel_from_shot(shot, i + 1) for i, shot in enumerate(shots)
        ]

    prompts: list[CompiledPrompt] = []
    evaluations: list[EvaluationResult] = []
    repair_log: list[str] = []
    repaired_shots: list[ShotIR] = []

    for index, shot in enumerate(shots):
        previous = repaired_shots[index - 1] if index > 0 else None
        fixed, log = repair_shot(shot, previous)
        repair_log.extend(log)
        repaired_shots.append(fixed)
        evaluations.append(evaluate_shot(fixed, previous))
        if mode is InputMode.storyboard and target is PromptTarget.storyboard:
            continue  # board only; no video prompt requested
        prompt = _compile_for_target(fixed, target, request)
        prompts.append(adapt(prompt, request.model_profile or PORTABLE_PROFILE))

    project = project.model_copy(update={"shots": repaired_shots})

    return PipelineResult(
        matched=True,
        route=route,
        mode=mode,
        target=target,
        generative=True,
        project=project,
        prompts=prompts,
        storyboard=storyboard,
        evaluations=evaluations,
        repair_log=repair_log,
        unresolved=unresolved,
    )


# --------------------------------------------------------------------------- #
# Intake / normalisation
# --------------------------------------------------------------------------- #
def _normalise_project(request: CinematicRequest) -> tuple[ProjectIR, list[str]]:
    if request.project is not None:
        project = request.project
        if project.story.scenes and not project.shots:
            project = project.model_copy(update={"shots": scene_to_shots(project.story)})
        if request.form is InputForm.storyboard_panel and project.storyboards and not project.shots:
            project = project.model_copy(update={"shots": panels_to_shots(project.storyboards)})
        return project, _collect_unknowns(project)

    # Bare idea/script text -> a single shot, with unspecified specifics recorded
    # as inferences/proposals rather than invented canon.
    shot, facts, unresolved = _shot_from_idea(request.text)
    project = ProjectIR(
        meta={"source": "idea", "text": request.text},
        shots=[shot],
    )
    project.facts.inferred.extend(f for f in facts if f.status is FactStatus.inferred)
    project.facts.proposed.extend(f for f in facts if f.status is FactStatus.proposed)
    for constraint in request.system_constraints:
        project.facts.defined.append(
            Fact(key="system_constraint", value=constraint, authority=SourceAuthority.system_constraint, status=FactStatus.defined)
        )
    return project, unresolved


def _shot_from_idea(text: str) -> tuple[ShotIR, list[Fact], list[str]]:
    idea = (text or "").strip().rstrip(".")
    subject, action = _split_subject_action(idea)
    setting = _extract_setting(action or idea)

    character_state: dict[str, object] = {}
    facts: list[Fact] = []
    unresolved: list[str] = []

    if subject:
        character_state["subject"] = subject
        facts.append(Fact(key="subject", value=subject, authority=SourceAuthority.reasonable_inference, status=FactStatus.inferred))
    else:
        unresolved.append("character: no subject stated in the idea — supply one or accept a proposed lead")

    location = {"description": setting} if setting else {}
    if setting:
        facts.append(Fact(key="location", value=setting, authority=SourceAuthority.reasonable_inference, status=FactStatus.inferred))
    else:
        unresolved.append("location: setting not stated in the idea")

    shot = ShotIR(
        id="shot_001",
        purpose=idea,
        primary_action=action or idea,
        character_state=character_state,
        location=location,
        light={"source": "available light"},  # CREATIVE_DEFAULT, recorded below
        final_frame=_default_final_frame(action or idea),
    )
    facts.append(Fact(key="light", value="available light", authority=SourceAuthority.creative_default, status=FactStatus.proposed))
    return shot, facts, unresolved


def _split_subject_action(idea: str) -> tuple[str | None, str]:
    tokens = idea.split()
    lowered = [t.lower().strip(",") for t in tokens]
    for i, tok in enumerate(lowered):
        if tok in _VERBS and i > 0:
            return " ".join(tokens[:i]), " ".join(tokens[i:])
    return None, idea


def _extract_setting(text: str) -> str | None:
    match = _SETTING_RE.search(text or "")
    if not match:
        return None
    tail = match.group(1).strip().rstrip(".")
    # Keep it short; the setting is a phrase, not the rest of the sentence.
    return tail if len(tail) <= 60 else tail[:60]


def _default_final_frame(action: str):
    from .schemas import FinalFrameHandshake

    return FinalFrameHandshake(motion_state="the described action resolves and settles")


def _collect_unknowns(project: ProjectIR) -> list[str]:
    return [
        f"{fact.key}: {fact.note or 'unknown critical fact'}"
        for fact in project.facts.defined + project.facts.inferred + project.facts.proposed
        if fact.status is FactStatus.unknown_critical
    ]


# --------------------------------------------------------------------------- #
# Target resolution / compilation
# --------------------------------------------------------------------------- #
def _resolve_target(request: CinematicRequest, mode: InputMode) -> PromptTarget:
    if request.target is not None:
        return request.target
    if mode is InputMode.storyboard:
        return PromptTarget.storyboard
    if request.source_image or request.form is InputForm.image:
        return PromptTarget.i2v
    if mode is InputMode.brand:
        return PromptTarget.motion
    return PromptTarget.t2v


def _compile_for_target(shot: ShotIR, target: PromptTarget, request: CinematicRequest) -> CompiledPrompt:
    if target is PromptTarget.t2i:
        return compile_t2i(shot)
    if target is PromptTarget.i2v:
        return compile_i2v(shot, request.source_image or "source image")
    # motion falls back to a T2V-style compile (brand-motion folded into atmosphere upstream)
    return compile_t2v(shot)


def _propagate_all(shots: list[ShotIR]) -> list[ShotIR]:
    if not shots:
        return shots
    out = [shots[0]]
    for nxt in shots[1:]:
        out.append(propagate(out[-1], nxt))
    return out


def _panel_from_shot(shot: ShotIR, number: int) -> StoryboardPanel:
    from .storyboard import shot_to_panel

    return shot_to_panel(shot, number)


# Re-exported for convenience / typing.
__all__ = ["PipelineResult", "run_pipeline", "Story", "Scene", "Beat"]
