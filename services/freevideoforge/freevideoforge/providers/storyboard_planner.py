"""Deterministic storyboard and shot planner.

This is the CREATIVE_COMPILER: it turns a script into fully specified scenes
where CONTENT_SPEC, VISUAL_SPEC and MOTION_SPEC are separate structures rather
than one opaque prompt string. Temporal continuity is explicit - each scene
records the end state it hands to the next one.

It is deterministic and seeded, so a storyboard can be regenerated exactly, and
it produces a renderer-agnostic plan: the same storyboard drives the mandatory
FFmpeg renderer, and would drive an image or video model without change.
"""

from __future__ import annotations

import random
from typing import Any

from ..models import ContentSpec, MotionSpec, Project, Scene, VisualSpec
from .base import Capability

#: Named palettes. Each is (background_a, background_b, accent, ink, muted).
#: All hand-picked for contrast at small sizes on a phone screen.
STYLE_SYSTEMS: dict[str, dict[str, Any]] = {
    "editorial": {
        "palette": ["#0B1020", "#161E38", "#F5C451", "#F7F5EF", "#8E9BB7"],
        "font_stack": "serif_display",
        "lighting": "soft key from upper left, deep falloff",
        "mood": "calm, considered, print-like",
    },
    "neon": {
        "palette": ["#0A0618", "#241046", "#4DE1C1", "#F2F0FF", "#9A86D6"],
        "font_stack": "grotesque",
        "lighting": "rim light, high contrast, glow bloom",
        "mood": "kinetic, late-night, high energy",
    },
    "clean": {
        "palette": ["#F6F7FB", "#E5E9F5", "#2F5BEA", "#0D1222", "#5C6685"],
        "font_stack": "grotesque",
        "lighting": "flat diffuse daylight",
        "mood": "clear, product-like, unfussy",
    },
    "warm": {
        "palette": ["#1A120B", "#2E1D10", "#E08D3C", "#FDF3E3", "#A98763"],
        "font_stack": "serif_display",
        "lighting": "low golden key, long shadows",
        "mood": "grounded, human, documentary",
    },
    "slate": {
        "palette": ["#101418", "#1C232B", "#5FD3A6", "#EDF2F6", "#7C8B99"],
        "font_stack": "grotesque",
        "lighting": "cool overcast key",
        "mood": "technical, precise, neutral",
    },
}

#: Style chosen from the narrative shape when the caller says "auto".
SHAPE_STYLE = {
    "question": "editorial",
    "explainer": "editorial",
    "how_to": "clean",
    "listicle": "neon",
    "myth_bust": "warm",
    "comparison": "slate",
}

#: Background motifs, deliberately abstract. They carry rhythm and depth
#: without claiming to depict the subject.
MOTIFS = ("rings", "grid", "waveform", "strata", "orbit", "contour", "beam")

#: Motif affinity per narrative role, so the visual arc tracks the story arc.
ROLE_MOTIFS = {
    "hook": ("orbit", "beam", "rings"),
    "context": ("strata", "contour", "grid"),
    "body": ("grid", "waveform", "contour", "strata"),
    "turn": ("beam", "orbit", "rings"),
    "payoff": ("rings", "strata", "beam"),
}

SHOT_SIZES = {
    "hook": "wide establishing",
    "context": "medium",
    "body": "medium close",
    "turn": "close",
    "payoff": "wide resolve",
}

COMPOSITIONS = {
    "hook": "centered, generous negative space above",
    "context": "lower third weighted, horizon high",
    "body": "left-weighted, subject offset on the thirds",
    "turn": "centered, tight, symmetry broken by the accent",
    "payoff": "centered, calm, everything settled",
}

#: (camera description, motion id, zoom_start, zoom_end, pan_x, pan_y)
CAMERA_MOVES: tuple[tuple[str, str, float, float, float, float], ...] = (
    ("slow push in", "push_in", 1.00, 1.10, 0.00, 0.00),
    ("slow pull back", "pull_back", 1.10, 1.00, 0.00, 0.00),
    ("drift left to right", "pan_right", 1.06, 1.08, -0.05, 0.00),
    ("drift right to left", "pan_left", 1.06, 1.08, 0.05, 0.00),
    ("rise", "tilt_up", 1.05, 1.09, 0.00, 0.05),
    ("settle down", "tilt_down", 1.09, 1.04, 0.00, -0.04),
)

TRANSITIONS = ("fade", "dip_to_ink", "soft_cut")

NEGATIVE_CONSTRAINTS = [
    "no text artifacts",
    "no watermark",
    "no photoreal human faces",
    "no brand marks",
    "no illegible small type",
]


