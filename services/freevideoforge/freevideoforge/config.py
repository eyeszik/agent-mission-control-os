"""Runtime configuration, workspace layout and the resource governor.

Configuration comes from (in increasing priority): built-in defaults,
``FVF_*`` environment variables, then explicit arguments. Nothing here reads a
credential, and nothing here contacts a network.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError, ResourceError

#: Directory (relative to the workspace root) holding durable job state.
STATE_DIRNAME = ".freevideoforge"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ResourceGovernor:
    """Bounds every run so degradation is graceful instead of an OOM or a
    runaway render."""

    max_concurrent_heavy_jobs: int = 1
    retry_limit: int = 3
    max_scenes: int = 40
    max_duration_seconds: float = 600.0
    max_scene_duration_seconds: float = 60.0
    max_pixels: int = 3840 * 2160
    scene_timeout_seconds: float = 900.0
    min_free_disk_mb: int = 512
    render_workers: int = 0  # 0 => auto (cpu_count - 1, clamped)

    @classmethod
    def from_env(cls) -> "ResourceGovernor":
        return cls(
            max_concurrent_heavy_jobs=_env_int("FVF_MAX_CONCURRENT_JOBS", 1),
            retry_limit=_env_int("FVF_RETRY_LIMIT", 3),
            max_scenes=_env_int("FVF_MAX_SCENES", 40),
            max_duration_seconds=_env_float("FVF_MAX_DURATION", 600.0),
            max_scene_duration_seconds=_env_float("FVF_MAX_SCENE_DURATION", 60.0),
            max_pixels=_env_int("FVF_MAX_PIXELS", 3840 * 2160),
            scene_timeout_seconds=_env_float("FVF_SCENE_TIMEOUT", 900.0),
            min_free_disk_mb=_env_int("FVF_MIN_FREE_DISK_MB", 512),
            render_workers=_env_int("FVF_RENDER_WORKERS", 0),
        )

    def resolve_workers(self) -> int:
        if self.render_workers > 0:
            return self.render_workers
        return max(1, min(4, (os.cpu_count() or 2) - 1))

    def check_plan(self, *, scenes: int, duration: float, width: int, height: int) -> None:
        """Reject a plan that exceeds the budget before any heavy work starts."""
        if scenes > self.max_scenes:
            raise ResourceError(
                f"Plan needs {scenes} scenes, governor allows {self.max_scenes}. "
                "Raise FVF_MAX_SCENES or shorten the video."
            )
        if duration > self.max_duration_seconds:
            raise ResourceError(
                f"Plan is {duration:.1f}s, governor allows {self.max_duration_seconds:.0f}s. "
                "Raise FVF_MAX_DURATION or shorten the video."
            )
        if width * height > self.max_pixels:
            raise ResourceError(
                f"Frame {width}x{height} exceeds the {self.max_pixels} pixel budget. "
                "Lower --height or raise FVF_MAX_PIXELS."
            )

    def check_disk(self, path: Path) -> None:
        target = path
        while not target.exists() and target != target.parent:
            target = target.parent
        free_mb = shutil.disk_usage(target).free // (1024 * 1024)
        if free_mb < self.min_free_disk_mb:
            raise ResourceError(
                f"Only {free_mb} MB free at {target}; FreeVideoForge needs at least "
                f"{self.min_free_disk_mb} MB. Free space or lower FVF_MIN_FREE_DISK_MB."
            )


@dataclass
class Settings:
    """Resolved workspace paths and global switches."""

    workspace: Path
    output_root: Path
    state_dir: Path
    work_root: Path
    governor: ResourceGovernor = field(default_factory=ResourceGovernor)
    #: Remote URL fetching is OFF by default (SECURITY contract).
    allow_remote_fetch: bool = False
    #: When False, any provider that would require paid credentials is refused.
    allow_paid_providers: bool = False
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None
    font_dirs: tuple[str, ...] = ()

    @classmethod
    def resolve(
        cls,
        workspace: str | Path | None = None,
        output_dir: str | Path | None = None,
        *,
        allow_paid: bool = False,
    ) -> "Settings":
        root = Path(workspace or os.environ.get("FVF_WORKSPACE") or Path.cwd()).resolve()
        out = Path(
            output_dir or os.environ.get("FVF_OUTPUT_DIR") or (root / "out")
        ).resolve()
        state = root / STATE_DIRNAME
        extra_fonts = os.environ.get("FVF_FONT_DIRS", "")
        return cls(
            workspace=root,
            output_root=out,
            state_dir=state,
            work_root=state / "work",
            governor=ResourceGovernor.from_env(),
            allow_remote_fetch=_env_bool("FVF_ALLOW_REMOTE_FETCH", False),
            allow_paid_providers=bool(allow_paid) or _env_bool("FVF_ALLOW_PAID", False),
            ffmpeg_path=os.environ.get("FVF_FFMPEG") or None,
            ffprobe_path=os.environ.get("FVF_FFPROBE") or None,
            font_dirs=tuple(p for p in extra_fonts.split(os.pathsep) if p),
        )

    def ensure_dirs(self) -> None:
        for path in (self.output_root, self.state_dir, self.work_root):
            path.mkdir(parents=True, exist_ok=True)

    def run_output_dir(self, run_id: str) -> Path:
        return self.output_root / run_id

    def run_work_dir(self, run_id: str) -> Path:
        return self.work_root / run_id

    @property
    def db_path(self) -> Path:
        return self.state_dir / "state.db"

    @property
    def state_json_path(self) -> Path:
        return self.state_dir / "state.json"
