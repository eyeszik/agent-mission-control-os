"""The UCPO capability activation matrix, computed on this host. Nothing here is asserted from configuration."""

from __future__ import annotations

from .disciplines import DISCIPLINES, availability, route
from .multimodal import generation_status
from .presentation import SYSTEMS
from .prompt_modules import library


def capability_matrix() -> dict:
    caps = availability()
    return {
        "capabilities": caps,
        "disciplines": [{**d.describe(), "route": route(d.discipline_id, available=caps)} for d in DISCIPLINES],
        "presentation_systems": [s.describe() for s in SYSTEMS.values()],
        "prompt_modules": library(),
        "generation": {"image": generation_status("image"), "video": generation_status("video")},
        "deployment": "NOT_AUTHORIZED: no route here deploys, publishes or sends",
    }


__all__ = ["capability_matrix"]
