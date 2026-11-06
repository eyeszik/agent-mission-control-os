"""Shared fixtures.

Every test runs against a throwaway workspace so nothing leaks between tests or
into the developer's own output directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freevideoforge.config import Settings  # noqa: E402
from freevideoforge.ffmpeg import FFTools  # noqa: E402
from freevideoforge.models import GenerateRequest  # noqa: E402
from freevideoforge.providers.registry import build_default_registry  # noqa: E402
from freevideoforge.state import RunStore  # noqa: E402


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def settings(workspace: Path) -> Settings:
    resolved = Settings.resolve(workspace)
    resolved.ensure_dirs()
    return resolved


@pytest.fixture
def registry(settings: Settings):
    return build_default_registry(settings)


@pytest.fixture
def store(settings: Settings) -> RunStore:
    return RunStore(settings.db_path, settings.state_json_path)


@pytest.fixture
def tools() -> FFTools:
    return FFTools()


@pytest.fixture
def fast_request() -> GenerateRequest:
    """A deliberately tiny job so the suite stays quick but still renders real
    video through the real encoder."""
    return GenerateRequest(
        topic="Why the moon changes shape",
        duration=5.0,
        aspect="9:16",
        quality_preset="draft",
        height=256,
        fps=12,
        music="none",
        seed=1234,
    )


def requires_ffmpeg(tools: FFTools) -> None:
    if not tools.ffmpeg or not tools.ffprobe:
        pytest.skip("ffmpeg/ffprobe not installed on this host")


@pytest.fixture(autouse=True)
def _no_credentials(monkeypatch: pytest.MonkeyPatch):
    """Prove the zero-credential claim: every test runs with plausible API key
    variables removed from the environment."""
    for name in list(os.environ):
        if name.endswith(("_API_KEY", "_TOKEN", "_SECRET")) or name in {
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "REPLICATE_API_TOKEN",
            "ELEVENLABS_API_KEY", "HF_TOKEN",
        }:
            monkeypatch.delenv(name, raising=False)
    yield
