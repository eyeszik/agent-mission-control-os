"""Final prompt compilers: T2I, T2V, I2V, failure-prevention, entropy control.

All compilers consume :class:`ShotIR` (never raw user input) so project context
is resolved once. Output is natural language by default; JSON is only emitted
when a target adapter demands it. Compression happens last and never removes a
protected dimension: who, where, what changes, camera, light, continuity, end
state.
"""

from __future__ import annotations

from .render import compile_lighting, compile_physics
from .camera import camera_summary
from .story import compile_performance
from .schemas import (
    Clause,
    ClauseWeight,
    CompiledPrompt,
    PromptTarget,
    ShotIR,
)

# Dimensions that must survive compression (checklist section 28).
PROTECTED_DIMENSIONS: frozenset[str] = frozenset(
    {"identity", "location", "action", "camera", "light", "continuity", "end_state"}
)

# Targeted, positive stabilising phrasing per known failure class (section 27).
_FAILURE_STABILISERS: dict[str, str] = {
    "identity drift": "hold the same face and identity throughout",
    "identity_drift": "hold the same face and identity throughout",
    "body geometry": "keep anatomy consistent and correctly proportioned",
    "duplicate objects": "exactly the objects described, no duplicates",
    "missing props": "keep the named props present in frame",
    "wardrobe mutation": "keep wardrobe unchanged across the shot",
    "geometry melting": "keep solid forms stable and non-warping",
    "camera jitter": "smooth, stable camera",
    "lighting discontinuity": "consistent lighting direction and colour",
    "text corruption": "render any text cleanly and legibly",
    "background mutation": "keep the background stable and consistent",
    "unmotivated zoom": "no unmotivated zoom",
    "temporal discontinuity": "continuous, chronological motion",
}

_DEFAULT_MAX_CHARS = 900


# --------------------------------------------------------------------------- #
# Text-to-video (checklist section 25)
# --------------------------------------------------------------------------- #
def compile_t2v(shot: ShotIR, *, max_chars: int = _DEFAULT_MAX_CHARS) -> CompiledPrompt:
    clauses: list[Clause] = []

    if shot.duration:
        clauses.append(Clause(text=f"{shot.duration:g}s shot", weight=ClauseWeight.important, dimension="format"))
    identity = _identity(shot)
    if identity:
        clauses.append(Clause(text=identity, weight=ClauseWeight.critical, dimension="identity"))
    where = _location(shot)
    if where:
        clauses.append(Clause(text=where, weight=ClauseWeight.critical, dimension="location"))
    if shot.start_frame:
        clauses.append(Clause(text=f"opening on {_flatten(shot.start_frame)}", weight=ClauseWeight.important, dimension="start"))
    if shot.primary_action:
        clauses.append(Clause(text=shot.primary_action, weight=ClauseWeight.critical, dimension="action"))
    if shot.secondary_action:
        clauses.append(Clause(text=shot.secondary_action, weight=ClauseWeight.optional, dimension="secondary"))
    performance = compile_performance(shot.performance)
    if performance:
        clauses.append(Clause(text=performance, weight=ClauseWeight.important, dimension="performance"))
    if shot.dialogue:
        clauses.append(Clause(text=f'dialogue: "{shot.dialogue}"', weight=ClauseWeight.important, dimension="dialogue"))
    clauses.append(Clause(text=_framing(shot), weight=ClauseWeight.critical, dimension="camera"))
    clauses.append(Clause(text=f"{shot.focus.value.lower()} focus", weight=ClauseWeight.optional, dimension="focus"))
    lighting = compile_lighting(shot.light, shot.materials)
    if lighting:
        clauses.append(Clause(text=lighting, weight=ClauseWeight.critical, dimension="light"))
    if shot.atmosphere:
        clauses.append(Clause(text=_flatten(shot.atmosphere), weight=ClauseWeight.optional, dimension="atmosphere"))
    for event in shot.physics:
        clauses.append(Clause(text=compile_physics(event), weight=ClauseWeight.important, dimension="physics"))
    end = _final_frame(shot)
    if end:
        clauses.append(Clause(text=f"ends with {end}", weight=ClauseWeight.critical, dimension="end_state"))

    negatives = compile_failure_prevention(shot)
    prompt, dropped = _assemble(clauses, max_chars)
    return CompiledPrompt(
        target=PromptTarget.t2v,
        shot_id=shot.id,
        prompt=prompt,
        negative_constraints=negatives,
        dropped_optional=dropped,
    )


# --------------------------------------------------------------------------- #
# Text-to-image (checklist section 24)
# --------------------------------------------------------------------------- #
def compile_t2i(shot: ShotIR, *, max_chars: int = _DEFAULT_MAX_CHARS) -> CompiledPrompt:
    clauses: list[Clause] = []
    identity = _identity(shot)
    if identity:
        clauses.append(Clause(text=identity, weight=ClauseWeight.critical, dimension="identity"))
    wardrobe = _wardrobe(shot)
    if wardrobe:
        clauses.append(Clause(text=wardrobe, weight=ClauseWeight.important, dimension="wardrobe"))
    where = _location(shot)
    if where:
        clauses.append(Clause(text=where, weight=ClauseWeight.critical, dimension="location"))
    if shot.primary_action:
        clauses.append(Clause(text=shot.primary_action, weight=ClauseWeight.critical, dimension="action"))
    clauses.append(Clause(text=_framing(shot), weight=ClauseWeight.important, dimension="camera"))
    lighting = compile_lighting(shot.light, shot.materials)
    if lighting:
        clauses.append(Clause(text=lighting, weight=ClauseWeight.critical, dimension="light"))
    clauses.append(Clause(text=f"{shot.focus.value.lower()} depth of field", weight=ClauseWeight.optional, dimension="depth"))
    if shot.color:
        clauses.append(Clause(text=_flatten(shot.color), weight=ClauseWeight.optional, dimension="color"))
    negatives = compile_failure_prevention(shot)
    prompt, dropped = _assemble(clauses, max_chars)
    return CompiledPrompt(
        target=PromptTarget.t2i,
        shot_id=shot.id,
        prompt=prompt,
        negative_constraints=negatives,
        dropped_optional=dropped,
    )


