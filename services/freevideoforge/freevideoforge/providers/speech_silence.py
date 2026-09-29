"""Timed-silence speech provider.

This is the floor that makes the ``local_tts`` contract honest on a host with
no speech engine at all: it produces a correctly timed silent track so scene
durations, caption timing and the final mux stay exact, and it reports
``is_speech=False`` so nothing downstream can claim narration was produced.

It is always available and has zero dependencies.
"""

from __future__ import annotations

from pathlib import Path

from ..audio import DEFAULT_SAMPLE_RATE, write_silence
from .base import Capability, SpeechResult

#: Speaking rate used to size silence for a given line of text.
WORDS_PER_SECOND = 2.45


class SilenceSpeechProvider:
    name = "silence"
    kind = "speech"

    def __init__(self, settings=None) -> None:
        self.settings = settings

    def probe(self) -> Capability:
        return Capability(
            available=True,
            name=self.name,
            kind=self.kind,
            detail=(
                "Timed silence. Always available; produces no narration. "
                "Install a local TTS engine for real voiceover."
            ),
            remediation=(
                "Free local speech engines:\n"
                "  * espeak-ng : sudo apt-get install espeak-ng | brew install espeak-ng\n"
                "  * Piper     : pip install piper-tts, then download one ONNX voice"
            ),
            version="1.0.0",
        )

    def synthesize(
        self, text: str, output: Path, *, voice: str = "auto", language: str = "en"
    ) -> SpeechResult:
        words = len((text or "").split())
        duration = max(0.6, words / WORDS_PER_SECOND + 0.4)
        write_silence(output, duration, sample_rate=DEFAULT_SAMPLE_RATE)
        return SpeechResult(
            path=Path(output),
            provider=self.name,
            duration=duration,
            voice="none",
            engine="silence",
            is_speech=False,
            metadata={"estimated_from": "word_count", "words": words},
        )
