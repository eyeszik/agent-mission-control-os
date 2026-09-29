"""FFmpeg/FFprobe discovery and safe invocation.

Discovery order for each binary:

1. An explicit override (``FVF_FFMPEG`` / ``FVF_FFPROBE`` or ``Settings``).
2. The system ``PATH``.
3. The static binary bundled by the optional ``imageio-ffmpeg`` wheel
   (ffmpeg only - that wheel does not ship ffprobe).

Every invocation goes through :func:`run` which uses an argument list and never
``shell=True``, so no user-derived string is ever interpreted by a shell.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Sequence

from .errors import DependencyError, RenderError

FFMPEG_INSTALL_HINT = (
    "Install FFmpeg with one of:\n"
    "  * Debian/Ubuntu : sudo apt-get install -y ffmpeg\n"
    "  * macOS         : brew install ffmpeg\n"
    "  * Windows       : winget install Gyan.FFmpeg\n"
    "  * Any platform  : pip install imageio-ffmpeg   (ffmpeg only, no ffprobe)\n"
    "Or point FVF_FFMPEG / FVF_FFPROBE at existing binaries."
)


@lru_cache(maxsize=1)
def _imageio_ffmpeg() -> Optional[str]:
    """Return the static ffmpeg shipped by imageio-ffmpeg, if installed."""
    try:
        import imageio_ffmpeg  # type: ignore
    except Exception:
        return None
    try:
        path = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    return path if path and Path(path).exists() else None


def find_ffmpeg(override: str | None = None) -> Optional[str]:
    for candidate in (override, os.environ.get("FVF_FFMPEG"), shutil.which("ffmpeg")):
        if candidate and Path(candidate).exists():
            return str(candidate)
    return _imageio_ffmpeg()


def find_ffprobe(override: str | None = None) -> Optional[str]:
    for candidate in (override, os.environ.get("FVF_FFPROBE"), shutil.which("ffprobe")):
        if candidate and Path(candidate).exists():
            return str(candidate)
    # imageio-ffmpeg does not bundle ffprobe; a sibling of a real ffmpeg often is.
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
        if sibling.exists():
            return str(sibling)
    return None


def run(
    argv: Sequence[str],
    *,
    stdin_bytes: bytes | None = None,
    timeout: float | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command from an argv list. Never uses a shell."""
    if not argv or not argv[0]:
        raise DependencyError("Refusing to execute an empty command")
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, shell=False, no user string eval
            list(argv),
            input=stdin_bytes,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DependencyError(f"Executable not found: {argv[0]}\n{FFMPEG_INSTALL_HINT}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"{Path(argv[0]).name} timed out after {timeout}s") from exc
    if check and proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-25:]
        raise RenderError(
            f"{Path(argv[0]).name} exited {proc.returncode}\n" + "\n".join(tail)
        )
    return proc


# --------------------------------------------------------------------------
# Probe results
# --------------------------------------------------------------------------


@dataclass
class StreamInfo:
    codec_type: str
    codec_name: str
    width: Optional[int] = None
    height: Optional[int] = None
    avg_frame_rate: Optional[float] = None
    duration: Optional[float] = None
    channels: Optional[int] = None
    sample_rate: Optional[int] = None
    nb_frames: Optional[int] = None


@dataclass
class ProbeResult:
    """Structured, vendor-neutral ffprobe output."""

    path: str
    format_name: str
    duration: float
    size_bytes: int
    streams: list[StreamInfo]
    raw: dict[str, Any]

    @property
    def video(self) -> Optional[StreamInfo]:
        return next((s for s in self.streams if s.codec_type == "video"), None)

    @property
    def audio(self) -> Optional[StreamInfo]:
        return next((s for s in self.streams if s.codec_type == "audio"), None)

    @property
    def has_video(self) -> bool:
        return self.video is not None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _frame_rate(value: Any) -> Optional[float]:
    if not value or not isinstance(value, str) or "/" not in value:
        return _as_float(value)
    num, _, den = value.partition("/")
    numerator, denominator = _as_float(num), _as_float(den)
    if numerator is None or not denominator:
        return None
    return numerator / denominator


