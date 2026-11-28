"""Offline refusal tests; fictional voice bytes never establish render readiness."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest


PACKAGE = Path(__file__).resolve().parents[3] / "artifacts/amc-explainer"
VOICE = "en_US-joe-medium.onnx"


def _voice_record(model: Path) -> dict:
    return {"voice_models": {
        name: {"bytes": path.stat().st_size,
               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for name, path in [(VOICE, model), (VOICE + ".json", Path(str(model) + ".json"))]
    }}


def _python_shim(root: Path) -> None:
    executable = root / ".venv/bin/python"
    executable.parent.mkdir(parents=True)
    executable.write_text(
        "#!/bin/sh\nif [ \"$1\" = '-m' ]; then\n"
        f"  printf '%s\\n' \"$@\" > {shlex.quote(str(root / 'render-called'))}\n"
        "  exit 0\nfi\n"
        f"exec {shlex.quote(sys.executable)} \"$@\"\n"
    )
    executable.chmod(0o700)


@pytest.fixture
def recipe(tmp_path: Path) -> dict:
    root = tmp_path / "fixture-repository"
    package = root / "artifacts/amc-explainer"
    (package / "source").mkdir(parents=True)
    shutil.copy2(PACKAGE / "source/generate.sh", package / "source/generate.sh")
    if (PACKAGE / "tools/verify_voice.py").exists():
        (package / "tools").mkdir()
        shutil.copy2(PACKAGE / "tools/verify_voice.py", package / "tools/verify_voice.py")
    model = tmp_path / VOICE
    model.write_bytes(b"Fictional fixture model, never used for inference.")
    Path(str(model) + ".json").write_bytes(b'{"fixture": true}')
    (package / "environment-record.json").write_text(json.dumps(_voice_record(model)))
    (package / "source/brief.txt").write_text("Fictional fixture brief.")
    _python_shim(root)
    return {"root": root, "package": package, "model": model}


def _run(recipe: dict, *, explicit: bool = True, outside: bool = False):
    root, model = recipe["root"], recipe["model"]
    trap = root / "untrusted-package"
    trap.mkdir(exist_ok=True)
    marker = root / "untrusted-import"
    (trap / "joe_us_piper_voice.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        f"def model_path(): return {str(model)!r}\n"
    )
    env = {"PATH": os.defpath, "PYTHONPATH": str(trap), "PYTHONNOUSERSITE": "1"}
    if explicit:
        env["FVF_PIPER_MODEL"] = str(model)
    return subprocess.run(
        ["/bin/sh", str(recipe["package"] / "source/generate.sh")],
        cwd=root.parent if outside else root, env=env, capture_output=True,
        text=True, timeout=10,
    )


@pytest.mark.parametrize("sidecar", [False, True])
def test_recipe_refuses_changed_voice_bytes_before_generation(recipe, sidecar):
    path = Path(str(recipe["model"]) + ".json") if sidecar else recipe["model"]
    path.write_bytes(b"x" * path.stat().st_size)
    result = _run(recipe)
    assert result.returncode != 0
    assert not (recipe["root"] / "render-called").exists()


@pytest.mark.parametrize("sidecar", [False, True])
def test_recipe_refuses_missing_voice_files_before_generation(recipe, sidecar):
    path = Path(str(recipe["model"]) + ".json") if sidecar else recipe["model"]
    path.unlink()
    assert _run(recipe).returncode != 0
    assert not (recipe["root"] / "render-called").exists()


def test_recipe_requires_explicit_model_without_importing_voice_package(recipe):
    assert _run(recipe, explicit=False).returncode != 0
    assert not (recipe["root"] / "untrusted-import").exists()
    assert not (recipe["root"] / "render-called").exists()


@pytest.mark.parametrize("outside", [False, True])
def test_verified_fixture_reaches_unchanged_generation_arguments(recipe, outside):
    result = _run(recipe, outside=outside)
    assert result.returncode == 0, result.stderr
    args = (recipe["root"] / "render-called").read_text().splitlines()
    assert "Fictional fixture brief." in args
    assert args[-12:] == ["--duration", "30", "--aspect", "9:16", "--preset",
                          "ffmpeg_motion", "--style", "slate", "--quality", "high",
                          "--seed", "20261109"]
    assert not (recipe["root"] / "untrusted-import").exists()


@pytest.mark.parametrize("field,value", [("sha256", "not-a-digest"), ("bytes", 1)])
def test_recipe_refuses_invalid_recorded_identity(recipe, field, value):
    record = recipe["package"] / "environment-record.json"
    data = json.loads(record.read_text())
    data["voice_models"][VOICE][field] = value
    record.write_text(json.dumps(data))
    assert _run(recipe).returncode != 0
    assert not (recipe["root"] / "render-called").exists()
