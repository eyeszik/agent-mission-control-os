"""Integrity pins catch changed bytes and removal of the new production boundaries.

The manifest is a drift detector, not a signature or an independent security review.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from scripts import verify_manifest

ROOT = Path(__file__).resolve().parents[3]
REQUIRED = (
    "services/langgraph/security/replay_store.py",
    "services/langgraph/agency/delivery/crg.py",
    "services/langgraph/agency/ucpo/brand_web.py",
    "services/langgraph/agency/ucpo/brand_web_contracts.py",
    "services/langgraph/agency/ucpo/contracts.py",
    "services/langgraph/agency/ucpo/requirements.py",
    "services/langgraph/agency/ucpo/semantic.py",
    "services/langgraph/agency/visual/file_staging.py",
    "services/langgraph/agency/vnexus/timeline_render.py",
    "services/langgraph/agency/vnexus/twin.py",
    "services/langgraph/agency/vnexus/video.py",
    "services/langgraph/tests/test_vnexus_cross_project_replay.py",
    "services/langgraph/tests/test_vnexus_project_source_authorization.py",
    "services/langgraph/tests/test_vnexus_replay_authorization.py",
    "scripts/verify_northline_bundle.py",
)


def test_manifest_rejects_boundary_drift_and_missing_required_pins(tmp_path, monkeypatch):
    payload = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for entry in payload["files"]:
        target = tmp_path / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / entry["path"], target)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(verify_manifest, "ROOT", tmp_path)
    monkeypatch.setattr(verify_manifest, "MANIFEST", manifest)
    verify_manifest.main()

    boundary = tmp_path / REQUIRED[2]
    original = boundary.read_bytes()
    boundary.write_bytes(original + b"\n# synthetic drift\n")
    with pytest.raises(SystemExit, match="manifest drift"):
        verify_manifest.main()
    boundary.write_bytes(original)

    # Removing a pin must not make the affected trust boundary silently pass.
    for name in REQUIRED:
        reduced = {**payload, "files": [entry for entry in payload["files"] if entry["path"] != name]}
        manifest.write_text(json.dumps(reduced), encoding="utf-8")
        with pytest.raises(SystemExit, match="manifest missing critical files") as error:
            verify_manifest.main()
        assert name in str(error.value)
