"""espeak-ng speech provider.

espeak-ng is a free, offline, formant-synthesis engine packaged for every major
platform. It is not a neural voice and this provider does not pretend it is -
``metadata['voice_quality']`` says ``formant_synthesis`` - but it is genuine
local speech with zero cost, zero credentials and no model download.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..audio import wav_duration
from ..errors import ProviderUnavailable
from ..ffmpeg import run
from .base import Capability, SpeechResult

#: Words per minute passed to espeak-ng. Slower than the 175 default because
#: the default is noticeably rushed under burned-in captions.
DEFAULT_RATE_WPM = 160

#: Language code -> espeak-ng voice.
VOICE_MAP = {
    "en": "en-us",
    "en-gb": "en-gb",
    "es": "es",
    "fr": "fr-fr",
    "de": "de",
    "it": "it",
    "pt": "pt",
    "nl": "nl",
    "pl": "pl",
    "ru": "ru",
}


class EspeakSpeechProvider:
    name = "espeak"
    kind = "speech"

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self._binary: str | None = None

    def _find(self) -> str | None:
        if self._binary is None:
            self._binary = shutil.which("espeak-ng") or shutil.which("espeak") or ""
        return self._binary or None

    def probe(self) -> Capability:
        binary = self._find()
        if not binary:
            return Capability(
                available=False,
                name=self.name,
                kind=self.kind,
                detail="espeak-ng is not on PATH.",
                remediation=(
                    "Install it (free, offline, no account):\n"
                    "  Debian/Ubuntu : sudo apt-get install -y espeak-ng\n"
                    "  macOS         : brew install espeak-ng\n"
                    "  Windows       : winget install eSpeak-NG.eSpeak-NG"
                ),
            )
        version = None
        try:
            proc = run([binary, "--version"], check=False)
            version = (proc.stdout or b"").decode("utf-8", "replace").strip().splitlines()
            version = version[0] if version else None
        except Exception:  # a broken binary must not break discovery
            pass
        return Capability(
            available=True,
            name=self.name,
            kind=self.kind,
            detail="Local formant-synthesis TTS. Offline, free, no model download.",
            version=version,
            metadata={"binary": binary, "voice_quality": "formant_synthesis"},
        )

    def synthesize(
        self, text: str, output: Path, *, voice: str = "auto", language: str = "en"
    ) -> SpeechResult:
        binary = self._find()
        if not binary:
            raise ProviderUnavailable("espeak-ng is not available")
        resolved = VOICE_MAP.get(language, "en-us") if voice in {"auto", "", None} else voice
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        # argv list: the narration text is an argument, never shell input.
        run(
            [
                binary,
                "-v", resolved,
                "-s", str(DEFAULT_RATE_WPM),
                "-p", "42",          # slightly lower pitch reads as less shrill
                "-g", "4",           # a little word gap for caption readability
                "-w", str(output),
                text or " ",
            ],
            timeout=120.0,
        )
        if not output.exists() or output.stat().st_size == 0:
            raise ProviderUnavailable("espeak-ng produced no audio")
        return SpeechResult(
            path=output,
            provider=self.name,
            duration=wav_duration(output),
            voice=resolved,
            engine="espeak-ng",
            is_speech=True,
            metadata={"rate_wpm": DEFAULT_RATE_WPM, "voice_quality": "formant_synthesis"},
        )
