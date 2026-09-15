"""The mandatory renderer: procedural composition + FFmpeg encoding.

This provider is the floor of the whole system. It depends on Pillow and an
ffmpeg binary, and on nothing else - no GPU, no model, no network, no
credential. Every acceptance criterion the project makes about running on a
bare CPU rests on this file.

What it produces is honestly labelled ``technique="procedural_ffmpeg"``. It is
designed, typographic motion graphics, not diffusion video, and the manifest
says so.

Rendering strategy
------------------
Frames are generated in Python and streamed to ffmpeg over a pipe as raw RGB24,
one scene at a time. Streaming rather than writing PNG sequences keeps temp
storage bounded, and per-scene clips are what make the run resumable and
idempotent: a scene whose input hash is unchanged is reused, never re-rendered.

Transitions are baked into each clip as a fade to the scene's own background,
rather than using ffmpeg's ``xfade``. ``xfade`` overlaps clips, which shortens
total duration and would shift every caption downstream of it; baking the fade
keeps scene durations exact and keeps caption timing honest.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Optional, Sequence

from ..errors import DependencyError, RenderError
from ..ffmpeg import FFTools
from ..models import Project, Scene
from ..visuals.fonts import FontBook
from ..visuals.frames import CaptionCue, SceneFrameRenderer, render_thumbnail
from ..visuals.palette import Palette
from .base import Capability, MediaResult

#: Font role per style system. Keeps the type voice consistent with the palette.
STYLE_FONT = {
    "serif_display": "display_bold",
    "grotesque": "sans_bold",
}


class FFmpegMotionRenderProvider:
    """Deterministic CPU renderer. Always the fallback, never optional."""

    name = "ffmpeg_motion"
    kind = "render"

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self.tools = FFTools(
            getattr(settings, "ffmpeg_path", None), getattr(settings, "ffprobe_path", None)
        )
        self.fonts = FontBook(getattr(settings, "font_dirs", ()) or ())

    # -- capability ------------------------------------------------------
    def probe(self) -> Capability:
        try:
            from PIL import Image  # noqa: F401
            pillow = True
        except ImportError:
            pillow = False

        if not pillow:
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail="Pillow is not installed.",
                remediation="pip install pillow",
            )
        if not self.tools.ffmpeg:
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail="No ffmpeg binary was found.",
                remediation=(
                    "Install FFmpeg:\n"
                    "  Debian/Ubuntu : sudo apt-get install -y ffmpeg\n"
                    "  macOS         : brew install ffmpeg\n"
                    "  Windows       : winget install Gyan.FFmpeg\n"
                    "  Any platform  : pip install imageio-ffmpeg"
                ),
            )
        font = self.fonts.path("display_bold")
        return Capability(
            available=True, name=self.name, kind=self.kind,
            detail="Procedural motion-graphics renderer. CPU only, no model, no network.",
            version=self.tools.version("ffmpeg"),
            metadata={
                "ffmpeg": self.tools.ffmpeg,
                "ffprobe": self.tools.ffprobe,
                "technique": "procedural_ffmpeg",
                "display_font": font,
                "font_degraded": font is None,
                "has_libx264": self.tools.has_encoder("libx264"),
            },
        )

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def palette_for(project: Project, scene: Scene) -> Palette:
        colours = scene.visual.palette or [
            "#0B1020", "#161E38", "#F5C451", "#F7F5EF", "#8E9BB7"
        ]
        return Palette(colours)

    def _style_font(self, project: Project) -> str:
        from .storyboard_planner import STYLE_SYSTEMS

        stack = STYLE_SYSTEMS.get(project.style_system, {}).get("font_stack", "serif_display")
        return STYLE_FONT.get(stack, "display_bold")

    # -- scene rendering -------------------------------------------------
    def render_scene(
        self,
        project: Project,
        scene: Scene,
        output: Path,
        *,
        captions: Sequence[dict] = (),
        timeout: float = 900.0,
    ) -> MediaResult:
        """Render one scene to a silent MP4 clip."""
        self.tools.require_ffmpeg()
        render = project.render
        cues = [
            CaptionCue(
                start=float(cue.get("scene_start", 0.0)),
                end=float(cue.get("scene_end", 0.0)),
                text=str(cue.get("text", "")),
            )
            for cue in captions
            if cue.get("scene_id") == scene.id
        ]

        renderer = SceneFrameRenderer(
            scene,
            width=render.width,
            height=render.height,
            fps=render.fps,
            palette=self.palette_for(project, scene),
            fonts=self.fonts,
            style_font=self._style_font(project),
            captions=cues,
            burn_captions=render.burn_captions,
            is_first=scene.index == 0,
            is_last=scene.index == len(project.scenes) - 1,
        )

        # The temp name keeps the real extension: ffmpeg picks its muxer from
        # the output suffix, and "foo.mp4.partial" gives it nothing to go on.
        tmp_output = output.with_name(f"{output.stem}.partial{output.suffix}")
        process = self.tools.encode_from_rgb_stream(
            width=render.width,
            height=render.height,
            fps=render.fps,
            output=tmp_output,
            crf=render.crf,
            preset=render.preset,
            pix_fmt=render.pixel_format,
            codec=render.video_codec,
        )
        assert process.stdin is not None
        frames_written = 0
        try:
            for frame in renderer.frames():
                process.stdin.write(frame.tobytes())
                frames_written += 1
        except BrokenPipeError as exc:
            stderr = (process.stderr.read() if process.stderr else b"").decode(
                "utf-8", "replace"
            )
            raise RenderError(f"ffmpeg closed the pipe for {scene.id}: {stderr}") from exc
        finally:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        try:
            returncode = process.wait(timeout=timeout)
        except Exception as exc:
            process.kill()
            raise RenderError(f"Encoding scene {scene.id} timed out") from exc

        stderr = (process.stderr.read() if process.stderr else b"").decode("utf-8", "replace")
        if returncode != 0:
            raise RenderError(f"ffmpeg exited {returncode} on {scene.id}:\n{stderr.strip()}")
        if not tmp_output.exists() or tmp_output.stat().st_size == 0:
            raise RenderError(f"ffmpeg produced no output for {scene.id}")

        # Atomic publish: a half-written clip must never look reusable to a
        # resumed run.
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_output), str(output))

        return MediaResult(
            path=output,
            provider=self.name,
            technique="procedural_ffmpeg",
            duration=frames_written / float(render.fps),
            seed=scene.seed,
            model=None,
            metadata={
                "frames": frames_written,
                "motif": scene.visual.motif,
                "motion": scene.motion.motion,
                "captions_burned": bool(render.burn_captions and cues),
            },
        )

    def render_thumbnail(self, project: Project, output: Path, title: str) -> Path:
        """A purpose-built title card rather than a frame grab."""
        if not project.scenes:
            raise RenderError("Cannot build a thumbnail without scenes")
        scene = project.scenes[0]
        image = render_thumbnail(
            scene,
            width=project.render.width,
            height=project.render.height,
            palette=self.palette_for(project, scene),
            fonts=self.fonts,
            title=title,
            style_font=self._style_font(project),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="JPEG", quality=92, optimize=True, progressive=True)
        return output

    # -- audio -----------------------------------------------------------
    def build_audio_bed(
        self,
        project: Project,
        voice_tracks: list[tuple[Path, float, float]],
        output: Path,
        *,
        music: str = "ambient",
        total_duration: float,
    ) -> Optional[Path]:
        """Mix per-scene narration onto the timeline, with an optional pad.

        ``voice_tracks`` is ``[(wav_path, start_seconds, scene_duration), ...]``.
        The music bed is synthesised by ffmpeg from sine sources, so it needs no
        asset library and carries no licence question.
        """
        ffmpeg = self.tools.require_ffmpeg()
        if not voice_tracks and music == "none":
            return None

        rate = project.render.audio_sample_rate
        inputs: list[str] = []
        filters: list[str] = []
        mix_labels: list[str] = []

        for index, (path, start, _duration) in enumerate(voice_tracks):
            inputs.extend(["-i", str(path)])
            delay_ms = max(0, int(round(start * 1000)))
            filters.append(
                f"[{index}:a]aformat=sample_fmts=fltp:sample_rates={rate}:"
                f"channel_layouts=stereo,adelay={delay_ms}|{delay_ms},"
                f"volume=1.0[v{index}]"
            )
            mix_labels.append(f"[v{index}]")

        voice_label = None
        if mix_labels:
            if len(mix_labels) == 1:
                filters.append(f"{mix_labels[0]}anull[voice]")
            else:
                filters.append(
                    f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:"
                    f"duration=longest:normalize=0[voice]"
                )
            voice_label = "[voice]"

        music_label = None
        if music == "ambient":
            # Two detuned sines and a slow tremolo: a neutral pad that sits
            # under speech without competing with it.
            base = 110.0
            inputs.extend([
                "-f", "lavfi", "-t", f"{total_duration:.3f}",
                "-i", f"sine=frequency={base:.2f}:sample_rate={rate}",
                "-f", "lavfi", "-t", f"{total_duration:.3f}",
                "-i", f"sine=frequency={base * 1.5:.2f}:sample_rate={rate}",
            ])
            a = len(voice_tracks)
            b = a + 1
            filters.append(
                f"[{a}:a][{b}:a]amix=inputs=2:duration=longest:normalize=0,"
                f"aformat=sample_fmts=fltp:sample_rates={rate}:channel_layouts=stereo,"
                f"lowpass=f=900,tremolo=f=0.18:d=0.35,volume=0.055,"
                f"afade=t=in:st=0:d=1.2,"
                f"afade=t=out:st={max(0.0, total_duration - 1.6):.3f}:d=1.6[music]"
            )
            music_label = "[music]"

        if voice_label and music_label:
            filters.append(f"{voice_label}{music_label}amix=inputs=2:duration=first:"
                           f"normalize=0[mixed]")
            final = "[mixed]"
        elif voice_label:
            final = voice_label
        elif music_label:
            final = music_label
        else:
            return None

        # Gentle limiting keeps the master well under 0 dBFS so the QC peak
        # check is meaningful rather than theatrical.
        filters.append(
            f"{final}alimiter=limit=0.89,"
            f"apad=whole_dur={total_duration:.3f},atrim=0:{total_duration:.3f},"
            f"aformat=sample_fmts=fltp:sample_rates={rate}:channel_layouts=stereo[out]"
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            *inputs,
            "-filter_complex", ";".join(filters),
            "-map", "[out]",
            "-c:a", "pcm_s16le",
            str(output),
        ]
        from ..ffmpeg import run

        run(argv, timeout=600.0)
        if not output.exists() or output.stat().st_size == 0:
            raise RenderError("Audio bed rendering produced no output")
        return output

    # -- composition -----------------------------------------------------
    def compose(
        self,
        project: Project,
        *,
        clips: list[Path],
        audio: Optional[Path],
        output: Path,
    ) -> MediaResult:
        """Concatenate scene clips and mux the audio bed."""
        from ..ffmpeg import run

        ffmpeg = self.tools.require_ffmpeg()
        if not clips:
            raise RenderError("Nothing to compose: no scene clips were produced")
        for clip in clips:
            if not Path(clip).exists() or Path(clip).stat().st_size == 0:
                raise RenderError(f"Missing or empty scene clip: {clip}")

        output.parent.mkdir(parents=True, exist_ok=True)
        concat_list = output.parent / f".{output.stem}.concat.txt"
        # Paths are quoted for ffmpeg's concat demuxer, not for a shell; the
        # command itself is still an argv list.
        concat_list.write_text(
            "".join(f"file '{Path(clip).resolve().as_posix()}'\n" for clip in clips),
            encoding="utf-8",
        )

        tmp_output = output.with_name(f"{output.stem}.partial{output.suffix}")
        argv = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
        ]
        if audio and Path(audio).exists():
            argv.extend(["-i", str(audio)])
        argv.extend(["-c:v", "copy", "-map", "0:v:0"])
        if audio and Path(audio).exists():
            argv.extend([
                "-map", "1:a:0",
                "-c:a", project.render.audio_codec,
                "-b:a", project.render.audio_bitrate,
                "-ar", str(project.render.audio_sample_rate),
                "-shortest",
            ])
        else:
            argv.append("-an")
        argv.extend(["-movflags", "+faststart", str(tmp_output)])

        try:
            run(argv, timeout=900.0)
        finally:
            concat_list.unlink(missing_ok=True)

        if not tmp_output.exists() or tmp_output.stat().st_size == 0:
            raise RenderError("Composition produced no output file")
        shutil.move(str(tmp_output), str(output))

        duration = 0.0
        if self.tools.ffprobe:
            try:
                duration = self.tools.duration(output)
            except (RenderError, DependencyError):
                duration = 0.0
        if not duration:
            duration = sum(scene.duration for scene in project.scenes)

        return MediaResult(
            path=output,
            provider=self.name,
            technique="procedural_ffmpeg",
            duration=duration,
            metadata={
                "scene_clips": len(clips),
                "has_audio": bool(audio and Path(audio).exists()),
                "concat_mode": "demuxer_copy",
            },
        )

    @staticmethod
    def estimate_frames(project: Project) -> int:
        return int(math.ceil(sum(s.duration for s in project.scenes) * project.render.fps))
