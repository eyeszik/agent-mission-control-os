"""CARS integration: capability checks, environment fingerprint, artifact provenance."""

import json
from pathlib import Path

from services.langgraph.agency.capability_assurance import (
    CapabilityResult,
    check_capability,
    check_all,
    environment_fingerprint,
)


def test_capability_result_schema():
    cr = CapabilityResult(capability="webgl", required=True, available=False, health="UNAVAILABLE", reason="NO_WEBGL_CONTEXT")
    d = cr.to_dict()
    assert d["capability"] == "webgl"
    assert d["required"] is True
    assert d["available"] is False
    assert d["health"] == "UNAVAILABLE"
    assert d["reason"] == "NO_WEBGL_CONTEXT"
    assert "checked_at" in d


def test_capability_probes_return_machine_readable_results():
    results = check_all()
    assert "webgl" in results
    assert "ffprobe" in results
    assert "tts" in results
    for name, result in results.items():
        assert "capability" in result
        assert "required" in result
        assert "available" in result
        assert "health" in result
        assert result["health"] in ("VERIFIED", "AVAILABLE_BUT_FAILED", "AVAILABLE_UNVERIFIED", "UNAVAILABLE")


def test_unregistered_capability_is_unavailable():
    result = check_capability("nonexistent-capability-xyz")
    assert result.available is False
    assert result.health == "UNAVAILABLE"
    assert "NO_PROBE" in (result.reason or "")


def test_environment_fingerprint_has_required_fields():
    fp = environment_fingerprint()
    assert "repository_commit" in fp
    assert "operating_system" in fp
    assert "architecture" in fp
    assert "runtime_versions" in fp
    assert "database_engine" in fp
    assert "checked_at" in fp
    # Only applicable fields are required; missing values may be None
    assert isinstance(fp["runtime_versions"], dict)


def test_fingerprint_is_serializable_and_stable_shape():
    fp = environment_fingerprint()
    # Must be JSON serializable
    text = json.dumps(fp)
    reloaded = json.loads(text)
    assert reloaded["operating_system"] == fp["operating_system"]


def test_ffprobe_capability_reports_remediation():
    result = check_capability("ffprobe")
    if not result.available:
        assert result.remediation is not None
        assert "ffmpeg" in result.remediation.lower()
    else:
        assert result.health in ("VERIFIED", "AVAILABLE_UNVERIFIED")


def test_tts_capability_distinguishes_unavailable_vs_verified():
    result = check_capability("tts")
    # On this host espeak may or may not be installed; either state is valid, but must be explicit
    assert result.health in ("VERIFIED", "UNAVAILABLE")
    if result.health == "UNAVAILABLE":
        assert result.reason is not None
