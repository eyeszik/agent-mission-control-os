"""Piper speech provider (optional, higher quality local neural TTS).

Piper is a free, MIT-licensed, offline neural TTS. FreeVideoForge will use it
when it is already installed with at least one voice, but **never downloads a
voice model on its own**: a voice is a 20-120 MB checkpoint, and pulling one
unprompted is exactly the kind of resource decision that belongs to a human.

Discovery looks for, in order:
  1. ``$FVF_PIPER_MODEL`` pointing at a ``.onnx`` voice.
  2. A ``.onnx`` voice in ``$FVF_PIPER_VOICE_DIR`` or a conventional voice dir.
and a ``piper`` executable on PATH (or the ``piper`` Python module).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

from ..audio import wav_duration
from ..errors import ProviderUnavailable
from ..ffmpeg import run
from .base import Capability, SpeechResult

VOICE_DIRS = (
    "~/.local/share/piper-voices",
    "~/.local/share/piper",
    "~/piper-voices",
    "/usr/share/piper-voices",
    "/opt/piper/voices",
)


def _find_voice() -> Optional[Path]:
    explicit = os.environ.get("FVF_PIPER_MODEL")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    candidates = [os.environ.get("FVF_PIPER_VOICE_DIR", ""), *VOICE_DIRS]
    for raw in candidates:
        if not raw:
            continue
        directory = Path(raw).expanduser()
        if not directory.is_dir():
            continue
        voices = sorted(directory.rglob("*.onnx"))
        if voices:
            return voices[0]
    return None


class PiperSpeechProvider:
    name = "piper"
    kind = "speech"

    def __init__(self, settings=None) -> None:
        self.settings = settings

    @staticmethod
    def _binary() -> Optional[str]:
        return shutil.which("piper")

    def probe(self) -> Capability:
        binary = self._binary()
        voice = _find_voice()
        remediation = (
            "Piper is free and offline (MIT licensed). To enable it:\n"
            "  1. pip install piper-tts\n"
            "  2. Download one voice (~20-120 MB) from the Piper voices release\n"
            "     and point FVF_PIPER_MODEL at the .onnx file.\n"
            "FreeVideoForge will not download a voice model for you."
        )
        if not binary:
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail="The `piper` executable is not on PATH.",
                remediation=remediation, requires_large_download=True,
            )
        if voice is None:
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail="Piper is installed but no .onnx voice model was found.",
                remediation=remediation, requires_large_download=True,
                metadata={"binary": binary},
            )
        return Capability(
            available=True, name=self.name, kind=self.kind,
            detail="Local neural TTS with an installed voice. Offline and free.",
            metadata={"binary": binary, "voice_model": str(voice),
                      "voice_quality": "neural"},
        )

    def synthesize(
        self, text: str, output: Path, *, voice: str = "auto", language: str = "en"
    ) -> SpeechResult:
        binary = self._binary()
        model = Path(voice) if voice not in {"auto", "", None} and Path(voice).is_file() \
            else _find_voice()
        if not binary or model is None:
            raise ProviderUnavailable("Piper is not fully installed on this host")
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        run(
            [binary, "--model", str(model), "--output_file", str(output)],
            stdin_bytes=(text or " ").encode("utf-8"),
            timeout=300.0,
        )
        if not output.exists() or output.stat().st_size == 0:
            raise ProviderUnavailable("Piper produced no audio")
        return SpeechResult(
            path=output, provider=self.name, duration=wav_duration(output),
            voice=model.stem, engine="piper", is_speech=True,
            metadata={"voice_model": str(model), "voice_quality": "neural"},
        )
