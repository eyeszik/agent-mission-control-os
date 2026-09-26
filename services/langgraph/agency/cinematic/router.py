"""Request routing and input classification for the cinematic capability.

Routing is driven by declarative trigger metadata, not a hand-tuned keyword
cascade, so it is deterministic and auditable. It deliberately does not hijack
ordinary coding, writing, or plain still-image requests. Capability/audit
requests are recognised as non-generative: they describe the system rather than
inventing a scene.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from . import CAPABILITY_ID, CAPABILITY_VERSION, GENERATION_FIREWALL
from .schemas import InputForm, InputMode, NON_GENERATIVE_MODES

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Declarative trigger phrases (checklist section 11). Multi-word phrases score
# higher because they are less ambiguous than single tokens.
CINEMATIC_TRIGGERS: tuple[str, ...] = (
    "cinematic video",
    "ai video",
    "text to video",
    "text-to-video",
    "image to video",
    "image-to-video",
    "storyboard",
    "shot list",
    "film scene",
    "cinematography",
    "camera movement",
    "video prompt",
    "video generation prompt",
    "director",
    "commercial video",
    "brand film",
    "product video",
    "character scene",
    "actor portrait",
    "cinematic prompt",
    "video creative direction",
    "motion graphics",
    "brand motion",
    "prompt to storyboard",
    "prompt-to-storyboard",
    "storyboard to video",
    "storyboard-to-video",
)

# Markers that indicate a request is NOT cinematic even if it mentions "video"
# in passing — prevents hijacking unrelated coding/writing/plain-image work.
_NEGATIVE_MARKERS: tuple[str, ...] = (
    "python", "javascript", "typescript", "function", "refactor", "unit test",
    "sql", "api endpoint", "essay", "blog post", "logo design", "spreadsheet",
)

# Mode keyword table (checklist section 12).
_MODE_KEYWORDS: dict[InputMode, tuple[str, ...]] = {
    InputMode.capability: ("what can", "capabilities", "what does", "can the cinematic", "what can you"),
    InputMode.audit: ("audit", "review the system", "assess the"),
    InputMode.system_design: ("system design", "architecture of", "design the system"),
    InputMode.workflow: ("workflow", "pipeline design", "process design"),
    InputMode.character: ("character", "actor portrait", "backstory"),
    InputMode.storyboard: ("storyboard", "9 panel", "9-panel", "panels"),
    InputMode.video_package: ("full video", "video package", "produce the video"),
    InputMode.prompts_only: ("just the prompt", "prompts only", "prompt only"),
    InputMode.revision: ("revise", "revision", "fix the shot", "change the shot"),
    InputMode.brand: ("brand motion", "brand film", "brand identity"),
    InputMode.automation: ("automation", "batch", "for every"),
}

_FORM_KEYWORDS: dict[InputForm, tuple[str, ...]] = {
    InputForm.script: ("script", "screenplay", "int.", "ext."),
    InputForm.treatment: ("treatment",),
    InputForm.dialogue: ("dialogue", "she says", "he says"),
    InputForm.image: ("image to video", "from this image", "source image", "photo"),
    InputForm.storyboard_panel: ("storyboard panel", "panel"),
    InputForm.character: ("character", "protagonist"),
    InputForm.location: ("location", "set "),
    InputForm.brand: ("brand",),
    InputForm.product: ("product",),
    InputForm.campaign: ("campaign",),
    InputForm.scene: ("scene",),
    InputForm.reference: ("reference",),
}


class RouteDecision(BaseModel):
    matched: bool
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    mode: InputMode | None = None
    form: InputForm | None = None
    generative: bool = False

    model_config = {"extra": "forbid"}


def route_request(text: str) -> RouteDecision:
    lowered = (text or "").lower()
    if not lowered.strip():
        return RouteDecision(matched=False, score=0.0, reason="empty request")

    hits = [phrase for phrase in CINEMATIC_TRIGGERS if phrase in lowered]
    negatives = [marker for marker in _NEGATIVE_MARKERS if marker in lowered]

    if not hits:
        return RouteDecision(matched=False, score=0.0, reason="no cinematic trigger present")

    # Weight multi-word matches; discount when strong non-cinematic markers exist.
    strength = sum(1.0 if " " in phrase or "-" in phrase else 0.6 for phrase in hits)
    score = min(1.0, strength / 2.0)
    if negatives:
        score *= 0.4
    if score < 0.25:
        return RouteDecision(
            matched=False,
            score=round(score, 3),
            reason=f"cinematic terms present but dominated by non-cinematic markers: {', '.join(negatives)}",
        )

    mode = classify_mode(text)
    return RouteDecision(
        matched=True,
        score=round(score, 3),
        reason="matched: " + ", ".join(hits),
        mode=mode,
        form=classify_form(text),
        generative=mode not in NON_GENERATIVE_MODES,
    )


def classify_mode(text: str) -> InputMode:
    lowered = (text or "").lower()
    for mode, keywords in _MODE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return mode
    # Default: a concrete creative ask is a video package unless narrowed above.
    return InputMode.video_package


def classify_form(text: str) -> InputForm | None:
    lowered = (text or "").lower()
    for form, keywords in _FORM_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return form
    return InputForm.idea


def capability_manifest() -> dict[str, object]:
    """Describe the capability without inventing any creative scene.

    Used for CAPABILITY / AUDIT / SYSTEM_DESIGN requests.
    """

    return {
        "capability_id": CAPABILITY_ID,
        "version": CAPABILITY_VERSION,
        "generation_firewall": GENERATION_FIREWALL,
        "produces": [
            "text-to-image prompts",
            "text-to-video prompts",
            "image-to-video prompts",
            "9-panel storyboards (bidirectional with shots)",
            "shot lists / SHOT_IR",
            "character identity & portrait references",
            "brand-motion specifications",
        ],
        "inputs": [f.value for f in InputForm],
        "modes": [m.value for m in InputMode],
        "guarantees": [
            "STATIC camera by default; movement must be motivated",
            "source authority preserved; inferences never silently become canon",
            "continuity handshake between consecutive shots",
            "portable, model-independent prompts for unknown generators",
            "never invokes a media provider or writes a generated asset",
        ],
    }
