"""Story reasoning: scenes/beats -> shots, performance, and portrait gating.

Story purpose is preserved on every shot. Backstory is only *used* where it
changes visible behaviour; actor portraits are only proposed for speaking,
recurring, or identity-sensitive characters.
"""

from __future__ import annotations

from .schemas import (
    Beat,
    Character,
    PerformanceSpec,
    ShotIR,
    ShotSize,
    Story,
)

# Coarse mapping from a beat's dramatic role to a default shot size, so a beat
# sequence yields a varied, purpose-driven shot list rather than flat coverage.
_BEAT_SHOT_SIZE = (ShotSize.ws, ShotSize.ms, ShotSize.cu)


def compile_performance(spec: PerformanceSpec) -> str:
    """Translate internal state into observable behaviour.

    Abstract emotion alone is never emitted; the NOTICE -> PROCESS -> DECIDE ->
    ACT -> REACT sequence and visible details carry the performance.
    """

    parts: list[str] = []
    visible = spec.visible_fields()
    if visible:
        parts.append(", ".join(f"{k.replace('_', ' ')} {v}" for k, v in visible.items()))
    if spec.beat_sequence:
        parts.append("beats: " + " -> ".join(spec.beat_sequence))
    if spec.subtext and visible:
        # Subtext is context for the visible behaviour, never a substitute.
        parts.append(f"(subtext: {spec.subtext})")
    return "; ".join(parts)


def scene_to_shots(story: Story) -> list[ShotIR]:
    """Convert a story's scenes/beats into a purpose-carrying shot sequence.

    Each beat becomes one shot; the shot's ``purpose`` preserves the beat's
    dramatic change so downstream compilers keep story intent.
    """

    shots: list[ShotIR] = []
    index = 0
    for scene in story.scenes:
        for position, beat in enumerate(scene.beats):
            index += 1
            shots.append(
                ShotIR(
                    id=f"shot_{index:03d}",
                    purpose=beat.dramatic_change or beat.summary,
                    primary_action=beat.summary,
                    shot_size=_BEAT_SHOT_SIZE[min(position, len(_BEAT_SHOT_SIZE) - 1)],
                    location={"id": scene.location_id} if scene.location_id else {},
                    character_state={"present": list(beat.characters)},
                )
            )
    return shots


def portrait_candidates(characters: list[Character]) -> list[Character]:
    """Characters that justify an actor portrait / identity reference."""

    return [c for c in characters if c.needs_portrait()]


def used_backstory(character: Character) -> str | None:
    """Backstory is only surfaced when it can shape visible behaviour."""

    if not character.backstory:
        return None
    if character.speaking or character.recurring or character.movement_signature:
        return character.backstory
    return None


def beats_present(story: Story) -> list[Beat]:
    return [beat for scene in story.scenes for beat in scene.beats]
