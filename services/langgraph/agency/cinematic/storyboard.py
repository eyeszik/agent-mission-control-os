"""Bidirectional storyboard: SCRIPT -> STORYBOARD and STORYBOARD -> SHOT_IR.

Default board is 9 panels (3x3). Rough-board priority order is composition,
blocking, camera, action, screen direction. Panel <-> shot mapping is preserved
so a board round-trips into video prompts.
"""

from __future__ import annotations

from .schemas import (
    CameraAngle,
    LensIntent,
    ShotIR,
    ShotSize,
    Story,
    StoryboardPanel,
)
from .story import scene_to_shots

DEFAULT_PANELS = 9


def script_to_storyboard(story: Story, panels: int = DEFAULT_PANELS) -> list[StoryboardPanel]:
    """Turn a script/story into a numbered storyboard (9-panel default).

    Panels are derived from the story's shot plan so panel N maps to shot N.
    """

    shots = scene_to_shots(story)
    board: list[StoryboardPanel] = []
    for number in range(1, panels + 1):
        shot = shots[number - 1] if number - 1 < len(shots) else None
        if shot is None:
            board.append(StoryboardPanel(number=number, composition="(hold / empty panel)"))
            continue
        board.append(shot_to_panel(shot, number))
    return board


def shot_to_panel(shot: ShotIR, number: int) -> StoryboardPanel:
    present = ", ".join(shot.character_state.get("present", [])) if isinstance(shot.character_state, dict) else ""
    return StoryboardPanel(
        number=number,
        shot_id=shot.id,
        shot_size=shot.shot_size.value,
        angle=shot.angle.value,
        lens=shot.lens.value,
        camera=shot.camera.move.value,
        composition=shot.purpose or shot.primary_action,
        character_pose=present,
        blocking=shot.primary_action,
        action=shot.primary_action,
        dialogue=shot.dialogue or "",
        continuity=shot.continuity.inherits_from or "",
    )


def panels_to_shots(panels: list[StoryboardPanel]) -> list[ShotIR]:
    """Recover blocking and camera interpretation from panels into SHOT_IR."""

    shots: list[ShotIR] = []
    for panel in panels:
        if not (panel.action or panel.blocking or panel.composition):
            continue
        shots.append(
            ShotIR(
                id=panel.shot_id or f"shot_{panel.number:03d}",
                purpose=panel.composition,
                primary_action=panel.action or panel.blocking,
                shot_size=_coerce(ShotSize, panel.shot_size, ShotSize.ms),
                angle=_coerce(CameraAngle, panel.angle, CameraAngle.eye),
                lens=_coerce(LensIntent, panel.lens, LensIntent.natural),
                dialogue=panel.dialogue or None,
            )
        )
    return shots


def _coerce(enum_cls, value: str, default):
    if not value:
        return default
    try:
        return enum_cls(value)
    except ValueError:
        for member in enum_cls:
            if member.value.lower() == value.strip().lower():
                return member
    return default
