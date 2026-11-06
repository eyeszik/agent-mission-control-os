"""Image, video and storyboard specifications, compiled to prompt packages; generation stays gated.

Specs are provider-neutral contracts. ``compile_image_spec`` / ``compile_storyboard`` derive
them from a brief and a PSEM genome (palette, negative constraints from the grammar's
anti-patterns). ``generation_status`` reports whether a verified provider adapter exists for
the medium; none is installed, so it is ``CAPABILITY_GAP`` and no image or video bytes are
ever produced or claimed here. The procedural plates the website uses are a different, local
route (``foundry.psem.plate``) and are labelled as such.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field

from services.langgraph.agency.foundry import psem
from services.langgraph.agency.foundry.contracts import CreativeGenome
from services.langgraph.agency.foundry.grammars import GRAMMARS
from services.langgraph.agency.prompt_compiler import GENERATION_FIREWALL

from .contracts import WebsiteBrief, _Strict


class ImageSpec(_Strict):
    spec_id: str
    subject: str
    scene: str
    composition: str
    camera_description: str
    lighting: str
    materials: str
    palette: dict[str, str]
    mood: str
    reference_refs: tuple[str, ...] = ()
    negative_constraints: tuple[str, ...]
    aspect_ratio: Literal["1:1", "3:2", "4:5", "16:9", "9:16"]
    output_requirements: dict[str, str]
    rights: Literal["generated_by_verified_provider", "licensed", "owned"]
    provenance: dict[str, str]


class StoryboardShot(_Strict):
    shot_id: str
    sequence: int = Field(ge=1)
    description: str
    visual_spec: str                    # ImageSpec id
    duration_s: float = Field(gt=0, le=60)
    camera: str
    motion: str
    continuity_constraints: tuple[str, ...]
    asset_refs: tuple[str, ...] = ()
    verification: tuple[str, ...]


class VideoSpec(_Strict):
    spec_id: str
    narrative: str
    shot_list: tuple[str, ...]
    scene_refs: tuple[str, ...]
    duration_s: float = Field(gt=0, le=600)
    frame_rate: Literal[24, 25, 30]
    camera_movement: str
    motion: str
    continuity: tuple[str, ...]
    transitions: tuple[str, ...]
    audio_requirements: str
    output_requirements: dict[str, str]
    rights: Literal["generated_by_verified_provider", "licensed", "owned"]


PROVIDERS: dict[str, Optional[str]] = {"image": None, "video": None}  # no verified adapter is installed


def generation_status(medium: Literal["image", "video"]) -> dict:
    adapter = PROVIDERS.get(medium)
    if adapter is None:
        return {"medium": medium, "status": "CAPABILITY_GAP", "reason": f"no verified {medium} provider adapter is installed",
                "terminal_state": GENERATION_FIREWALL, "generated": False}
    return {"medium": medium, "status": "ADAPTER_PRESENT_REQUIRES_AUTHORIZATION", "adapter": adapter, "generated": False}


def _negatives(genome: CreativeGenome) -> tuple[str, ...]:
    grammar = GRAMMARS[genome.composition_rules["dominant_grammar"]]
    return tuple(grammar.anti_patterns) + ("text rendered inside the image", "logos or marks of other organizations")


def compile_image_spec(brief: WebsiteBrief, genome: CreativeGenome, asset_id: str, *, subject: str, scene: str) -> ImageSpec:
    image = next((i for i in brief.images if i.asset_id == asset_id), None)
    if image is None:
        raise KeyError(f"image {asset_id} is not declared in the brief")
    return ImageSpec(
        spec_id=f"img-{asset_id}", subject=subject, scene=scene,
        composition="monumental negative space; subject small in the frame; optical asymmetry on a 12-column grid",
        camera_description="medium-format, long lens, eye level, no distortion",
        lighting="soft overcast, low contrast, atmospheric haze", materials="matte print surface with fine analog grain",
        palette={name: psem.PALETTE[name] for name in ("charcoal", "graphite", "fog", "paper", "signal_red")},
        mood="quiet, precise, impossible-yet-photographic", negative_constraints=_negatives(genome), aspect_ratio="3:2",
        output_requirements={"min_width_px": "2400", "format": "image/png", "alt_text": image.alt},
        rights="generated_by_verified_provider", provenance={"brief": brief.content_hash, "genome": genome.content_hash})


def compile_storyboard(spec: ImageSpec, *, shots: int = 3) -> tuple[StoryboardShot, ...]:
    return tuple(StoryboardShot(
        shot_id=f"{spec.spec_id}-s{n}", sequence=n, description=f"{spec.subject}: beat {n} of {shots}", visual_spec=spec.spec_id,
        duration_s=4.0, camera=("static wide", "slow push-in", "static detail")[(n - 1) % 3],
        motion="minimal; respects reduced motion with a still frame", continuity_constraints=(
            "same palette roles", "same light direction", "subject never identifiable as a real person"),
        verification=("ffprobe duration and fps", "palette conformance", "human review")) for n in range(1, shots + 1))


def compile_video_spec(spec: ImageSpec, board: tuple[StoryboardShot, ...]) -> VideoSpec:
    return VideoSpec(spec_id=f"vid-{spec.spec_id}", narrative=spec.subject, shot_list=tuple(s.shot_id for s in board),
                     scene_refs=(spec.spec_id,), duration_s=sum(s.duration_s for s in board), frame_rate=24,
                     camera_movement="; ".join(s.camera for s in board), motion="slow, ease-out; no flashing",
                     continuity=board[0].continuity_constraints, transitions=("cut",) * max(0, len(board) - 1),
                     audio_requirements="none, or licensed ambient bed with captions for any speech",
                     output_requirements={"format": "video/mp4", "codec": "h264", "max_bytes": "52428800"},
                     rights="generated_by_verified_provider")


def prompt_package(spec: ImageSpec | VideoSpec) -> dict:
    """Provider-neutral prompt text from a spec. Terminal: PROMPT_PACKAGE_READY; nothing is sent anywhere."""
    data = spec.model_dump(mode="json")
    lines = [f"{k}: {v}" for k, v in data.items() if k not in {"provenance", "palette"}]
    if isinstance(spec, ImageSpec):
        lines.append("palette: " + ", ".join(f"{k} {v}" for k, v in spec.palette.items()))
    medium = "image" if isinstance(spec, ImageSpec) else "video"
    return {"spec_id": spec.spec_id, "medium": medium, "prompt": "\n".join(lines), "spec_hash": spec.content_hash,
            "terminal_state": GENERATION_FIREWALL, "generation": generation_status(medium)}


__all__ = ["ImageSpec", "PROVIDERS", "StoryboardShot", "VideoSpec", "compile_image_spec", "compile_storyboard",
           "compile_video_spec", "generation_status", "prompt_package"]
