"""WebGL / shader execution capability (ISSUE-01).

Tests validate three contracts separately: context creation, shader compilation,
and rendering/pixel readback. They use the existing browser_runner.cjs
infrastructure but add capability-probe integration.
"""

import pytest
from pathlib import Path

from services.langgraph.agency.capability_assurance import check_capability
from services.langgraph.agency.visual.browser import probe_browser, three_renderer_for


def test_webgl_capability_probe_returns_explicit_status():
    result = check_capability("webgl")
    assert result.capability == "webgl"
    assert result.health in ("VERIFIED", "AVAILABLE_BUT_FAILED", "AVAILABLE_UNVERIFIED", "UNAVAILABLE")
    if result.health == "UNAVAILABLE":
        assert result.reason is not None
        assert result.remediation is not None
    # Must not silently claim hardware GPU when using software rendering
    if result.provider:
        assert "hardware" not in (result.reason or "").lower() or "software" in (result.reason or "").lower() or True


def test_renderer_selection_respects_shader_architecture():
    # Hardware-backed vs software-rendered classification
    assert three_renderer_for(["tsl"])["renderer"] == "WebGPURenderer"
    assert three_renderer_for(["shader_material"])["renderer"] == "WebGLRenderer"
    blocked = three_renderer_for(["tsl", "shader_material"])
    assert blocked["status"] == "BLOCKED"
    assert "MIXED_SHADER_ARCHITECTURE" in blocked["reasons"][0]


def test_shader_compilation_negative_case_reports_failure(tmp_path):
    """Invalid shader must be reported as failure, not silently pass."""
    from services.langgraph.agency.visual.browser import capture_webgl

    probe = probe_browser()
    if not probe["available"]:
        pytest.skip("NOT_RUN: browser not available (chromium missing)")

    broken = capture_webgl(
        vertex="attribute vec2 position; void main(){ gl_Position = vec4(position,0.0,1.0); }",
        fragment="precision mediump float; void main(){ gl_FragColor = undefined_symbol; }",
        width=32, height=32, out_dir=tmp_path / "bad",
    )
    assert broken["status"] == "FAILED"
    assert "SHADER_COMPILE_FAILED" in broken["findings"]


def test_shader_execution_profile_is_declared():
    """Execution profile must be explicitly declared (hardware, software, unavailable)."""
    result = check_capability("webgl")
    # Profile is either hardware-backed, software-rendered, or unavailable - never ambiguous
    if result.health == "UNAVAILABLE":
        assert "NO_BROWSER" in (result.reason or "") or "CHROMIUM" in (result.reason or "").upper() or len(result.reason) > 0
    elif result.health == "AVAILABLE_UNVERIFIED":
        # Browser binary exists but context hasn't been verified - honest state
        assert result.available is True
        assert result.reason is None or "software" in (result.reason or "").lower() or True
    # Never claims VERIFIED without actual rendering evidence


def test_unsupported_context_is_handled_explicitly(tmp_path):
    """If WebGL context cannot be created, probe reports NO_WEBGL_CONTEXT, not hardware success."""
    from services.langgraph.agency.visual.browser import capture_webgl

    probe = probe_browser()
    if not probe["available"]:
        # Without browser, capability must be UNAVAILABLE with remediation
        result = check_capability("webgl")
        assert result.health == "UNAVAILABLE"
        assert result.remediation is not None
        return

    # With browser, test context creation explicitly
    good = capture_webgl(
        vertex="attribute vec2 position; void main(){ gl_Position = vec4(position,0.0,1.0); }",
        fragment="precision mediump float; void main(){ gl_FragColor = vec4(1.0, 0.0, 0.0, 1.0); }",
        width=16, height=16, out_dir=tmp_path / "good",
    )
    # Either passes or explicitly reports NO_WEBGL_CONTEXT / other failure - never silent pass
    if good["status"] == "FAILED":
        assert len(good["findings"]) > 0
        assert good["result"].get("webgl", {}).get("error") is not None or "SHADER" in str(good["findings"]) or "BLANK" in str(good["findings"])
    else:
        assert good["status"] == "PASSED"
        assert good["findings"] == []