class DeterministicStoryboardProvider:
    """Always-available storyboard planner. No model, no network."""

    name = "deterministic"
    kind = "storyboard"

    def probe(self) -> Capability:
        return Capability(
            available=True,
            name=self.name,
            kind=self.kind,
            detail="Seeded shot planner with explicit content/visual/motion separation.",
            version="1.0.0",
            metadata={"style_systems": sorted(STYLE_SYSTEMS)},
        )

    @staticmethod
    def resolve_style(requested: str, shape: str) -> str:
        if requested in STYLE_SYSTEMS:
            return requested
        return SHAPE_STYLE.get(shape, "editorial")

    def plan(self, project: Project, script: dict[str, Any]) -> list[Scene]:
        rng = random.Random(project.seed ^ 0x5F5E1)
        style_name = self.resolve_style(project.style_system, script.get("shape", "explainer"))
        style = STYLE_SYSTEMS[style_name]
        project.style_system = style_name

        beats = script.get("beats", [])
        scenes: list[Scene] = []
        previous_end_state = "cold open, screen at rest"

        for index, beat in enumerate(beats):
            role = beat.get("role", "body")
            motif_pool = ROLE_MOTIFS.get(role, MOTIFS)
            motif = motif_pool[index % len(motif_pool)]
            camera, motion_id, zoom_a, zoom_b, pan_x, pan_y = CAMERA_MOVES[
                (index + project.seed) % len(CAMERA_MOVES)
            ]
            # Alternate drift direction so consecutive scenes never repeat the
            # same move, which is what makes a procedural render feel looped.
            if index and scenes and scenes[-1].motion.motion == motion_id:
                camera, motion_id, zoom_a, zoom_b, pan_x, pan_y = CAMERA_MOVES[
                    (index + project.seed + 1) % len(CAMERA_MOVES)
                ]

            duration = float(beat.get("target_duration", project.duration / max(1, len(beats))))
            headline = beat.get("headline", "")
            kicker = beat.get("kicker", "")
            voiceover = beat.get("voiceover", "")

            visual_subject = self._visual_subject(script, role, headline)
            environment = f"{style['mood']}; {style['lighting']}"
            end_state = (
                f"{motif} field settled at {zoom_b:.2f}x zoom, accent colour holding "
                f"{'left' if pan_x > 0 else 'right' if pan_x < 0 else 'centre'}"
            )

            scene = Scene(
                id=f"s{index + 1:02d}",
                index=index,
                duration=round(duration, 3),
                seed=project.seed * 1000 + index,
                content=ContentSpec(
                    narrative_function=role,
                    voiceover=voiceover,
                    text_overlay=headline,
                    kicker=kicker,
                    key_point=beat.get("headline", ""),
                ),
                visual=VisualSpec(
                    visual_subject=visual_subject,
                    environment=environment,
                    composition=COMPOSITIONS.get(role, "centered"),
                    shot_size=SHOT_SIZES.get(role, "medium"),
                    lighting=style["lighting"],
                    palette=list(style["palette"]),
                    motif=motif,
                    continuity=f"continues from: {previous_end_state}",
                    # A renderer-agnostic prompt for any future image/video
                    # backend. The FFmpeg renderer ignores it and reads the
                    # structured fields instead.
                    media_prompt=(
                        f"{SHOT_SIZES.get(role, 'medium')} abstract {motif} composition, "
                        f"{visual_subject}, {style['mood']}, {style['lighting']}, "
                        f"palette {' '.join(style['palette'][:3])}, "
                        f"{COMPOSITIONS.get(role, 'centered')}, no text"
                    ),
                    negative_constraints=list(NEGATIVE_CONSTRAINTS),
                ),
                motion=MotionSpec(
                    camera=camera,
                    motion=motion_id,
                    zoom_start=zoom_a,
                    zoom_end=zoom_b,
                    pan_x=pan_x,
                    pan_y=pan_y,
                    parallax=round(0.25 + rng.random() * 0.25, 3),
                    transition=TRANSITIONS[index % len(TRANSITIONS)] if index else "fade",
                    transition_seconds=round(min(0.45, duration * 0.12), 3),
                ),
            )
            scenes.append(scene)
            previous_end_state = end_state

        return scenes

    @staticmethod
    def _visual_subject(script: dict[str, Any], role: str, headline: str) -> str:
        """A short description of what the frame shows.

        Abstract on purpose: a procedural renderer that claimed to depict the
        literal subject would be lying about what it produced.
        """
        topic = script.get("topic", "the subject")
        if role == "hook":
            return f"opening title card for '{topic}'"
        if role == "payoff":
            return "closing statement card, composition at rest"
        if role == "turn":
            return "the accent element breaking the established symmetry"
        if role == "context":
            return "layered background establishing scale and stakes"
        return f"supporting card for '{headline or topic}'"
