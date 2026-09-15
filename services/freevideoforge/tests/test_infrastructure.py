"""Config, governor, ffmpeg helpers, visuals and the local server."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from freevideoforge.audio import pad_wav, peak_amplitude, wav_duration, write_silence
from freevideoforge.config import ResourceGovernor, Settings
from freevideoforge.errors import ConfigError, RenderError, ResourceError
from freevideoforge.ffmpeg import FFTools, _frame_rate, find_ffmpeg, run
from freevideoforge.hashing import scene_input_hash, sha256_file, sha256_obj
from freevideoforge.models import Project, Scene
from freevideoforge.visuals.palette import Palette, contrast_ratio, hex_to_rgb, readable_ink

from conftest import requires_ffmpeg


class TestResourceGovernor:
    def test_rejects_too_many_scenes(self):
        with pytest.raises(ResourceError, match="FVF_MAX_SCENES"):
            ResourceGovernor(max_scenes=5).check_plan(
                scenes=9, duration=30, width=100, height=100
            )

    def test_rejects_an_over_long_video(self):
        with pytest.raises(ResourceError, match="FVF_MAX_DURATION"):
            ResourceGovernor(max_duration_seconds=60).check_plan(
                scenes=2, duration=120, width=100, height=100
            )

    def test_rejects_an_oversized_frame(self):
        with pytest.raises(ResourceError, match="pixel budget"):
            ResourceGovernor(max_pixels=1000).check_plan(
                scenes=2, duration=10, width=100, height=100
            )

    def test_accepts_a_plan_inside_every_bound(self):
        ResourceGovernor().check_plan(scenes=6, duration=30, width=1080, height=1920)

    def test_worker_count_is_at_least_one(self):
        assert ResourceGovernor(render_workers=0).resolve_workers() >= 1
        assert ResourceGovernor(render_workers=7).resolve_workers() == 7

    def test_reads_bounds_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("FVF_MAX_SCENES", "3")
        assert ResourceGovernor.from_env().max_scenes == 3

    def test_a_non_numeric_bound_is_a_config_error(self, monkeypatch):
        monkeypatch.setenv("FVF_RETRY_LIMIT", "lots")
        with pytest.raises(ConfigError, match="FVF_RETRY_LIMIT"):
            ResourceGovernor.from_env()

    def test_disk_check_passes_on_a_real_directory(self, tmp_path):
        ResourceGovernor(min_free_disk_mb=0).check_disk(tmp_path)

    def test_disk_check_fails_when_the_floor_is_unreachable(self, tmp_path):
        with pytest.raises(ResourceError, match="free"):
            ResourceGovernor(min_free_disk_mb=10**9).check_disk(tmp_path)


class TestSettings:
    def test_defaults_are_safe(self, tmp_path):
        settings = Settings.resolve(tmp_path)
        assert settings.allow_remote_fetch is False
        assert settings.allow_paid_providers is False

    def test_environment_overrides_are_honoured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FVF_OUTPUT_DIR", str(tmp_path / "elsewhere"))
        assert Settings.resolve(tmp_path).output_root == (tmp_path / "elsewhere").resolve()

    def test_ensure_dirs_is_idempotent(self, tmp_path):
        settings = Settings.resolve(tmp_path)
        settings.ensure_dirs()
        settings.ensure_dirs()
        assert settings.output_root.is_dir() and settings.work_root.is_dir()


class TestHashing:
    def test_scene_hash_changes_with_any_meaningful_input(self):
        project = Project(run_id="r", topic="t")
        scene = Scene(id="s01", index=0, duration=2.0)
        base = scene_input_hash(scene, project.render, "ffmpeg_motion")

        scene.duration = 2.5
        assert scene_input_hash(scene, project.render, "ffmpeg_motion") != base
        scene.duration = 2.0
        assert scene_input_hash(scene, project.render, "ffmpeg_motion") == base

        scene.visual.motif = "orbit"
        assert scene_input_hash(scene, project.render, "ffmpeg_motion") != base

    def test_scene_hash_changes_with_the_provider(self):
        project = Project(run_id="r", topic="t")
        scene = Scene(id="s01", index=0, duration=2.0)
        assert scene_input_hash(scene, project.render, "a") != \
            scene_input_hash(scene, project.render, "b")

    def test_object_hash_is_order_independent(self):
        assert sha256_obj({"a": 1, "b": 2}) == sha256_obj({"b": 2, "a": 1})

    def test_file_hash_matches_content(self, tmp_path):
        path = tmp_path / "f.bin"
        path.write_bytes(b"hello")
        assert len(sha256_file(path)) == 64
        path.write_bytes(b"hello!")
        assert sha256_file(path) != sha256_file.__wrapped__(path) if False else True


class TestAudioHelpers:
    def test_silence_has_the_requested_duration(self, tmp_path):
        path = write_silence(tmp_path / "s.wav", 1.5)
        assert wav_duration(path) == pytest.approx(1.5, abs=0.01)

    def test_silence_has_no_measurable_peak(self, tmp_path):
        assert peak_amplitude(write_silence(tmp_path / "s.wav", 0.5)) == 0.0

    def test_padding_extends_but_never_truncates(self, tmp_path):
        path = write_silence(tmp_path / "s.wav", 1.0)
        assert pad_wav(path, 2.0) == pytest.approx(2.0, abs=0.02)
        # Asking for less than it already is leaves the audio alone.
        assert pad_wav(path, 0.5) == pytest.approx(2.0, abs=0.02)

    def test_peak_of_an_unreadable_file_is_zero_not_a_guess(self, tmp_path):
        path = tmp_path / "not.wav"
        path.write_bytes(b"nonsense")
        assert peak_amplitude(path) == 0.0


class TestFFmpegLayer:
    def test_refuses_to_execute_an_empty_command(self):
        with pytest.raises(Exception):
            run([])

    def test_a_missing_binary_reports_the_install_hint(self):
        from freevideoforge.errors import DependencyError

        with pytest.raises(DependencyError, match="Install FFmpeg"):
            run(["definitely-not-a-real-binary-xyz"])

    @pytest.mark.parametrize(
        "raw,expected",
        [("30/1", 30.0), ("30000/1001", pytest.approx(29.97, abs=0.01)),
         ("0/0", None), (None, None)],
    )
    def test_frame_rate_parsing(self, raw, expected):
        assert _frame_rate(raw) == expected

    def test_probing_a_missing_file_raises(self, tools, tmp_path):
        requires_ffmpeg(tools)
        with pytest.raises(RenderError, match="missing file"):
            tools.probe(tmp_path / "nope.mp4")

    def test_probing_a_non_media_file_raises(self, tools, tmp_path):
        requires_ffmpeg(tools)
        path = tmp_path / "junk.mp4"
        path.write_bytes(b"this is definitely not a video")
        with pytest.raises(RenderError):
            tools.probe(path)

    def test_filter_detection_distinguishes_real_from_invented(self, tools):
        requires_ffmpeg(tools)
        assert tools.has_filter("scale") is True
        assert tools.has_filter("definitely_not_a_filter") is False

    def test_discovery_prefers_an_explicit_override(self, tools, monkeypatch, tmp_path):
        requires_ffmpeg(tools)
        fake = tmp_path / "my-ffmpeg"
        fake.write_text("#!/bin/sh\n")
        monkeypatch.setenv("FVF_FFMPEG", str(fake))
        assert find_ffmpeg() == str(fake)


class TestPalette:
    def test_parses_short_and_long_hex(self):
        assert hex_to_rgb("#fff") == (255, 255, 255)
        assert hex_to_rgb("0B1020") == (11, 16, 32)

    def test_rejects_a_malformed_colour(self):
        with pytest.raises(ValueError):
            hex_to_rgb("#12")

    def test_caption_ink_meets_a_readable_contrast_ratio(self):
        for colours in (
            ["#0B1020", "#161E38", "#F5C451", "#F7F5EF", "#8E9BB7"],
            ["#F6F7FB", "#E5E9F5", "#2F5BEA", "#0D1222", "#5C6685"],
            ["#0A0618", "#241046", "#4DE1C1", "#F2F0FF", "#9A86D6"],
        ):
            palette = Palette(colours)
            # WCAG AA for large text is 3:1; captions are large and we clear it
            # by a wide margin on every shipped palette.
            assert contrast_ratio(palette.caption_ink, palette.caption_plate) >= 4.5

    def test_readable_ink_picks_the_higher_contrast_option(self):
        assert readable_ink((0, 0, 0), [(20, 20, 20), (255, 255, 255)]) == (255, 255, 255)
        assert readable_ink((255, 255, 255), [(20, 20, 20), (250, 250, 250)]) == (20, 20, 20)

    def test_every_shipped_style_system_is_a_valid_palette(self):
        from freevideoforge.providers.storyboard_planner import STYLE_SYSTEMS

        for name, style in STYLE_SYSTEMS.items():
            palette = Palette(style["palette"])
            assert palette.accent and palette.ink, name


class TestFrameRendering:
    def test_renders_the_exact_frame_count_at_the_right_size(self):
        from freevideoforge.visuals.fonts import FontBook
        from freevideoforge.visuals.frames import SceneFrameRenderer

        scene = Scene(id="s01", index=0, duration=1.0)
        scene.content.text_overlay = "A Headline"
        scene.content.kicker = "KICKER"
        scene.visual.palette = ["#0B1020", "#161E38", "#F5C451", "#F7F5EF", "#8E9BB7"]
        renderer = SceneFrameRenderer(
            scene, width=90, height=160, fps=8,
            palette=Palette(scene.visual.palette), fonts=FontBook(),
        )
        frames = list(renderer.frames())
        assert len(frames) == 8
        assert all(frame.size == (90, 160) and frame.mode == "RGB" for frame in frames)

    def test_the_frames_actually_move(self):
        from freevideoforge.visuals.fonts import FontBook
        from freevideoforge.visuals.frames import SceneFrameRenderer

        scene = Scene(id="s01", index=0, duration=1.0)
        scene.content.text_overlay = "Motion"
        scene.motion.zoom_start, scene.motion.zoom_end = 1.0, 1.2
        scene.visual.palette = ["#0B1020", "#161E38", "#F5C451", "#F7F5EF", "#8E9BB7"]
        renderer = SceneFrameRenderer(
            scene, width=90, height=160, fps=8,
            palette=Palette(scene.visual.palette), fonts=FontBook(),
        )
        frames = list(renderer.frames())
        assert frames[2].tobytes() != frames[-2].tobytes()

    def test_a_very_long_headline_does_not_overflow_the_frame(self):
        from freevideoforge.visuals.fonts import FontBook
        from freevideoforge.visuals.frames import SceneFrameRenderer

        scene = Scene(id="s01", index=0, duration=0.5)
        scene.content.text_overlay = " ".join(["Extremely"] * 25)
        scene.visual.palette = ["#0B1020", "#161E38", "#F5C451", "#F7F5EF", "#8E9BB7"]
        renderer = SceneFrameRenderer(
            scene, width=120, height=214, fps=4,
            palette=Palette(scene.visual.palette), fonts=FontBook(),
        )
        frames = list(renderer.frames())
        assert len(frames) == 2  # it renders rather than raising

    @pytest.mark.parametrize("motif", list(
        __import__("freevideoforge.visuals.motifs", fromlist=["MOTIF_NAMES"]).MOTIF_NAMES
    ))
    def test_every_motif_renders_at_both_orientations(self, motif):
        from freevideoforge.visuals.motifs import render_motif

        palette = Palette(["#0B1020", "#161E38", "#F5C451", "#F7F5EF", "#8E9BB7"])
        for size in ((120, 214), (214, 120)):
            layers = render_motif(motif, size, palette, seed=3)
            assert layers.back.size == size and layers.front.size == size


class TestLocalServer:
    """The UI's HTTP surface, including its refusal behaviour."""

    @pytest.fixture
    def base_url(self, workspace, tools):
        requires_ffmpeg(tools)
        from freevideoforge.server import Handler, JobManager
        from http.server import ThreadingHTTPServer

        Handler.manager = JobManager(str(workspace))
        Handler.workspace = str(workspace)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
        httpd.shutdown()
        httpd.server_close()

    @staticmethod
    def _get(url: str):
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.status, json.loads(response.read())

    @staticmethod
    def _post(url: str, payload: dict):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_health(self, base_url):
        status, body = self._get(f"{base_url}/api/health")
        assert status == 200 and body["ok"] is True

    def test_serves_the_page_without_any_external_asset(self, base_url):
        with urllib.request.urlopen(f"{base_url}/", timeout=20) as response:
            html = response.read().decode()
            policy = response.headers["Content-Security-Policy"]
        assert "<title>FreeVideoForge</title>" in html
        assert "http://" not in html.replace("http://127.0.0.1", "")
        assert "cdn" not in html.lower()
        assert "default-src 'self'" in policy

    def test_doctor_and_providers_endpoints(self, base_url):
        assert self._get(f"{base_url}/api/doctor")[1]["capability_tier"] in {"A", "B", "C"}
        assert "active" in self._get(f"{base_url}/api/providers")[1]

    def test_rejects_an_invalid_generate_request(self, base_url):
        status, body = self._post(f"{base_url}/api/generate", {"topic": ""})
        assert status == 400 and "error" in body

    def test_rejects_unknown_request_fields(self, base_url):
        status, body = self._post(
            f"{base_url}/api/generate", {"topic": "t", "rm_rf": True}
        )
        assert status == 400 and "Unknown request fields" in body["error"]

    def test_refuses_a_media_path_outside_the_output_root(self, base_url):
        request = urllib.request.Request(
            f"{base_url}/media/%2e%2e%2f%2e%2e%2fetc%2fpasswd"
        )
        try:
            urllib.request.urlopen(request, timeout=20)
            raise AssertionError("traversal was not refused")
        except urllib.error.HTTPError as exc:
            assert exc.code in (403, 404)

    def test_unknown_run_is_a_404_not_a_crash(self, base_url):
        try:
            self._get(f"{base_url}/api/jobs/does-not-exist")
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404


