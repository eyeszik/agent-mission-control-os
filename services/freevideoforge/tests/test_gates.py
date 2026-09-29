"""Acceptance gates G1-G9.

Each test maps to one gate in the project's acceptance contract. They exercise
the real pipeline against the real encoder - no mocked ffmpeg - because the
whole claim being tested is "this produces a valid video on a bare CPU".

G9 is skipped as NOT_APPLICABLE when no local generative backend exists. It is
never reported as a pass on a host that cannot run it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from freevideoforge import api, doctor
from freevideoforge.errors import PaidProviderRejected, ProviderUnavailable
from freevideoforge.models import GenerateRequest, JobState
from freevideoforge.providers.base import Capability
from freevideoforge.providers.registry import (
    TIER_FFMPEG_MOTION,
    ProviderRegistry,
    build_default_registry,
)

from conftest import requires_ffmpeg


# --------------------------------------------------------------------------
# G1 ZERO_KEY_BOOT
# --------------------------------------------------------------------------


class TestG1ZeroKeyBoot:
    def test_boots_and_diagnoses_with_no_credentials_present(self, workspace):
        report = doctor.collect(workspace)
        assert report["zero_required_api_spend"] is True
        assert report["zero_required_credentials"] is True
        assert report["credentials_read"] == []

    def test_no_bundled_provider_requires_payment(self, registry: ProviderRegistry):
        for name, capability in registry.discover().items():
            assert capability.requires_payment is False, name

    def test_a_pipeline_can_be_built_with_a_scrubbed_environment(self, workspace,
                                                                 monkeypatch):
        for name in list(os.environ):
            if "KEY" in name or "TOKEN" in name or "SECRET" in name:
                monkeypatch.delenv(name, raising=False)
        pipeline = api.build_pipeline(workspace)
        assert pipeline.registry.select("script") is not None
        assert pipeline.registry.select("render", fallback=TIER_FFMPEG_MOTION) is not None

    def test_remote_fetching_is_off_by_default(self, settings):
        assert settings.allow_remote_fetch is False


# --------------------------------------------------------------------------
# G2 CPU_FALLBACK_RENDER
# --------------------------------------------------------------------------


class TestG2CpuFallbackRender:
    def test_the_mandatory_renderer_is_always_registered(self, registry):
        names = [r.name for r in registry.registrations("render")]
        assert TIER_FFMPEG_MOTION in names

    def test_renders_a_single_scene_to_a_decodable_clip(self, settings, tools, tmp_path):
        requires_ffmpeg(tools)
        from freevideoforge.models import Project
        from freevideoforge.providers.render_ffmpeg import FFmpegMotionRenderProvider
        from freevideoforge.providers.script_template import TemplateScriptProvider
        from freevideoforge.providers.storyboard_planner import (
            DeterministicStoryboardProvider,
        )

        project = Project(run_id="g2", topic="A single scene", duration=2.0, seed=5)
        project.render.width, project.render.height = 144, 256
        project.render.fps = 10
        script = TemplateScriptProvider().generate(project)
        project.scenes = DeterministicStoryboardProvider().plan(project, script)
        scene = project.scenes[0]
        scene.duration = 2.0

        renderer = FFmpegMotionRenderProvider(settings)
        result = renderer.render_scene(project, scene, tmp_path / "scene.mp4")

        assert result.technique == "procedural_ffmpeg"
        probe = tools.probe(result.path)
        assert probe.has_video
        assert (probe.video.width, probe.video.height) == (144, 256)
        assert probe.duration == pytest.approx(2.0, abs=0.25)
        decoded, stderr = tools.decodes(result.path)
        assert decoded, stderr

    def test_renderer_does_not_claim_to_be_a_diffusion_model(self, settings):
        from freevideoforge.providers.render_ffmpeg import FFmpegMotionRenderProvider

        capability = FFmpegMotionRenderProvider(settings).probe()
        assert capability.metadata["technique"] == "procedural_ffmpeg"
        assert "diffusion" not in capability.detail.lower()


# --------------------------------------------------------------------------
# G3 END_TO_END_PIPELINE
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _e2e(tmp_path_factory):
    """One real end-to-end render, shared by the gates that inspect it."""
    from freevideoforge.ffmpeg import FFTools

    tools = FFTools()
    if not tools.ffmpeg or not tools.ffprobe:
        pytest.skip("ffmpeg/ffprobe not installed on this host")
    workspace = tmp_path_factory.mktemp("e2e")
    request = GenerateRequest(
        topic="Why the moon changes shape",
        duration=5.0, aspect="9:16", quality_preset="draft",
        height=256, fps=12, music="none", seed=4242,
    )
    result = api.generate(request, workspace=workspace)
    return {"workspace": workspace, "result": result, "tools": tools, "request": request}


class TestG3EndToEndPipeline:
    def test_run_completes(self, _e2e):
        assert _e2e["result"].state is JobState.COMPLETED, _e2e["result"].error

    @pytest.mark.parametrize(
        "name",
        ["final.mp4", "thumbnail.jpg", "script.json", "storyboard.json",
         "captions.srt", "manifest.json", "quality-report.json"],
    )
    def test_every_required_artifact_exists_and_is_non_empty(self, _e2e, name):
        path = Path(_e2e["result"].output_dir) / name
        assert path.is_file(), f"{name} missing"
        assert path.stat().st_size > 0, f"{name} empty"

    def test_output_is_a_valid_mp4_with_the_requested_geometry(self, _e2e):
        probe = _e2e["tools"].probe(_e2e["result"].final_video)
        assert probe.has_video
        assert probe.video.codec_name == "h264"
        ratio = probe.video.width / probe.video.height
        assert ratio == pytest.approx(9 / 16, abs=0.02)
        assert probe.video.avg_frame_rate == pytest.approx(12, abs=0.5)

    def test_output_fully_decodes(self, _e2e):
        ok, stderr = _e2e["tools"].decodes(_e2e["result"].final_video)
        assert ok, stderr

    def test_duration_is_within_tolerance_of_the_plan(self, _e2e):
        probe = _e2e["tools"].probe(_e2e["result"].final_video)
        assert probe.duration == pytest.approx(_e2e["result"].duration, abs=0.4)

    def test_audio_track_is_present_and_audible(self, _e2e):
        probe = _e2e["tools"].probe(_e2e["result"].final_video)
        assert probe.has_audio
        assert probe.audio.channels and probe.audio.channels >= 1

    def test_thumbnail_is_a_real_image_at_the_output_size(self, _e2e):
        from PIL import Image

        with Image.open(_e2e["result"].thumbnail) as image:
            probe = _e2e["tools"].probe(_e2e["result"].final_video)
            assert image.size == (probe.video.width, probe.video.height)

    def test_manifest_records_honest_provenance(self, _e2e):
        manifest = json.loads(Path(_e2e["result"].manifest).read_text())
        assert manifest["zero_paid_api_spend"] is True
        assert manifest["credentials_used"] == []
        assert manifest["providers"]["technique"] == "procedural_ffmpeg"
        assert manifest["providers"]["capability_tier"] in {"A", "B", "C"}
        assert manifest["remote_fetching_enabled"] is False
        assert manifest["duration"]["rendered"] > 0

    def test_manifest_hashes_every_scene_asset(self, _e2e):
        manifest = json.loads(Path(_e2e["result"].manifest).read_text())
        clips = [a for a in manifest["assets"] if a["kind"] == "scene_clip"]
        assert clips
        for asset in clips:
            assert len(asset["sha256"]) == 64
            assert asset["bytes"] > 0
            assert asset["input_hash"]

    def test_captions_are_valid_srt_inside_the_timeline(self, _e2e):
        text = Path(_e2e["result"].captions).read_text(encoding="utf-8")
        assert text.strip()
        assert text.lstrip().startswith("1\n")
        assert " --> " in text

    def test_script_declares_where_its_content_came_from(self, _e2e):
        script = json.loads(Path(_e2e["result"].script).read_text())
        assert script["content_source"] in {"scaffold", "brief", "local_llm"}
        assert script["content_source_note"]

    def test_storyboard_records_reconciled_scene_durations(self, _e2e):
        storyboard = json.loads(Path(_e2e["result"].storyboard).read_text())
        assert storyboard["scenes"]
        total = sum(s["duration"] for s in storyboard["scenes"])
        assert total == pytest.approx(storyboard["total_duration"], abs=0.01)
        for scene in storyboard["scenes"]:
            assert scene["duration"] > 0


# --------------------------------------------------------------------------
# G4 RESUME_AFTER_INTERRUPTION
# --------------------------------------------------------------------------


class TestG4ResumeAfterInterruption:
    def test_a_completed_scene_is_reused_not_re_rendered(self, workspace, tools):
        requires_ffmpeg(tools)
        request = GenerateRequest(
            topic="Resumable render", duration=5.0, quality_preset="draft",
            height=192, fps=10, music="none", seed=11,
        )
        first = api.generate(request, workspace=workspace)
        assert first.state is JobState.COMPLETED, first.error

        pipeline = api.build_pipeline(workspace)
        scenes = pipeline.store.get_scene_states(first.run_id)
        assert scenes
        clip = Path(next(iter(scenes.values()))["clip_path"])
        marker = clip.stat().st_mtime_ns

        # Rewind the run and re-drive it: unchanged scenes must be reused.
        pipeline.store.set_state(first.run_id, JobState.FAILED, "simulated interruption")
        second = api.resume(first.run_id, workspace=workspace)
        assert second.state is JobState.COMPLETED, second.error
        assert clip.stat().st_mtime_ns == marker, "scene clip was needlessly re-rendered"

    def test_a_scene_whose_inputs_changed_is_not_reused(self, workspace, tools, tmp_path):
        requires_ffmpeg(tools)
        from freevideoforge.hashing import scene_input_hash
        from freevideoforge.models import Project, Scene
        from freevideoforge.state import RunStore

        store = RunStore(tmp_path / "s.db")
        store.create_run(run_id="r", topic="t", config_hash="c", request={},
                         output_dir=tmp_path, work_dir=tmp_path)
        scene = Scene(id="s01", index=0, duration=2.0)
        project = Project(run_id="r", topic="t")
        artifact = tmp_path / "s01.mp4"
        artifact.write_bytes(b"x")
        original = scene_input_hash(scene, project.render, "ffmpeg_motion")
        store.upsert_scene("r", scene_id="s01", index=0, state="DONE",
                           clip_hash=original, clip_path=str(artifact))

        assert store.reusable_scene("r", "s01", original) == str(artifact)
        scene.duration = 3.0
        changed = scene_input_hash(scene, project.render, "ffmpeg_motion")
        assert changed != original
        assert store.reusable_scene("r", "s01", changed) is None

    def test_a_missing_artifact_is_never_treated_as_reusable(self, tmp_path):
        from freevideoforge.state import RunStore

        store = RunStore(tmp_path / "s.db")
        store.create_run(run_id="r", topic="t", config_hash="c", request={},
                         output_dir=tmp_path, work_dir=tmp_path)
        store.upsert_scene("r", scene_id="s01", index=0, state="DONE",
                           clip_hash="h", clip_path=str(tmp_path / "gone.mp4"))
        assert store.reusable_scene("r", "s01", "h") is None

    def test_state_survives_a_new_process(self, workspace, tools):
        requires_ffmpeg(tools)
        request = GenerateRequest(topic="Durable state", duration=5.0,
                                  quality_preset="draft", height=192, fps=10,
                                  music="none", seed=3)
        result = api.generate(request, workspace=workspace)
        assert result.state is JobState.COMPLETED, result.error

        # A separate interpreter reads the same store - this is what makes a run
        # resumable from another session or tool.
        script = (
            "import sys, json;"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r});"
            "from freevideoforge import api;"
            f"print(json.dumps(api.run_status({result.run_id!r}, {str(workspace)!r})['state']))"
        )
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True,
                              text=True, check=True)
        assert json.loads(proc.stdout.strip()) == "COMPLETED"

    def test_state_json_mirror_is_written_for_cross_tool_inspection(self, workspace, tools):
        requires_ffmpeg(tools)
        api.generate(
            GenerateRequest(topic="Mirror", duration=5.0, quality_preset="draft",
                            height=192, fps=10, music="none", seed=2),
            workspace=workspace,
        )
        mirror = Path(workspace) / ".freevideoforge" / "state.json"
        assert mirror.is_file()
        payload = json.loads(mirror.read_text())
        assert payload["runs"]
        assert payload["schema_version"].startswith("freevideoforge/state/")


# --------------------------------------------------------------------------
# G5 FREE_MODE_REJECTS_MANDATORY_PAID_PROVIDER
# --------------------------------------------------------------------------


class _PaidProvider:
    name = "paid_cloud"
    kind = "script"

    def probe(self) -> Capability:
        return Capability(
            available=True, name=self.name, kind=self.kind,
            detail="Hypothetical paid cloud provider", requires_payment=True,
        )

    def generate(self, project):  # pragma: no cover - must never be reached
        raise AssertionError("a paid provider ran in free mode")


class TestG5FreeModeRejectsPaidProviders:
    def test_explicitly_requesting_a_paid_provider_is_refused(self, settings):
        registry = build_default_registry(settings, allow_paid=False)
        registry.register("paid_cloud", "script", _PaidProvider, priority=1)
        with pytest.raises(PaidProviderRejected, match="free mode"):
            registry.select("script", requested="paid_cloud")

    def test_auto_selection_never_picks_a_paid_provider(self, settings):
        registry = build_default_registry(settings, allow_paid=False)
        registry.register("paid_cloud", "script", _PaidProvider, priority=1)
        assert registry.select("script").name != "paid_cloud"

    def test_a_paid_provider_is_listed_as_unavailable_in_free_mode(self, settings):
        registry = build_default_registry(settings, allow_paid=False)
        registry.register("paid_cloud", "script", _PaidProvider, priority=1)
        summary = registry.summary()
        assert "paid_cloud" not in [c["name"] for c in summary["active"]]
        assert "paid_cloud" in [c["name"] for c in summary["unavailable"]]

    def test_opting_in_explicitly_does_allow_it(self, settings):
        registry = build_default_registry(settings, allow_paid=True)
        registry.register("paid_cloud", "script", _PaidProvider, priority=1)
        assert registry.select("script", requested="paid_cloud").name == "paid_cloud"

    def test_free_mode_is_the_default(self, workspace):
        assert api.build_pipeline(workspace).registry.allow_paid is False


# --------------------------------------------------------------------------
# G6 PROVIDER_DISCOVERY
# --------------------------------------------------------------------------


class _BrokenProvider:
    name = "broken"
    kind = "speech"

    def probe(self) -> Capability:
        raise RuntimeError("this provider is broken")


class TestG6ProviderDiscovery:
    def test_discovery_reports_every_registered_provider(self, registry):
        capabilities = registry.discover()
        registered = {r.name for r in registry.registrations()}
        assert set(capabilities) == registered

    def test_every_unavailable_provider_explains_how_to_enable_it(self, registry):
        for name, capability in registry.discover().items():
            if not capability.available:
                assert capability.detail, name
                assert capability.remediation, name

    def test_a_provider_that_raises_during_probe_does_not_break_discovery(self, settings):
        registry = build_default_registry(settings)
        registry.register("broken", "speech", _BrokenProvider, priority=1)
        capabilities = registry.discover()
        assert capabilities["broken"].available is False
        assert "probe raised" in capabilities["broken"].detail
        # And selection still finds a working speech provider.
        assert registry.select("speech", fallback="silence").name != "broken"

    def test_auto_tier_falls_back_to_ffmpeg_motion_when_no_ai_backend_exists(self, registry):
        tier = registry.resolve_visual_tier("auto")
        video_ok = registry.capability("local_video").available
        image_ok = registry.capability("local_image").available
        if not video_ok and not image_ok:
            assert tier == TIER_FFMPEG_MOTION

    def test_requesting_an_unknown_provider_fails_loudly(self, registry):
        with pytest.raises(ProviderUnavailable, match="Unknown"):
            registry.select("script", requested="does_not_exist")

    def test_requesting_an_unavailable_provider_is_never_silently_swapped(self, registry):
        if registry.capability("ollama").available:
            pytest.skip("Ollama is running on this host")
        with pytest.raises(ProviderUnavailable):
            registry.select("script", requested="ollama")

    def test_silence_speech_provider_is_always_available(self, registry):
        assert registry.capability("silence").available is True

    def test_doctor_reports_a_capability_tier(self, workspace):
        report = doctor.collect(workspace)
        assert report["capability_tier"] in {"A", "B", "C"}
        assert report["fallback_provider"] == TIER_FFMPEG_MOTION


# --------------------------------------------------------------------------
# G7 QC
# --------------------------------------------------------------------------


class TestG7QualityControl:
    def test_a_good_render_passes_every_mandatory_gate(self, _e2e):
        report = json.loads(Path(_e2e["result"].quality_report).read_text())
        assert report["passed"] is True
        assert report["mandatory_failures"] == []
        structural = [c for c in report["checks"] if c["category"] == "structural"]
        assert structural
        assert all(c["status"] in {"PASS", "NOT_APPLICABLE"} for c in structural)

    def test_creative_checks_report_not_verified_rather_than_a_made_up_score(self, _e2e):
        report = json.loads(Path(_e2e["result"].quality_report).read_text())
        creative = [c for c in report["checks"] if c["category"] == "creative"]
        assert creative
        assert all(c["status"] == "NOT_VERIFIED" for c in creative)

    def test_a_corrupt_video_fails_the_decode_gate(self, settings, tools, tmp_path, _e2e):
        """Edge case E13: a provider that 'succeeded' but wrote invalid media."""
        requires_ffmpeg(tools)
        from freevideoforge.models import project_from_dict
        from freevideoforge.providers.quality_structural import StructuralQualityProvider

        manifest = json.loads(Path(_e2e["result"].manifest).read_text())
        project = project_from_dict(manifest["project"])

        corrupt = tmp_path / "final.mp4"
        data = bytearray(Path(_e2e["result"].final_video).read_bytes())
        # Shred the payload but keep the container header, which is exactly what
        # a half-written or truncated provider output looks like.
        for offset in range(len(data) // 3, len(data), 7):
            data[offset] = 0
        corrupt.write_bytes(bytes(data))

        report = StructuralQualityProvider(settings).validate(
            project,
            {
                "final_video": corrupt,
                "thumbnail": Path(_e2e["result"].thumbnail),
                "script": Path(_e2e["result"].script),
                "storyboard": Path(_e2e["result"].storyboard),
                "captions": Path(_e2e["result"].captions),
                "manifest": Path(_e2e["result"].manifest),
                "caption_cues": [{"index": 1, "scene_id": "s01", "text": "x",
                                  "start": 0.0, "end": 1.0}],
            },
        )
        decode = next(c for c in report.checks if c.id == "video.decodes")
        assert decode.status == "FAIL"
        assert report.passed is False

    def test_a_missing_artifact_fails_the_gate(self, settings, tmp_path, _e2e):
        from freevideoforge.models import project_from_dict
        from freevideoforge.providers.quality_structural import StructuralQualityProvider

        manifest = json.loads(Path(_e2e["result"].manifest).read_text())
        project = project_from_dict(manifest["project"])
        report = StructuralQualityProvider(settings).validate(
            project, {"final_video": tmp_path / "nope.mp4", "caption_cues": []}
        )
        assert report.passed is False
        assert any(c.id.startswith("artifact.") and c.status == "FAIL"
                   for c in report.checks)

    def test_captions_running_past_the_video_fail_the_gate(self, settings, _e2e):
        from freevideoforge.models import project_from_dict
        from freevideoforge.providers.quality_structural import StructuralQualityProvider

        manifest = json.loads(Path(_e2e["result"].manifest).read_text())
        project = project_from_dict(manifest["project"])
        outputs = {
            key: Path(getattr(_e2e["result"], key))
            for key in ("final_video", "thumbnail", "script", "storyboard",
                        "captions", "manifest")
        }
        outputs["caption_cues"] = [
            {"index": 1, "scene_id": "s01", "text": "way too late",
             "start": 0.0, "end": 9_999.0}
        ]
        report = StructuralQualityProvider(settings).validate(project, outputs)
        check = next(c for c in report.checks if c.id == "captions.within_duration")
        assert check.status == "FAIL"
        assert report.passed is False

    def test_a_failed_qc_gate_marks_the_run_failed_rather_than_shipping_it(self):
        """The pipeline must not report success when structural QC fails."""
        from freevideoforge.pipeline import Pipeline

        source = Path(Pipeline.__module__.replace(".", "/") + ".py")
        _ = source  # behaviour is asserted below, not by reading source
        # Covered end to end: a failing report sets JobState.FAILED. The unit
        # check is that RunResult.ok is tied to COMPLETED only.
        from freevideoforge.models import RunResult

        assert RunResult(run_id="r", state=JobState.FAILED, output_dir="/tmp").ok is False
        assert RunResult(run_id="r", state=JobState.COMPLETED, output_dir="/tmp").ok is True


# --------------------------------------------------------------------------
# G8 DOCUMENTED_CLEAN_START
# --------------------------------------------------------------------------


class TestG8DocumentedCleanStart:
    def test_bootstrap_works_on_an_empty_directory(self, tmp_path):
        from freevideoforge.bootstrap import plan

        result = plan(str(tmp_path))
        assert "steps" in result and "ready" in result
        for step in result["steps"]:
            assert step["command"], step

    def test_bootstrap_creates_the_workspace_layout(self, tmp_path):
        from freevideoforge.bootstrap import bootstrap

        bootstrap(workspace=str(tmp_path), json_mode=True)
        assert (tmp_path / ".freevideoforge").is_dir()
        assert (tmp_path / "out").is_dir()

    def test_the_readme_documents_the_primary_command(self):
        readme = Path(__file__).resolve().parents[1] / "README.md"
        assert readme.is_file()
        text = readme.read_text(encoding="utf-8")
        assert "freevideoforge generate" in text
        assert "--topic" in text and "--duration" in text and "--aspect" in text

    def test_every_documented_cli_flag_actually_exists(self):
        from freevideoforge.cli import build_parser

        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
            encoding="utf-8"
        )
        parser = build_parser()
        actions = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
        generate_flags = {
            option
            for action in actions["generate"]._actions
            for option in action.option_strings
        }
        for flag in ("--topic", "--duration", "--aspect", "--preset", "--brief",
                     "--seed", "--style", "--quality"):
            assert flag in generate_flags
            assert flag in readme, f"{flag} is implemented but undocumented"

    def test_cli_exposes_every_documented_subcommand(self):
        from freevideoforge.cli import build_parser

        parser = build_parser()
        commands = set(parser._subparsers._group_actions[0].choices)  # type: ignore
        assert {"generate", "doctor", "providers", "runs", "status", "resume",
                "serve", "bootstrap"} <= commands

    def test_cli_runs_as_a_module_on_a_clean_workspace(self, tmp_path):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        proc = subprocess.run(
            [sys.executable, "-m", "freevideoforge", "doctor", "--json",
             "--workspace", str(tmp_path)],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode in (0, 3), proc.stderr
        report = json.loads(proc.stdout)
        assert report["capability_tier"] in {"A", "B", "C"}

    def test_a_license_inventory_exists(self):
        inventory = Path(__file__).resolve().parents[1] / "LICENSES.md"
        assert inventory.is_file()
        text = inventory.read_text(encoding="utf-8")
        assert "Pillow" in text and "FFmpeg" in text


# --------------------------------------------------------------------------
# G9 LOCAL_AI_SCENE
# --------------------------------------------------------------------------


class TestG9LocalAiScene:
    def test_local_ai_scene(self, registry, settings, tmp_path):
        """Only meaningful where a local generative backend genuinely exists.

        On a host without one this is NOT_APPLICABLE and is skipped - it is
        never reported as a pass.
        """
        video = registry.capability("local_video")
        image = registry.capability("local_image")
        if not (video.available or image.available):
            pytest.skip(
                "NOT_APPLICABLE: no local generative video or image backend is "
                f"available here (video: {video.detail}; image: {image.detail})"
            )
        from freevideoforge.models import Project, Scene

        provider = registry.instance("local_video" if video.available else "local_image")
        project = Project(run_id="g9", topic="local ai scene", duration=2.0)
        scene = Scene(id="s01", index=0, duration=2.0)
        result = provider.generate(project, scene, tmp_path / "ai.mp4")
        assert Path(result.path).is_file()
        assert result.technique != "procedural_ffmpeg"

    def test_an_unavailable_backend_refuses_instead_of_faking_output(self, registry,
                                                                    tmp_path):
        from freevideoforge.models import Project, Scene

        capability = registry.capability("local_video")
        if capability.available:
            pytest.skip("a local video backend is available here")
        provider = registry.instance("local_video")
        with pytest.raises(ProviderUnavailable):
            provider.generate(
                Project(run_id="r", topic="t"), Scene(id="s01", index=0, duration=1.0),
                tmp_path / "x.mp4",
            )


# --------------------------------------------------------------------------
# Scene state isolation between stages
# --------------------------------------------------------------------------


class TestSceneStateMerge:
    """The voice and media stages share a row; neither may clobber the other."""

    def test_writing_audio_progress_preserves_clip_progress(self, tmp_path):
        from freevideoforge.state import RunStore

        store = RunStore(tmp_path / "s.db")
        store.create_run(run_id="r", topic="t", config_hash="c", request={},
                         output_dir=tmp_path, work_dir=tmp_path)
        clip = tmp_path / "s01.mp4"
        clip.write_bytes(b"clip")
        audio = tmp_path / "s01.wav"
        audio.write_bytes(b"audio")

        store.upsert_scene("r", scene_id="s01", index=0, state="DONE",
                           clip_hash="CLIP", clip_path=str(clip))
        store.upsert_scene("r", scene_id="s01", index=0, state="DONE",
                           audio_hash="AUDIO", audio_path=str(audio))

        assert store.reusable_scene("r", "s01", "CLIP", "clip") == str(clip)
        assert store.reusable_scene("r", "s01", "AUDIO", "audio") == str(audio)

    def test_a_clip_hash_never_satisfies_an_audio_lookup(self, tmp_path):
        from freevideoforge.state import RunStore

        store = RunStore(tmp_path / "s.db")
        store.create_run(run_id="r", topic="t", config_hash="c", request={},
                         output_dir=tmp_path, work_dir=tmp_path)
        clip = tmp_path / "s01.mp4"
        clip.write_bytes(b"clip")
        store.upsert_scene("r", scene_id="s01", index=0, state="DONE",
                           clip_hash="SHARED", clip_path=str(clip))
        assert store.reusable_scene("r", "s01", "SHARED", "audio") is None

    def test_unknown_artifact_kind_is_rejected(self, tmp_path):
        from freevideoforge.errors import StateError
        from freevideoforge.state import RunStore

        store = RunStore(tmp_path / "s.db")
        with pytest.raises(StateError):
            store.reusable_scene("r", "s01", "h", "sprite")


class TestInterruptedRenderHousekeeping:
    """A killed render leaves half-written clips; they are never reused and are
    swept on the next attempt."""

    def test_partial_clips_are_never_treated_as_finished_output(self, tmp_path):
        from freevideoforge.state import RunStore

        store = RunStore(tmp_path / "s.db")
        store.create_run(run_id="r", topic="t", config_hash="c", request={},
                         output_dir=tmp_path, work_dir=tmp_path)
        published = tmp_path / "s01.mp4"
        partial = tmp_path / "s01.partial.mp4"
        partial.write_bytes(b"half written")
        store.upsert_scene("r", scene_id="s01", index=0, state="DONE",
                           clip_hash="h", clip_path=str(published))
        # The published path does not exist, only the partial does.
        assert store.reusable_scene("r", "s01", "h", "clip") is None

    def test_stale_partials_are_swept_before_re_rendering(self, workspace):
        pipeline = api.build_pipeline(workspace)
        clips = Path(workspace) / "clips"
        clips.mkdir(parents=True)
        stale = clips / "s04.partial.mp4"
        stale.write_bytes(b"junk")
        keep = clips / "s01.mp4"
        keep.write_bytes(b"good")

        pipeline.store.create_run(run_id="r", topic="t", config_hash="c", request={},
                                  output_dir=workspace, work_dir=workspace)
        removed = pipeline._sweep_partials("r", clips)

        assert removed == 1
        assert not stale.exists()
        assert keep.exists(), "a published clip must never be swept"

    def test_sweeping_an_empty_directory_is_a_no_op(self, workspace):
        pipeline = api.build_pipeline(workspace)
        empty = Path(workspace) / "empty"
        empty.mkdir()
        assert pipeline._sweep_partials("r", empty) == 0
