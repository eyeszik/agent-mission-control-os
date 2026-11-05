"""WAV helpers built on the standard library.

Reading duration and writing silence through :mod:`wave` rather than ffmpeg
means audio timing works even on a host where ffmpeg is only available as the
imageio-ffmpeg static binary (which ships no ffprobe).
"""

from __future__ import annotations

import contextlib
import struct
import wave
from pathlib import Path

DEFAULT_SAMPLE_RATE = 22050


def wav_duration(path: str | Path) -> float:
    """Duration of a PCM WAV file in seconds."""
    with contextlib.closing(wave.open(str(path), "rb")) as handle:
        frames = handle.getnframes()
        rate = handle.getframerate() or DEFAULT_SAMPLE_RATE
        return frames / float(rate)


def write_silence(
    path: str | Path,
    duration: float,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = 1,
) -> Path:
    """Write ``duration`` seconds of digital silence."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(round(max(0.0, duration) * sample_rate)))
    with contextlib.closing(wave.open(str(target), "wb")) as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames * channels)
    return target


def pad_wav(path: str | Path, target_duration: float) -> float:
    """Extend a mono 16-bit WAV with trailing silence to ``target_duration``.

    Returns the resulting duration. A file already at or past the target is left
    alone - narration is never truncated to fit a clock.
    """
    source = Path(path)
    with contextlib.closing(wave.open(str(source), "rb")) as handle:
        params = handle.getparams()
        payload = handle.readframes(handle.getnframes())
    current = params.nframes / float(params.framerate or DEFAULT_SAMPLE_RATE)
    if current >= target_duration:
        return current
    extra = int(round((target_duration - current) * params.framerate)) * params.nchannels
    with contextlib.closing(wave.open(str(source), "wb")) as handle:
        handle.setparams(params)
        handle.writeframes(payload + b"\x00" * params.sampwidth * extra)
    return target_duration


def _peak_via_ffmpeg(path: str | Path) -> float:
    """Peak from ffmpeg's ``volumedetect`` for containers the WAV reader cannot open (e.g. AAC in MP4).

    Returns 0.0 when ffmpeg is unavailable, the file has no audio, or the output cannot be parsed.
    """
    import re
    import subprocess

    from .ffmpeg import find_ffmpeg

    binary = find_ffmpeg()
    if not binary:
        return 0.0
    try:
        proc = subprocess.run(
            [binary, "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 0.0
    match = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", proc.stderr)
    if proc.returncode != 0 or not match:
        return 0.0
    return min(1.0, 10 ** (float(match.group(1)) / 20.0))


def peak_amplitude(path: str | Path, max_frames: int = 2_000_000) -> float:
    """Peak sample magnitude in [0, 1].

    16-bit PCM WAV is read directly. Any other readable container (for example the AAC track in
    final.mp4) is measured with ffmpeg's volumedetect. Used by the structural QC gate to catch
    silent or clipped audio. Returns 0.0 when nothing can be measured, rather than guessing.
    """
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as handle:
            if handle.getsampwidth() != 2:
                # Readable WAV at another sample width (24-bit, float, ...): measure it with ffmpeg.
                return _peak_via_ffmpeg(path)
            frames = handle.readframes(min(handle.getnframes(), max_frames))
    except (wave.Error, OSError):
        return _peak_via_ffmpeg(path)
    if not frames:
        return 0.0
    count = len(frames) // 2
    samples = struct.unpack(f"<{count}h", frames[: count * 2])
    return max(abs(min(samples)), abs(max(samples))) / 32768.0
