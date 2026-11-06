"""Script-derived caption timing.

Captions are generated from the narration text and the *measured* duration of
each scene's synthesized audio, not from a guess. Within a scene, time is
distributed across caption lines in proportion to their spoken length, which
tracks real speech closely enough for short-form video without needing a
forced-alignment model.

If a forced-alignment provider is ever added it plugs in here as another
CaptionProvider; the pipeline does not change.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..models import Project
from .base import Capability, CaptionResult

#: Caption line limits tuned for a phone screen.
MAX_CHARS_PER_LINE = 42
MAX_WORDS_PER_CUE = 8
MIN_CUE_SECONDS = 0.7

#: Relative "speaking cost" of punctuation, so a line ending in a full stop
#: gets the pause it actually takes to say.
_PAUSE_WEIGHT = {",": 0.25, ";": 0.35, ":": 0.35, ".": 0.5, "!": 0.5, "?": 0.5, "—": 0.35}


def _split_into_cues(text: str) -> list[str]:
    """Break narration into caption-sized chunks at clause boundaries."""
    words = (text or "").split()
    if not words:
        return []
    cues: list[str] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        too_long = (
            len(" ".join(current)) >= MAX_CHARS_PER_LINE
            or len(current) >= MAX_WORDS_PER_CUE
        )
        ends_clause = word[-1] in ".!?;:," if word else False
        if too_long or (ends_clause and len(current) >= 4):
            cues.append(" ".join(current))
            current = []
    if current:
        if cues and len(current) <= 2:
            cues[-1] = f"{cues[-1]} {' '.join(current)}"
        else:
            cues.append(" ".join(current))
    return cues


def _weight(cue: str) -> float:
    """Approximate speaking time weight for a cue."""
    base = float(len(cue.split()))
    for char, extra in _PAUSE_WEIGHT.items():
        base += cue.count(char) * extra
    return max(0.5, base)


def format_timestamp(seconds: float) -> str:
    """SRT timestamp: HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000.0))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(cues: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n"
            f"{format_timestamp(cue['start'])} --> {format_timestamp(cue['end'])}\n"
            f"{cue['text']}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


class ScriptDerivedCaptionProvider:
    """Always-available caption timing. No model, no network."""

    name = "script_derived"
    kind = "captions"

    def probe(self) -> Capability:
        return Capability(
            available=True,
            name=self.name,
            kind=self.kind,
            detail=(
                "Caption timing derived from narration text and measured scene "
                "audio durations."
            ),
            version="1.0.0",
            metadata={"technique": "script_derived", "alignment": "proportional"},
        )

    def generate(self, project: Project, output: Path) -> CaptionResult:
        cues: list[dict[str, Any]] = []
        timeline = 0.0
        for scene in project.scenes:
            # The scene's own clip length is authoritative: captions must land
            # inside the frames that actually exist.
            span = float(scene.duration)
            speech = float(scene.audio_duration or span)
            usable = min(span, speech) if speech > 0 else span
            lead_in = 0.08 if span > 0.6 else 0.0

            texts = _split_into_cues(scene.content.voiceover)
            if not texts:
                timeline += span
                continue

            weights = [_weight(text) for text in texts]
            total = sum(weights) or 1.0
            available = max(0.3, usable - lead_in)
            cursor = timeline + lead_in
            for index, (text, weight) in enumerate(zip(texts, weights)):
                length = available * weight / total
                if index == len(texts) - 1:
                    end = timeline + min(span, lead_in + available)
                else:
                    end = cursor + length
                end = max(cursor + MIN_CUE_SECONDS * 0.5, end)
                end = min(end, timeline + span)
                cues.append(
                    {
                        "index": len(cues) + 1,
                        "scene_id": scene.id,
                        "text": text,
                        "start": round(cursor, 3),
                        "end": round(end, 3),
                        "scene_start": round(cursor - timeline, 3),
                        "scene_end": round(end - timeline, 3),
                    }
                )
                cursor = end
            timeline += span

        write_srt(cues, output)
        return CaptionResult(
            srt_path=output,
            cues=cues,
            provider=self.name,
            technique="script_derived",
        )
