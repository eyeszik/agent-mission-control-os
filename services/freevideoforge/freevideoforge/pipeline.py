"""The pipeline orchestrator.

    BRIEF -> SCRIPT -> STORYBOARD -> SHOTS -> MEDIA -> VOICE -> CAPTIONS
          -> COMPOSE -> QC -> EXPORT

Design rules this file enforces:

* Every stage advances the job FSM and persists before moving on, so a kill -9
  at any point leaves a resumable run rather than a corrupt one.
* Scene work is content-addressed. A scene whose input hash matches a recorded
  DONE state with a file still on disk is reused, never re-rendered. That makes
  resume cheap and makes a repeat run idempotent.
* A failing scene is repaired in place, up to the governor's retry limit. The
  job is never restarted wholesale because one scene failed.
* Nothing here knows what a provider is made of. Swapping the renderer for a
  diffusion backend changes no line in this file.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

from .audio import wav_duration
from .config import Settings
from .errors import ForgeError, ProviderUnavailable, RenderError, ResourceError
from .hashing import scene_input_hash, sha256_file, sha256_obj
from .models import (
    Aspect,
    GenerateRequest,
    JobState,
    Manifest,
    Project,
    RunResult,
    dump_json,
    to_jsonable,
)
from .providers.registry import TIER_FFMPEG_MOTION, TIER_LETTER, ProviderRegistry, \
    build_default_registry
from .state import RunStore, new_run_id
from .version import __version__

ProgressFn = Callable[[str, float, str], None]

#: Output filenames. Fixed by contract so automation can rely on them.
OUTPUT_NAMES = {
    "final_video": "final.mp4",
    "thumbnail": "thumbnail.jpg",
    "script": "script.json",
    "storyboard": "storyboard.json",
    "captions": "captions.srt",
    "manifest": "manifest.json",
    "quality_report": "quality-report.json",
}

#: Render heights per quality preset.
PRESET_HEIGHT = {"draft": 720, "balanced": 1920, "high": 1920}
PRESET_CRF = {"draft": 28, "balanced": 20, "high": 17}
PRESET_ENCODER = {"draft": "veryfast", "balanced": "medium", "high": "slow"}


class Pipeline:
    """Runs one job from brief to validated export."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        registry: Optional[ProviderRegistry] = None,
        store: Optional[RunStore] = None,
        progress: Optional[ProgressFn] = None,
    ) -> None:
        self.settings = settings or Settings.resolve()
        self.settings.ensure_dirs()
        self.registry = registry or build_default_registry(
            self.settings, allow_paid=self.settings.allow_paid_providers
        )
        self.store = store or RunStore(self.settings.db_path, self.settings.state_json_path)
        self._progress = progress or (lambda stage, fraction, message: None)

    # -- helpers ---------------------------------------------------------
    def _emit(self, run_id: str, stage: str, fraction: float, message: str) -> None:
        self._progress(stage, fraction, message)
        self.store.log(run_id, "info", stage, message, {"progress": round(fraction, 4)})

    def _advance(self, run_id: str, state: JobState) -> None:
        self.store.set_state(run_id, state)

    # -- project construction --------------------------------------------
    def compile_brief(self, request: GenerateRequest, run_id: str) -> Project:
        """BRIEF stage: turn the request into a validated Project."""
        request.validate()
        aspect = Aspect.parse(request.aspect)
        height = int(request.height or PRESET_HEIGHT.get(request.quality_preset, 1920))
        width, height = aspect.resolution(height)
        seed = int(request.seed) if request.seed is not None else (
            abs(hash((request.topic, request.brief, request.duration))) % 1_000_000
        )

        project = Project(
            run_id=run_id,
            topic=request.topic.strip(),
            brief=(request.brief or "").strip(),
            duration=float(request.duration),
            aspect=aspect,
            style_system=request.style,
            language=request.language,
            seed=seed,
        )
        project.render.width = width
        project.render.height = height
        project.render.fps = int(request.fps)
        project.render.crf = PRESET_CRF.get(request.quality_preset, 20)
        project.render.preset = PRESET_ENCODER.get(request.quality_preset, "medium")
        project.render.burn_captions = bool(request.burn_captions)
        project.render.validate()

        if request.scenes:
            project.providers["_scene_count"] = str(int(request.scenes))

        self.settings.governor.check_plan(
            scenes=int(request.scenes or 12),
            duration=project.duration,
            width=width,
            height=height,
        )
        self.settings.governor.check_disk(self.settings.output_root)
        return project

    # -- stages ----------------------------------------------------------
    def stage_script(self, project: Project, request: GenerateRequest) -> dict[str, Any]:
        provider = self.registry.select("script", requested=request.script_provider)
        self._emit(project.run_id, "script", 0.08, f"scripting via {provider.name}")
        try:
            script = provider.generate(project)
        except ProviderUnavailable as exc:
            if request.script_provider not in {"auto", "", None}:
                raise
            # Degrade to the deterministic engine rather than failing the job.
            self.store.log(project.run_id, "warn", "script",
                           f"{provider.name} failed, using template", {"error": str(exc)})
            provider = self.registry.instance("template")
            script = provider.generate(project)
        project.providers["script"] = provider.name
        if script.get("model"):
            project.providers["script_model"] = str(script["model"])
        return script

    def stage_storyboard(self, project: Project, script: dict[str, Any]) -> None:
        provider = self.registry.select("storyboard")
        self._emit(project.run_id, "storyboard", 0.16, f"planning shots via {provider.name}")
        project.scenes = provider.plan(project, script)
        project.providers["storyboard"] = provider.name
        project.validate()
        self.settings.governor.check_plan(
            scenes=len(project.scenes),
            duration=project.total_scene_duration,
            width=project.render.width,
            height=project.render.height,
        )

    def stage_voice(self, project: Project, request: GenerateRequest, work: Path) -> bool:
        """VOICE stage. Returns True when real speech (not silence) was produced."""
        provider = self.registry.select(
            "speech", requested=request.speech_provider, fallback="silence"
        )
        project.providers["speech"] = provider.name
        is_speech = True
        for index, scene in enumerate(project.scenes):
            target = work / "audio" / f"{scene.id}.wav"
            input_hash = scene_input_hash(
                scene, project.render, provider.name,
                {"voice": request.voice, "language": project.language, "stage": "voice"},
            )
            reused = self.store.reusable_scene(project.run_id, scene.id, input_hash, "audio")
            if reused:
                scene.audio_path = reused
                scene.audio_duration = wav_duration(reused)
                self._emit(project.run_id, "voice",
                           0.24 + 0.10 * (index + 1) / len(project.scenes),
                           f"reusing narration for {scene.id}")
                continue
            try:
                result = provider.synthesize(
                    scene.content.voiceover, target,
                    voice=request.voice, language=project.language,
                )
            except ForgeError as exc:
                # Speech is never allowed to fail the job: fall back to timed
                # silence so the timeline and captions stay intact.
                self.store.log(project.run_id, "warn", "voice",
                               f"{provider.name} failed on {scene.id}", {"error": str(exc)})
                fallback = self.registry.instance("silence")
                result = fallback.synthesize(scene.content.voiceover, target)
                project.providers["speech"] = f"{provider.name}+silence_fallback"
            scene.audio_path = str(result.path)
            scene.audio_duration = result.duration
            is_speech = is_speech and result.is_speech
            self.store.upsert_scene(
                project.run_id, scene_id=scene.id, index=scene.index, state="DONE",
                audio_hash=input_hash, audio_path=scene.audio_path,
                duration=scene.duration,
            )
            self._emit(project.run_id, "voice",
                       0.24 + 0.10 * (index + 1) / len(project.scenes),
                       f"narrated {scene.id} ({result.duration:.2f}s)")
        self._reconcile_durations(project)
        return is_speech

    @staticmethod
    def _reconcile_durations(project: Project) -> None:
        """Make each scene at least as long as its own narration.

        Copy is never cut to fit a clock. The manifest records the resulting
        drift from the requested duration so the difference is visible rather
        than silent.
        """
        for scene in project.scenes:
            if scene.audio_duration:
                scene.duration = round(max(scene.duration, scene.audio_duration + 0.35), 3)

    def stage_captions(self, project: Project, output_dir: Path) -> dict[str, Any]:
        provider = self.registry.select("captions")
        self._emit(project.run_id, "captions", 0.36, f"timing captions via {provider.name}")
        result = provider.generate(project, output_dir / OUTPUT_NAMES["captions"])
        project.providers["captions"] = provider.name
        return {"srt": result.srt_path, "cues": result.cues, "technique": result.technique}

    def stage_media(
        self, project: Project, cues: list[dict[str, Any]], work: Path
    ) -> list[Path]:
        """MEDIA stage: render (or reuse) one clip per scene."""
        tier = self.registry.resolve_visual_tier()
        renderer = self.registry.select("render", fallback=TIER_FFMPEG_MOTION)
        project.providers["render"] = renderer.name
        project.providers["visual_tier"] = tier
        if tier != TIER_FFMPEG_MOTION:
            # A higher tier exists but scene media still routes through the
            # renderer contract; the tier is recorded for provenance.
            self.store.log(project.run_id, "info", "media",
                           f"visual tier {tier} available", {"tier": tier})

        clips_dir = work / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        self._sweep_partials(project.run_id, clips_dir)
        retry_limit = self.settings.governor.retry_limit
        workers = self.settings.governor.resolve_workers()
        total = len(project.scenes)
        done = 0

        def render_one(scene) -> Path:
            target = clips_dir / f"{scene.id}.mp4"
            scene_cues = [c for c in cues if c.get("scene_id") == scene.id]
            input_hash = scene_input_hash(
                scene, project.render, renderer.name,
                {"cues": scene_cues, "stage": "media"},
            )
            scene.input_hash = input_hash
            reused = self.store.reusable_scene(project.run_id, scene.id, input_hash, "clip")
            if reused:
                scene.clip_path = reused
                scene.state = "DONE"
                return Path(reused)

            last_error: Optional[Exception] = None
            for attempt in range(1, retry_limit + 1):
                scene.attempts = attempt
                try:
                    result = renderer.render_scene(
                        project, scene, target, captions=scene_cues,
                        timeout=self.settings.governor.scene_timeout_seconds,
                    )
                except (RenderError, OSError) as exc:
                    last_error = exc
                    self.store.log(project.run_id, "warn", "media",
                                   f"{scene.id} attempt {attempt} failed",
                                   {"error": str(exc)[:500]})
                    self.store.upsert_scene(
                        project.run_id, scene_id=scene.id, index=scene.index,
                        state="FAILED", clip_hash=input_hash, attempts=attempt,
                        error=str(exc)[:500], duration=scene.duration,
                    )
                    continue
                scene.clip_path = str(result.path)
                scene.state = "DONE"
                scene.error = None
                self.store.upsert_scene(
                    project.run_id, scene_id=scene.id, index=scene.index, state="DONE",
                    clip_hash=input_hash, clip_path=scene.clip_path,
                    duration=scene.duration, attempts=attempt,
                )
                return result.path
            scene.state = "FAILED"
            scene.error = str(last_error)
            raise RenderError(
                f"Scene {scene.id} failed after {retry_limit} attempts: {last_error}"
            )

        clips: list[Optional[Path]] = [None] * total
        if workers > 1 and total > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(render_one, scene): scene.index
                    for scene in project.scenes
                }
                for future, index in futures.items():
                    clips[index] = future.result()
                    done += 1
                    self._emit(project.run_id, "media", 0.40 + 0.38 * done / total,
                               f"rendered {done}/{total} scenes")
        else:
            for scene in project.scenes:
                clips[scene.index] = render_one(scene)
                done += 1
                self._emit(project.run_id, "media", 0.40 + 0.38 * done / total,
                           f"rendered {done}/{total} scenes")

        missing = [project.scenes[i].id for i, clip in enumerate(clips) if clip is None]
        if missing:
            raise RenderError(f"No clip produced for scenes: {', '.join(missing)}")
        return [Path(clip) for clip in clips if clip is not None]

    def _sweep_partials(self, run_id: str, directory: Path) -> int:
        """Delete half-written clips left behind by a killed render.

        A ``.partial`` file is never reusable - reuse requires a recorded DONE
        state pointing at the published path - so these are pure waste. Sweeping
        them keeps a repeatedly interrupted run from filling the disk.
        """
        removed = 0
        for stale in directory.glob("*.partial.*"):
            try:
                size = stale.stat().st_size
                stale.unlink()
                removed += 1
                self.store.log(run_id, "info", "media", "removed stale partial clip",
                               {"path": str(stale), "bytes": size})
            except OSError:
                continue
        return removed

    def stage_compose(
        self, project: Project, request: GenerateRequest, clips: list[Path],
        work: Path, output_dir: Path,
    ) -> tuple[Path, Optional[Path]]:
        renderer = self.registry.instance(project.providers.get("render", TIER_FFMPEG_MOTION))
        self._emit(project.run_id, "compose", 0.80, "mixing audio")

        tracks: list[tuple[Path, float, float]] = []
        cursor = 0.0
        for scene in project.scenes:
            if scene.audio_path and Path(scene.audio_path).exists():
                tracks.append((Path(scene.audio_path), cursor, scene.duration))
            cursor += scene.duration

        audio_path: Optional[Path] = None
        try:
            audio_path = renderer.build_audio_bed(
                project, tracks, work / "audio" / "master.wav",
                music=request.music, total_duration=project.total_scene_duration,
            )
        except (RenderError, ForgeError) as exc:
            # A failed music bed must not sink the render; drop to voice-only.
            self.store.log(project.run_id, "warn", "compose",
                           "audio bed failed, retrying without music",
                           {"error": str(exc)[:400]})
            audio_path = renderer.build_audio_bed(
                project, tracks, work / "audio" / "master.wav",
                music="none", total_duration=project.total_scene_duration,
            )

        self._emit(project.run_id, "compose", 0.86, "composing final video")
        final = output_dir / OUTPUT_NAMES["final_video"]
        renderer.compose(project, clips=clips, audio=audio_path, output=final)
        return final, audio_path

    # -- entry point -----------------------------------------------------
    def run(self, request: GenerateRequest, run_id: Optional[str] = None) -> RunResult:
        """Execute the full pipeline. Resumes when ``run_id`` names an existing run."""
        started = time.time()
        resuming = bool(run_id) and self.store.run_exists(run_id or "")
        run_id = run_id or request.run_id or new_run_id()
        output_dir = Path(request.output_dir) if request.output_dir else \
            self.settings.run_output_dir(run_id)
        work = self.settings.run_work_dir(run_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)

        config_hash = sha256_obj(to_jsonable(request))
        if not resuming:
            self.store.create_run(
                run_id=run_id, topic=request.topic, config_hash=config_hash,
                request=to_jsonable(request), output_dir=output_dir, work_dir=work,
            )
        else:
            record = self.store.get_run(run_id)
            if record["config_hash"] != config_hash:
                self.store.log(run_id, "warn", "resume",
                               "request changed since the original run; "
                               "mismatched scene artifacts will be re-rendered")
            output_dir = Path(record["output_dir"])
            work = Path(record["work_dir"])
        self.store.bump_attempts(run_id)

        warnings: list[str] = []
        try:
            self._advance(run_id, JobState.PLANNING)
            project = self.compile_brief(request, run_id)

            script = self.stage_script(project, request)
            dump_json(script, output_dir / OUTPUT_NAMES["script"])
            self.store.save_project(project)
            self._advance(run_id, JobState.SCRIPT_READY)

            self.stage_storyboard(project, script)
            self.store.save_project(project)
            self._advance(run_id, JobState.STORYBOARD_READY)

            self._advance(run_id, JobState.AUDIO_GENERATING)
            has_speech = self.stage_voice(project, request, work)
            if not has_speech:
                warnings.append(
                    "No local TTS engine was available, so the narration track is timed "
                    "silence. Install espeak-ng or Piper for real voiceover."
                )
            self.store.save_project(project)
            self._advance(run_id, JobState.AUDIO_READY)

            captions = self.stage_captions(project, output_dir)

            # The storyboard is written after voice so it carries the reconciled
            # durations that were actually rendered.
            dump_json(
                {
                    "schema_version": "freevideoforge/storyboard/v1",
                    "run_id": run_id,
                    "topic": project.topic,
                    "style_system": project.style_system,
                    "aspect": project.aspect.value,
                    "render": to_jsonable(project.render),
                    "total_duration": project.total_scene_duration,
                    "scenes": [to_jsonable(scene) for scene in project.scenes],
                },
                output_dir / OUTPUT_NAMES["storyboard"],
            )

            self._advance(run_id, JobState.MEDIA_GENERATING)
            clips = self.stage_media(project, captions["cues"], work)
            self.store.save_project(project)
            self._advance(run_id, JobState.MEDIA_READY)

            self._advance(run_id, JobState.COMPOSING)
            final, audio_path = self.stage_compose(
                project, request, clips, work, output_dir
            )

            thumbnail = output_dir / OUTPUT_NAMES["thumbnail"]
            renderer = self.registry.instance(project.providers.get("render",
                                                                    TIER_FFMPEG_MOTION))
            renderer.render_thumbnail(project, thumbnail, script.get("title", project.topic))

            self._advance(run_id, JobState.VALIDATING)
            outputs = {
                "final_video": final,
                "thumbnail": thumbnail,
                "script": output_dir / OUTPUT_NAMES["script"],
                "storyboard": output_dir / OUTPUT_NAMES["storyboard"],
                "captions": output_dir / OUTPUT_NAMES["captions"],
                "manifest": output_dir / OUTPUT_NAMES["manifest"],
                "caption_cues": captions["cues"],
            }
            if audio_path:
                outputs["audio"] = audio_path

            manifest = self._write_manifest(
                project, request, script, captions, outputs, final, audio_path,
                started, has_speech, warnings,
            )
            outputs["manifest"] = manifest

            quality = self.registry.select("quality")
            report = quality.validate(project, outputs)
            dump_json(
                {
                    "schema_version": "freevideoforge/quality-report/v1",
                    "run_id": run_id,
                    "passed": report.passed,
                    "summary": report.summary(),
                    "mandatory_failures": [c.id for c in report.structural_failures],
                    "checks": [to_jsonable(c) for c in report.checks],
                },
                output_dir / OUTPUT_NAMES["quality_report"],
            )

            for asset_key in ("final_video", "thumbnail", "script", "storyboard",
                              "captions", "manifest"):
                path = Path(outputs[asset_key])
                if path.exists():
                    self.store.record_asset(run_id, {
                        "kind": asset_key, "path": str(path),
                        "sha256": sha256_file(path), "bytes": path.stat().st_size,
                        "provider": project.providers.get("render", "pipeline"),
                    })

            if not report.passed:
                failures = ", ".join(c.id for c in report.structural_failures)
                self._advance(run_id, JobState.FAILED)
                self.store.set_state(run_id, JobState.FAILED,
                                     f"structural QC failed: {failures}")
                return RunResult(
                    run_id=run_id, state=JobState.FAILED, output_dir=str(output_dir),
                    final_video=str(final), quality_report=str(
                        output_dir / OUTPUT_NAMES["quality_report"]),
                    providers=dict(project.providers), warnings=warnings,
                    error=f"structural QC failed: {failures}",
                )

            self._advance(run_id, JobState.COMPLETED)
            self._emit(run_id, "export", 1.0, f"completed in {time.time() - started:.1f}s")
            return RunResult(
                run_id=run_id,
                state=JobState.COMPLETED,
                output_dir=str(output_dir),
                final_video=str(final),
                thumbnail=str(thumbnail),
                script=str(output_dir / OUTPUT_NAMES["script"]),
                storyboard=str(output_dir / OUTPUT_NAMES["storyboard"]),
                captions=str(output_dir / OUTPUT_NAMES["captions"]),
                manifest=str(output_dir / OUTPUT_NAMES["manifest"]),
                quality_report=str(output_dir / OUTPUT_NAMES["quality_report"]),
                duration=project.total_scene_duration,
                providers=dict(project.providers),
                warnings=warnings,
            )

        except (ForgeError, OSError) as exc:
            self.store.set_state(run_id, JobState.FAILED, str(exc)[:1000])
            return RunResult(
                run_id=run_id, state=JobState.FAILED, output_dir=str(output_dir),
                warnings=warnings, error=str(exc),
            )

    # -- manifest --------------------------------------------------------
    def _write_manifest(
        self, project: Project, request: GenerateRequest, script: dict[str, Any],
        captions: dict[str, Any], outputs: dict[str, Any], final: Path,
        audio: Optional[Path], started: float, has_speech: bool, warnings: list[str],
    ) -> Path:
        import platform

        assets = []
        for scene in project.scenes:
            for kind, path in (("scene_clip", scene.clip_path),
                               ("scene_audio", scene.audio_path)):
                if path and Path(path).exists():
                    assets.append({
                        "kind": kind, "scene_id": scene.id, "path": str(path),
                        "sha256": sha256_file(path),
                        "bytes": Path(path).stat().st_size,
                        "provider": project.providers.get(
                            "render" if kind == "scene_clip" else "speech", "unknown"),
                        "duration": scene.duration if kind == "scene_clip"
                        else scene.audio_duration,
                        "seed": scene.seed,
                        "input_hash": scene.input_hash,
                    })

        capabilities = self.registry.summary()
        manifest = Manifest(
            run_id=project.run_id,
            version=__version__,
            created_at=started,
            completed_at=time.time(),
            config_hash=sha256_obj(to_jsonable(request)),
            project=to_jsonable(project),
            providers={
                "resolved": dict(project.providers),
                "visual_tier": capabilities["visual_tier"],
                "capability_tier": TIER_LETTER.get(capabilities["visual_tier"], "C"),
                "active": capabilities["active"],
                "unavailable": capabilities["unavailable"],
                "technique": "procedural_ffmpeg",
                "technique_note": (
                    "Scene media is procedural motion graphics rendered on the CPU. "
                    "It is not diffusion video and is not labelled as such."
                ),
                "script_content_source": script.get("content_source"),
                "caption_technique": captions.get("technique"),
                "narration_is_speech": has_speech,
            },
            assets=assets,
            outputs={
                key: str(value) for key, value in outputs.items()
                if isinstance(value, (str, Path))
            },
            environment={
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "cpu_count": __import__("os").cpu_count(),
                "render_workers": self.settings.governor.resolve_workers(),
            },
            zero_paid_api_spend=True,
            credentials_used=[],
        )
        payload = to_jsonable(manifest)
        payload["schema_version"] = "freevideoforge/manifest/v1"
        payload["requested"] = to_jsonable(request)
        payload["duration"] = {
            "requested": project.duration,
            "planned": script.get("planned_duration"),
            "rendered": project.total_scene_duration,
            "drift_seconds": round(project.total_scene_duration - project.duration, 3),
            "note": script.get("duration_note", "") or
            "Scene durations were extended where narration needed more time than "
            "the requested duration allowed.",
        }
        payload["warnings"] = warnings
        payload["remote_fetching_enabled"] = self.settings.allow_remote_fetch
        return dump_json(payload, Path(outputs["manifest"]))