# --------------------------------------------------------------------------- #
# Image-to-video (checklist section 26)
# --------------------------------------------------------------------------- #
def compile_i2v(shot: ShotIR, source_image: str, *, max_chars: int = _DEFAULT_MAX_CHARS) -> CompiledPrompt:
    """Source image is the appearance source; the prompt is about motion, not
    re-description of what the image already fixes."""

    clauses: list[Clause] = [
        Clause(
            text=f"preserve the subject, wardrobe and composition of the source image ({source_image})",
            weight=ClauseWeight.critical,
            dimension="identity",
        )
    ]
    if shot.primary_action:
        clauses.append(Clause(text=f"animate: {shot.primary_action}", weight=ClauseWeight.critical, dimension="action"))
    if shot.secondary_action:
        clauses.append(Clause(text=shot.secondary_action, weight=ClauseWeight.optional, dimension="secondary"))
    if shot.camera.is_moving:
        clauses.append(Clause(text=camera_summary(shot.camera), weight=ClauseWeight.critical, dimension="camera"))
    lighting = compile_lighting(shot.light, shot.materials)
    if lighting:
        clauses.append(Clause(text=f"light evolves: {lighting}", weight=ClauseWeight.important, dimension="light"))
    for event in shot.physics:
        clauses.append(Clause(text=compile_physics(event), weight=ClauseWeight.important, dimension="physics"))
    end = _final_frame(shot)
    if end:
        clauses.append(Clause(text=f"settles on {end}", weight=ClauseWeight.critical, dimension="end_state"))

    negatives = compile_failure_prevention(shot)
    prompt, dropped = _assemble(clauses, max_chars)
    return CompiledPrompt(
        target=PromptTarget.i2v,
        shot_id=shot.id,
        prompt=prompt,
        negative_constraints=negatives,
        dropped_optional=dropped,
    )


# --------------------------------------------------------------------------- #
# Targeted failure prevention (checklist section 27)
# --------------------------------------------------------------------------- #
def compile_failure_prevention(shot: ShotIR) -> list[str]:
    """Only constraints tied to this shot's declared risks, phrased positively."""

    out: list[str] = []
    for risk in shot.failure_risks:
        key = risk.strip().lower()
        stabiliser = _FAILURE_STABILISERS.get(key)
        if stabiliser is None:
            # Fall back to a positive restatement of the risk.
            stabiliser = f"avoid {key}"
        if stabiliser not in out:
            out.append(stabiliser)
    return out


# --------------------------------------------------------------------------- #
# Entropy control (checklist section 28)
# --------------------------------------------------------------------------- #
def _assemble(clauses: list[Clause], max_chars: int) -> tuple[str, list[str]]:
    """Join clauses into a natural-language prompt, dropping only OPTIONAL /
    lowest-value clauses (never a protected dimension) to fit the budget."""

    kept = list(clauses)
    dropped: list[str] = []

    def render(items: list[Clause]) -> str:
        return ". ".join(c.text for c in items if c.text).strip()

    # Drop optionals first, then lowest-weight non-protected clauses, until we fit.
    while len(render(kept)) > max_chars:
        candidate_index = _lowest_droppable(kept)
        if candidate_index is None:
            break
        dropped.append(kept[candidate_index].text)
        kept.pop(candidate_index)

    return render(kept), dropped


def _lowest_droppable(clauses: list[Clause]) -> int | None:
    best_index: int | None = None
    best_weight = ClauseWeight.critical
    for index, clause in enumerate(clauses):
        if clause.dimension in PROTECTED_DIMENSIONS:
            continue
        if clause.weight is ClauseWeight.critical:
            continue
        if best_index is None or clause.weight.value < best_weight.value:
            best_index = index
            best_weight = clause.weight
    return best_index


# --------------------------------------------------------------------------- #
# Field helpers
# --------------------------------------------------------------------------- #
def _identity(shot: ShotIR) -> str:
    present = shot.character_state.get("present") if isinstance(shot.character_state, dict) else None
    subject = shot.character_state.get("subject") if isinstance(shot.character_state, dict) else None
    if subject:
        return str(subject)
    if present:
        return ", ".join(str(p) for p in present)
    return ""


def _wardrobe(shot: ShotIR) -> str:
    if isinstance(shot.character_state, dict):
        wardrobe = shot.character_state.get("wardrobe")
        if wardrobe:
            return str(wardrobe)
    return ""


def _location(shot: ShotIR) -> str:
    if isinstance(shot.location, dict):
        for key in ("description", "name", "id"):
            value = shot.location.get(key)
            if value:
                return str(value)
    return ""


def _framing(shot: ShotIR) -> str:
    base = f"{shot.shot_size.value} {shot.angle.value.lower()}-level, {shot.lens.value.lower()} lens"
    if shot.camera.is_moving:
        return f"{base}, {camera_summary(shot.camera)}"
    return f"{base}, static camera"


def _final_frame(shot: ShotIR) -> str:
    ff = shot.final_frame
    parts = [
        ff.subject_position,
        ff.gaze,
        ff.prop_state,
        ff.motion_state,
    ]
    return ", ".join(p for p in parts if p)


def _flatten(value: object) -> str:
    if isinstance(value, dict):
        return ", ".join(str(v) for v in value.values() if v)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v)
    return str(value)
