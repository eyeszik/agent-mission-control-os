"""Programmatic local interface.

This is the stable surface for automation: another process, an agent, a job
queue or an n8n node calls these functions directly. It is a plain Python API
over a local pipeline - no server required, no credentials, no network.

    from freevideoforge.api import generate, GenerateRequest

    result = generate(GenerateRequest(topic="Why the moon changes shape",
                                      duration=30, aspect="9:16"))
    if result.ok:
        print(result.final_video)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from .config import Settings
from .models import GenerateRequest, JobState, RunResult
from .pipeline import Pipeline
from .providers.registry import build_default_registry
from .state import RunStore

ProgressFn = Callable[[str, float, str], None]


def build_pipeline(
    workspace: str | Path | None = None,
    output_dir: str | Path | None = None,
    *,
    allow_paid: bool = False,
    progress: Optional[ProgressFn] = None,
) -> Pipeline:
    """Construct a pipeline bound to a workspace. Cheap; safe to call per job."""
    settings = Settings.resolve(workspace, output_dir, allow_paid=allow_paid)
    settings.ensure_dirs()
    registry = build_default_registry(settings, allow_paid=settings.allow_paid_providers)
    store = RunStore(settings.db_path, settings.state_json_path)
    return Pipeline(settings=settings, registry=registry, store=store, progress=progress)


def generate(
    request: GenerateRequest,
    *,
    workspace: str | Path | None = None,
    progress: Optional[ProgressFn] = None,
    run_id: Optional[str] = None,
) -> RunResult:
    """Run the full BRIEF -> EXPORT pipeline and return the result."""
    pipeline = build_pipeline(
        workspace, request.output_dir, allow_paid=request.allow_paid, progress=progress
    )
    return pipeline.run(request, run_id=run_id)


def resume(
    run_id: str,
    *,
    workspace: str | Path | None = None,
    progress: Optional[ProgressFn] = None,
) -> RunResult:
    """Resume an interrupted or failed run from its last valid artifacts."""
    pipeline = build_pipeline(workspace, progress=progress)
    record = pipeline.store.get_run(run_id)
    state = JobState(record["state"])
    if state is JobState.COMPLETED:
        output_dir = Path(record["output_dir"])
        return RunResult(
            run_id=run_id, state=state, output_dir=str(output_dir),
            final_video=str(output_dir / "final.mp4"),
            thumbnail=str(output_dir / "thumbnail.jpg"),
            manifest=str(output_dir / "manifest.json"),
            providers=record.get("providers", {}),
            warnings=["run was already complete; nothing to do"],
        )
    request = GenerateRequest.from_dict(record["request"])
    return pipeline.run(request, run_id=run_id)


def describe_providers(
    workspace: str | Path | None = None, *, allow_paid: bool = False
) -> dict[str, Any]:
    """Discovery report: what is available here, what is not, and why."""
    settings = Settings.resolve(workspace, allow_paid=allow_paid)
    registry = build_default_registry(settings, allow_paid=settings.allow_paid_providers)
    return registry.summary()


def list_runs(workspace: str | Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    settings = Settings.resolve(workspace)
    settings.ensure_dirs()
    return RunStore(settings.db_path, settings.state_json_path).list_runs(limit)


def run_status(run_id: str, workspace: str | Path | None = None) -> dict[str, Any]:
    """Current state, scene progress and recent events for one run."""
    settings = Settings.resolve(workspace)
    settings.ensure_dirs()
    store = RunStore(settings.db_path, settings.state_json_path)
    record = store.get_run(run_id)
    scenes = store.get_scene_states(run_id)
    return {
        "run_id": run_id,
        "state": record["state"],
        "topic": record["topic"],
        "output_dir": record["output_dir"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "completed_at": record["completed_at"],
        "error": record["error"],
        "providers": record["providers"],
        "scenes": {
            scene_id: {
                "state": data["state"],
                "attempts": data["attempts"],
                "duration": data["duration"],
                "error": data["error"],
            }
            for scene_id, data in scenes.items()
        },
        "events": store.events(run_id, limit=100),
    }


__all__ = [
    "GenerateRequest", "RunResult", "build_pipeline", "generate", "resume",
    "describe_providers", "list_runs", "run_status",
]
