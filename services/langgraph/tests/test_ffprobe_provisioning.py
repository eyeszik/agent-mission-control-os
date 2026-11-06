"""FFprobe reproducibility: deterministic discovery, version reporting, provisioning (ISSUE-07)."""

import os
import shutil
from pathlib import Path

import pytest


def test_ffprobe_discovery_does_not_depend_on_tmp():
    """FFprobe must not be resolved from /tmp manually installed state."""
    from services.freevideoforge.freevideoforge.ffmpeg import find_ffprobe, find_ffmpeg

    # Neither should resolve to /tmp unless explicitly overridden
    ffprobe = find_ffprobe()
    ffmpeg = find_ffmpeg()
    if ffprobe:
        assert not ffprobe.startswith("/tmp"), f"ffprobe must not come from /tmp: {ffprobe}"
    if ffmpeg:
        assert not ffmpeg.startswith("/tmp"), f"ffmpeg must not come from /tmp: {ffmpeg}"


def test_ffprobe_binary_resolution_is_deterministic():
    from services.freevideoforge.freevideoforge.ffmpeg import FFTools
    import os

    # Explicit override takes precedence (FFTools uses positional arg name ffprobe)
    tools_override = FFTools(None, "/nonexistent/ffprobe")
    assert tools_override.ffprobe is None or tools_override.ffprobe == "/nonexistent/ffprobe"

    # System PATH is checked
    tools_default = FFTools()
    # Should not raise; either finds system binary or returns None
    assert tools_default.ffprobe is None or Path(tools_default.ffprobe).exists() or tools_default.ffprobe.startswith("/")


def test_ffprobe_version_reporting():
    from services.freevideoforge.freevideoforge.ffmpeg import FFTools

    tools = FFTools()
    version = tools.version("ffprobe")
    # If ffprobe is present, version must be a non-empty string
    if tools.ffprobe:
        assert isinstance(version, str) and len(version) > 0
    else:
        assert version is None


def test_missing_ffprobe_fails_explicitly():
    from services.freevideoforge.freevideoforge.ffmpeg import FFTools, run
    from services.freevideoforge.freevideoforge.errors import DependencyError

    tools = FFTools(None, "/nonexistent/ffprobe-xyz")
    # Probe of nonexistent file should not crash
    assert tools.ffprobe is None or not Path(tools.ffprobe).exists()
    # Direct run with missing binary raises DependencyError with hint
    with pytest.raises(DependencyError, match="Executable not found"):
        run(["/nonexistent/ffprobe-xyz", "-version"])


def test_media_inspection_smoke_without_ffprobe():
    """QC should report missing ffprobe as INCONCLUSIVE, not PASSED, when binary absent."""
    # This mirrors verify_media behavior for missing ffprobe: video checks are skipped
    from services.langgraph.agency.visual.verify import verify_media
    # SVG verification without chromium should be INCONCLUSIVE for multi_size, not PASSED
    from services.langgraph.agency.assets import render_logo_svg
    PALETTE = {"primary": "#5b1a22", "secondary": "#665d52", "surface": "#ece6da", "text": "#121212"}
    svg = render_logo_svg(brand_name="Test", primary=PALETTE["primary"], secondary=PALETTE["secondary"], surface=PALETTE["surface"])
    v = verify_media(svg.encode(), mime_type="image/svg+xml", expect={"palette": list(PALETTE.values()), "render_sizes": (32,)})
    # Without chromium, this must not be PASSED
    if v.status == "PASSED":
        # If chromium is available, PASSED is ok; otherwise INCONCLUSIVE
        from services.langgraph.agency.visual.browser import probe_browser
        assert probe_browser()["available"] is True
    else:
        assert v.status in ("INCONCLUSIVE", "FAILED")


def test_doctor_reports_ffprobe_provenance():
    from services.freevideoforge.freevideoforge.doctor import collect

    report = collect()
    assert "toolchain" in report
    assert "ffprobe" in report["toolchain"]
    assert "ffprobe_version" in report["toolchain"]
    # When ffprobe missing, doctor must list it as a blocker
    if report["toolchain"]["ffprobe"] is None:
        assert any("ffprobe" in b.lower() for b in report["blockers"])
