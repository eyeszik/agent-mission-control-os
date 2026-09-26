"""Model adapters and portable fallback.

The core compilers are vendor-neutral. Known models are adapted into their
dialect; unknown models receive the portable natural-language prompt unchanged.
Capabilities are never fabricated, hard constraints are never silently dropped —
unsupported requirements are surfaced explicitly. The ``/use-after-effects``
compatibility prefix is legacy metadata only and is never emitted by default.
"""

from __future__ import annotations

import json

from .schemas import CompiledPrompt, ModelProfile

# Portable, vendor-neutral default. Natural-language, no invented parameters.
PORTABLE_PROFILE = ModelProfile(
    provider=None,
    model=None,
    prompt_style="natural",
    reference_support=None,
    negative_support=None,
    camera_control=None,
    audio=None,
    seed=None,
)


def adapt(prompt: CompiledPrompt, profile: ModelProfile | None) -> CompiledPrompt:
    """Return a prompt shaped for ``profile``.

    - Unknown / no profile -> portable natural-language prompt, unchanged.
    - ``prompt_style == 'json'`` -> emit a JSON payload for that target.
    - Negatives the model cannot take are surfaced as unsupported requirements
      rather than discarded.
    """

    profile = profile or PORTABLE_PROFILE
    unsupported = list(prompt.unsupported_requirements)

    # Never fabricate: only drop negatives when the model explicitly cannot take
    # them, and record that we did so.
    negatives = list(prompt.negative_constraints)
    if profile.negative_support is False and negatives:
        unsupported.extend(f"negative:{n}" for n in negatives)
        negatives = []

    if profile.camera_control is False:
        # Camera intent stays in the natural-language body; we just note the model
        # cannot take a structured camera-control channel.
        unsupported.append("structured_camera_control")

    body = prompt.prompt
    style = profile.prompt_style or "natural"
    if style == "json":
        body = json.dumps(
            {
                "target": prompt.target.value,
                "prompt": prompt.prompt,
                "negatives": negatives,
            },
            ensure_ascii=True,
        )

    # Legacy prefix is opt-in only, through an adapter that explicitly requires it.
    if profile.legacy_prefix:
        body = f"{profile.legacy_prefix} {body}"

    return prompt.model_copy(
        update={
            "prompt": body,
            "prompt_style": style,
            "negative_constraints": negatives,
            "unsupported_requirements": _dedupe(unsupported),
        }
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