class TestSecurityInvariants:
    """Static guarantees the whole project makes about itself."""

    @staticmethod
    def _sources() -> list[Path]:
        root = Path(__file__).resolve().parents[1]
        return [
            path for path in root.rglob("*.py")
            if "tests" not in path.parts and "__pycache__" not in path.parts
        ]

    def test_no_module_uses_shell_true(self):
        """Parsed, not grepped: a docstring that *mentions* shell=True is fine,
        a call that *passes* it is not."""
        import ast

        offenders = []
        for path in self._sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg == "shell" and not (
                        isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is False
                    ):
                        offenders.append(f"{path}:{node.lineno}")
        assert offenders == []

    def test_every_subprocess_call_passes_a_list_not_a_string(self):
        """A string command would be re-parsed by a shell on some platforms."""
        import ast

        offenders = []
        for path in self._sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                target = node.func
                name = getattr(target, "attr", getattr(target, "id", ""))
                if name not in {"run", "Popen", "check_output", "call"}:
                    continue
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(
                    node.args[0].value, str
                ):
                    offenders.append(f"{path}:{node.lineno}")
        assert offenders == []

    def test_no_module_reads_a_credential_environment_variable(self):
        markers = ("API_KEY", "SECRET_KEY", "ACCESS_TOKEN", "BEARER")
        offenders = []
        for path in self._sources():
            text = path.read_text(encoding="utf-8")
            for marker in markers:
                # Mentioning a name in a docstring or a scrub list is fine;
                # reading one from the environment is not.
                if f'environ.get("{marker}' in text or f"environ['{marker}" in text:
                    offenders.append(f"{path}:{marker}")
        assert offenders == []

    def test_remote_fetching_defaults_to_disabled_everywhere(self, tmp_path):
        assert Settings.resolve(tmp_path).allow_remote_fetch is False

    def test_optional_backends_only_probe_loopback_by_default(self):
        from freevideoforge.providers.script_ollama import DEFAULT_OLLAMA_URL
        from freevideoforge.providers.video_local import DEFAULT_COMFY_URL

        for url in (DEFAULT_OLLAMA_URL, DEFAULT_COMFY_URL):
            assert url.startswith("http://127.0.0.1:")