class FFTools:
    """Bound pair of ffmpeg/ffprobe executables plus capability probing."""

    def __init__(self, ffmpeg: str | None = None, ffprobe: str | None = None) -> None:
        self.ffmpeg = find_ffmpeg(ffmpeg)
        self.ffprobe = find_ffprobe(ffprobe)
        self._filter_cache: frozenset[str] | None = None

    # -- availability ----------------------------------------------------
    @property
    def available(self) -> bool:
        return bool(self.ffmpeg)

    def require_ffmpeg(self) -> str:
        if not self.ffmpeg:
            raise DependencyError("ffmpeg was not found.\n" + FFMPEG_INSTALL_HINT)
        return self.ffmpeg

    def require_ffprobe(self) -> str:
        if not self.ffprobe:
            raise DependencyError("ffprobe was not found.\n" + FFMPEG_INSTALL_HINT)
        return self.ffprobe

    def version(self, which: str = "ffmpeg") -> Optional[str]:
        binary = self.ffmpeg if which == "ffmpeg" else self.ffprobe
        if not binary:
            return None
        try:
            proc = run([binary, "-hide_banner", "-version"], check=False)
        except DependencyError:
            return None
        lines = (proc.stdout or b"").decode("utf-8", "replace").splitlines()
        if not lines:
            return None
        # "ffmpeg version 6.1.1-3ubuntu5 Copyright (c) ..." -> "6.1.1-3ubuntu5"
        parts = lines[0].split()
        if len(parts) >= 3 and parts[1] == "version":
            return parts[2]
        return lines[0].strip()

    def _filters(self) -> frozenset[str]:
        # Cached per instance: lru_cache on a method would pin instances alive
        # and thrash across differently-configured FFTools objects.
        if self._filter_cache is not None:
            return self._filter_cache
        if not self.ffmpeg:
            self._filter_cache = frozenset()
            return self._filter_cache
        proc = run([self.ffmpeg, "-hide_banner", "-filters"], check=False)
        names: set[str] = set()
        for line in (proc.stdout or b"").decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] and not parts[0].startswith("-"):
                names.add(parts[1])
        self._filter_cache = frozenset(names)
        return self._filter_cache

    def has_filter(self, name: str) -> bool:
        return name in self._filters()

    def has_encoder(self, name: str) -> bool:
        if not self.ffmpeg:
            return False
        proc = run([self.ffmpeg, "-hide_banner", "-encoders"], check=False)
        return f" {name} " in (proc.stdout or b"").decode("utf-8", "replace")

    # -- probing ---------------------------------------------------------
    def probe(self, path: str | Path) -> ProbeResult:
        """Return structured stream/format info, or raise RenderError."""
        probe_bin = self.require_ffprobe()
        target = Path(path)
        if not target.exists():
            raise RenderError(f"Cannot probe missing file: {target}")
        proc = run(
            [
                probe_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(target),
            ]
        )
        try:
            data = json.loads((proc.stdout or b"{}").decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise RenderError(f"ffprobe returned invalid JSON for {target}") from exc
        fmt = data.get("format", {}) or {}
        streams = [
            StreamInfo(
                codec_type=s.get("codec_type", "unknown"),
                codec_name=s.get("codec_name", "unknown"),
                width=_as_int(s.get("width")),
                height=_as_int(s.get("height")),
                avg_frame_rate=_frame_rate(s.get("avg_frame_rate")),
                duration=_as_float(s.get("duration")) or _as_float(fmt.get("duration")),
                channels=_as_int(s.get("channels")),
                sample_rate=_as_int(s.get("sample_rate")),
                nb_frames=_as_int(s.get("nb_frames")),
            )
            for s in data.get("streams", []) or []
        ]
        return ProbeResult(
            path=str(target),
            format_name=fmt.get("format_name", "unknown"),
            duration=_as_float(fmt.get("duration")) or 0.0,
            size_bytes=_as_int(fmt.get("size")) or target.stat().st_size,
            streams=streams,
            raw=data,
        )

    def duration(self, path: str | Path) -> float:
        """Duration in seconds. Falls back to a decode pass when metadata lies."""
        result = self.probe(path)
        if result.duration > 0:
            return result.duration
        stream = result.video or result.audio
        return float(stream.duration or 0.0) if stream else 0.0

    def decodes(self, path: str | Path, timeout: float = 300.0) -> tuple[bool, str]:
        """Fully decode a file to /dev/null. This is what catches a provider
        that reported success while writing structurally invalid media (E13)."""
        try:
            proc = run(
                [
                    self.require_ffmpeg(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-xerror",
                    "-i",
                    str(path),
                    "-f",
                    "null",
                    "-",
                ],
                timeout=timeout,
                check=False,
            )
        except (DependencyError, RenderError) as exc:
            return False, str(exc)
        stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
        # A non-zero exit is conclusive, but H.264 conceals a lot of damage and
        # still exits 0. At -loglevel error any output at all means the decoder
        # hit something it had to paper over, which is exactly the "provider
        # reported success but wrote invalid media" case this guards against.
        return proc.returncode == 0 and not stderr, stderr

    def encode_from_rgb_stream(
        self,
        *,
        width: int,
        height: int,
        fps: int,
        output: Path,
        crf: int = 20,
        preset: str = "medium",
        pix_fmt: str = "yuv420p",
        codec: str = "libx264",
    ) -> subprocess.Popen:
        """Open ffmpeg reading raw RGB24 frames on stdin.

        Frames are streamed rather than written to disk as PNGs, which keeps
        temp storage bounded for long renders.
        """
        output.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            self.require_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            str(fps),
            "-i",
            "-",
            "-an",
            "-c:v",
            codec,
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            pix_fmt,
            "-movflags",
            "+faststart",
            str(output),
        ]
        return subprocess.Popen(  # noqa: S603 - argv list, shell=False
            argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )


@lru_cache(maxsize=4)
def default_tools() -> FFTools:
    return FFTools()
