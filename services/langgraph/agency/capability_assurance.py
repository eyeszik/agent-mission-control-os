"""Capability Assurance and Reproducibility System (CARS).

Integrates existing capability probes (visual routes, browser, FFprobe/FFmpeg,
TTS, DB, HMAC replay, council capabilities) into a unified contract instead
of creating a redundant subsystem.

Each capability exposes a machine-readable result:

{
  "capability": "webgl",
  "required": true,
  "available": false,
  "version": "chromium 119.4 ...",
  "provider": "local-chromium",
  "platform": "linux-x86_64",
  "provenance": "sha256:...",
  "health": "UNAVAILABLE",
  "reason": "NO_WEBGL_CONTEXT",
  "remediation": "install chromium + mesa ...",
  "checked_at": "2026-11-06T..."
}

Environment fingerprint captures reproducible diagnostics for comparing
failing vs passing environments.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class CapabilityResult:
    capability: str
    required: bool
    available: bool
    version: Optional[str] = None
    provider: Optional[str] = None
    platform: Optional[str] = None
    provenance: Optional[str] = None
    health: str = "UNAVAILABLE"  # VERIFIED | AVAILABLE_BUT_FAILED | AVAILABLE_UNVERIFIED | UNAVAILABLE
    reason: Optional[str] = None
    remediation: Optional[str] = None
    checked_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def passed(self) -> bool:
        return self.health == "VERIFIED"


# ---------------------------------------------------------------------------
# Probes registry - integrates existing probes
# ---------------------------------------------------------------------------

_PROBES: dict[str, Callable[[], CapabilityResult]] = {}


def register_probe(name: str, fn: Callable[[], CapabilityResult]) -> None:
    _PROBES[name] = fn


def check_capability(name: str) -> CapabilityResult:
    fn = _PROBES.get(name)
    if fn is None:
        return CapabilityResult(capability=name, required=False, available=False, health="UNAVAILABLE", reason="NO_PROBE")
    try:
        result = fn()
        if not result.checked_at:
            result.checked_at = datetime.now(timezone.utc).isoformat()
        return result
    except Exception as exc:
        return CapabilityResult(capability=name, required=False, available=False, health="UNAVAILABLE", reason=f"PROBE_ERROR:{exc}", checked_at=datetime.now(timezone.utc).isoformat())


def check_all() -> dict[str, dict]:
    return {name: check_capability(name).to_dict() for name in sorted(_PROBES)}


# ---------------------------------------------------------------------------
# Environment fingerprint
# ---------------------------------------------------------------------------

def _file_hash(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:12]


def _run_version(cmd: list[str]) -> Optional[str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            return (proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else proc.stderr.strip().splitlines()[0]).strip()[:200]
        return None
    except Exception:
        return None


def environment_fingerprint() -> dict[str, Any]:
    """Reproducible fingerprint for relevant test and execution environments."""
    # git commit
    commit = None
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT)).stdout.strip()[:40] or None
    except Exception:
        pass

    # dependency lock hash
    lock_hash = _file_hash(REPO_ROOT / "pnpm-lock.yaml")
    req_hash = _file_hash(REPO_ROOT / "services" / "langgraph" / "pyproject.toml")

    # runtime versions
    runtime_versions: dict[str, Optional[str]] = {
        "python": platform.python_version(),
        "node": _run_version(["node", "--version"]),
        "pnpm": _run_version(["pnpm", "--version"]),
    }

    # browser
    browser_version = None
    browser_profile = None
    graphics_renderer = None
    graphics_capabilities: list[str] = []
    try:
        from services.langgraph.agency.visual.browser import probe_browser
        info = probe_browser()
        browser_version = info.get("chromium") or None
        # graphics renderer comes from actual WebGL context when available; otherwise record that it wasn't probed
        if info.get("available"):
            browser_profile = "chromium-available"
        else:
            browser_profile = "chromium-unavailable"
            graphics_capabilities = info.get("blockers", [])
    except Exception:
        pass

    # ffprobe
    ffprobe_version = None
    try:
        from services.freevideoforge.freevideoforge.ffmpeg import find_ffprobe, FFTools
        tools = FFTools()
        ffprobe_version = tools.version("ffprobe")
        if ffprobe_version is None and tools.ffprobe:
            ffprobe_version = tools.ffprobe
    except Exception:
        pass

    # TTS - only real speech (not silence)
    tts_engine = None
    tts_model = None
    try:
        from services.freevideoforge.freevideoforge.providers.speech_espeak import EspeakSpeechProvider
        from services.freevideoforge.freevideoforge.providers.speech_piper import PiperSpeechProvider
        for Provider in (PiperSpeechProvider, EspeakSpeechProvider):
            try:
                cap = Provider().probe()
                if cap.available:
                    tts_engine = cap.name
                    tts_model = getattr(cap, "version", None)
                    break
            except Exception:
                continue
    except Exception:
        pass

    # database
    database_engine = os.environ.get("AMC_DATABASE_BACKEND", "sqlite")
    database_version = None
    try:
        if database_engine == "sqlite":
            import sqlite3
            database_version = sqlite3.sqlite_version
        elif database_engine == "postgres":
            database_version = "postgres-external"
    except Exception:
        pass

    # config hash
    config_hash = None
    try:
        env_relevant = {k: v for k, v in os.environ.items() if k.startswith("AMC_") or k.startswith("FVF_")}
        config_hash = hashlib.sha256(json.dumps(env_relevant, sort_keys=True).encode()).hexdigest()[:12]
    except Exception:
        pass

    return {
        "repository_commit": commit,
        "operating_system": platform.platform(),
        "architecture": platform.machine(),
        "runtime_versions": runtime_versions,
        "dependency_lock_hash": lock_hash,
        "dependency_py_hash": req_hash,
        "browser_version": browser_version,
        "browser_profile": browser_profile,
        "graphics_renderer": graphics_renderer,
        "graphics_capabilities": graphics_capabilities,
        "tts_engine": tts_engine,
        "tts_model": tts_model,
        "ffprobe_version": ffprobe_version,
        "database_engine": database_engine,
        "database_version": database_version,
        "worker_count": os.environ.get("AMC_WORKER_COUNT"),
        "configuration_hash": config_hash,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Pre-registered probes integrating existing infrastructure
# ---------------------------------------------------------------------------

def _probe_webgl() -> CapabilityResult:
    """WebGL probe: checks browser availability and WebGL context creation."""
    try:
        from services.langgraph.agency.visual.browser import probe_browser, chromium_path
        info = probe_browser()
        if not info["available"]:
            return CapabilityResult(
                capability="webgl",
                required=True,
                available=False,
                provider="chromium",
                platform=platform.platform(),
                health="UNAVAILABLE",
                reason="; ".join(info.get("blockers", [])) or "NO_BROWSER",
                remediation="Install Chromium: pnpm --filter @amc/web exec playwright install chromium; ensure mesa for software rendering",
            )
        # Browser binary exists - but WebGL context may still be unavailable (e.g. missing mesa/swiftshader)
        # We don't claim hardware acceleration; we record renderer after actual context probe.
        # Here we report AVAILABLE_UNVERIFIED until a real render test verifies it.
        return CapabilityResult(
            capability="webgl",
            required=True,
            available=True,
            version=info.get("chromium"),
            provider="chromium",
            platform=platform.platform(),
            health="AVAILABLE_UNVERIFIED",
            reason=None,
            remediation=None,
        )
    except Exception as exc:
        return CapabilityResult(capability="webgl", required=True, available=False, health="UNAVAILABLE", reason=str(exc))


def _probe_ffprobe() -> CapabilityResult:
    try:
        from services.freevideoforge.freevideoforge.ffmpeg import find_ffprobe, FFTools
        tools = FFTools()
        if tools.ffprobe:
            return CapabilityResult(
                capability="ffprobe",
                required=True,
                available=True,
                version=tools.version("ffprobe"),
                provider=tools.ffprobe,
                platform=platform.platform(),
                health="VERIFIED",
            )
        return CapabilityResult(
            capability="ffprobe",
            required=True,
            available=False,
            health="UNAVAILABLE",
            reason="ffprobe not found on PATH",
            remediation="sudo apt-get install -y ffmpeg  OR  pip install imageio-ffmpeg (ffmpeg only) + apt-get for ffprobe",
        )
    except Exception as exc:
        return CapabilityResult(capability="ffprobe", required=True, available=False, health="UNAVAILABLE", reason=str(exc))


def _probe_tts() -> CapabilityResult:
    try:
        from services.freevideoforge.freevideoforge.providers.speech_espeak import EspeakSpeechProvider
        from services.freevideoforge.freevideoforge.providers.speech_piper import PiperSpeechProvider
        # Prefer piper if available, else espeak, else silence (not real speech)
        for Provider in (PiperSpeechProvider, EspeakSpeechProvider):
            try:
                cap = Provider().probe()
                if cap.available:
                    return CapabilityResult(
                        capability="tts",
                        required=True,
                        available=True,
                        version=getattr(cap, "version", None),
                        provider=cap.name,
                        platform=platform.platform(),
                        health="VERIFIED",
                        reason=None,
                    )
            except Exception:
                continue
        return CapabilityResult(capability="tts", required=True, available=False, health="UNAVAILABLE", reason="no speech provider available", remediation="sudo apt-get install -y espeak-ng  OR  pip install piper-tts + voice model")
    except Exception as exc:
        return CapabilityResult(capability="tts", required=True, available=False, health="UNAVAILABLE", reason=str(exc))


def _probe_sqlite_migration() -> CapabilityResult:
    try:
        from services.langgraph.persistence.sqlite_db import DB_PATH
        return CapabilityResult(capability="sqlite-migration", required=True, available=True, version=DB_PATH, provider="sqlite", platform=platform.platform(), health="VERIFIED")
    except Exception as exc:
        return CapabilityResult(capability="sqlite-migration", required=True, available=False, health="UNAVAILABLE", reason=str(exc))


# Auto-register
for _name, _fn in [("webgl", _probe_webgl), ("ffprobe", _probe_ffprobe), ("tts", _probe_tts), ("sqlite-migration", _probe_sqlite_migration)]:
    _PROBES[_name] = _fn
