"""Structural quality control.

Structural checks are deterministic and mandatory: schema validity, asset
presence, duration, resolution, aspect, stream presence, full decode, caption
bounds and ordering, audio level sanity.

Creative checks are reported separately and are allowed to say NOT_VERIFIED.
FreeVideoForge does not ship a perceptual evaluator, so it does not invent a
prompt-adherence or visual-coherence score. A check with no reliable evaluator
reports NOT_VERIFIED and is never counted as a pass.

The decode check is what catches edge case E13: a provider that reported
success while writing structurally invalid media.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..audio import peak_amplitude
from ..errors import DependencyError, RenderError
from ..ffmpeg import FFTools
from ..models import Project, QualityCheck, QualityReport
from .base import Capability

#: Fraction of the planned duration the render may drift before failing.
DURATION_TOLERANCE = 0.06
#: Absolute floor, so very short videos are not failed by rounding.
DURATION_TOLERANCE_FLOOR = 0.35
#: A master peaking above this is judged to be clipping.
PEAK_CEILING = 0.995
#: Below this, a track that claims to contain speech is effectively silent.
PEAK_FLOOR = 0.02


class StructuralQualityProvider:
    name = "structural"
    kind = "quality"

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self.tools = FFTools(
            getattr(settings, "ffmpeg_path", None), getattr(settings, "ffprobe_path", None)
        )

    def probe(self) -> Capability:
        return Capability(
            available=bool(self.tools.ffprobe),
            name=self.name,
            kind=self.kind,
            detail=(
                "Deterministic structural validation via ffprobe and a full decode pass."
                if self.tools.ffprobe
                else "ffprobe is required for structural validation and was not found."
            ),
            remediation="Install FFmpeg (which provides ffprobe): "
                        "sudo apt-get install -y ffmpeg",
            version=self.tools.version("ffprobe"),
        )

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _check(check_id: str, status: str, detail: str = "", *,
               expected: Any = None, observed: Any = None,
               category: str = "structural") -> QualityCheck:
        return QualityCheck(
            id=check_id, category=category, status=status, detail=detail,
            expected=expected, observed=observed,
        )

    # -- main ------------------------------------------------------------
    def validate(self, project: Project, outputs: dict[str, Path]) -> QualityReport:
        checks: list[QualityCheck] = []
        add = checks.append

        # --- required artifacts exist and are non-empty ------------------
        required = ("final_video", "thumbnail", "script", "storyboard", "captions",
                    "manifest")
        for key in required:
            path = outputs.get(key)
            if path is None:
                add(self._check(f"artifact.{key}", "FAIL", f"{key} was never produced"))
            elif not Path(path).exists():
                add(self._check(f"artifact.{key}", "FAIL", f"missing file: {path}"))
            elif Path(path).stat().st_size == 0:
                add(self._check(f"artifact.{key}", "FAIL", f"empty file: {path}"))
            else:
                add(self._check(f"artifact.{key}", "PASS",
                                observed=f"{Path(path).stat().st_size} bytes"))

        video_path = outputs.get("final_video")
        planned = round(sum(scene.duration for scene in project.scenes), 3)

        # --- scene sanity -------------------------------------------------
        bad_scenes = [s.id for s in project.scenes if s.duration <= 0]
        add(self._check(
            "scenes.positive_duration",
            "FAIL" if bad_scenes else "PASS",
            f"scenes with non-positive duration: {', '.join(bad_scenes)}"
            if bad_scenes else f"{len(project.scenes)} scenes",
            expected="all > 0", observed=len(project.scenes),
        ))

        if not video_path or not Path(video_path).exists():
            add(self._check("video.probe", "FAIL", "no final video to probe"))
            return QualityReport(run_id=project.run_id, checks=checks + self._creative())

        # --- probe --------------------------------------------------------
        try:
            probe = self.tools.probe(video_path)
        except (RenderError, DependencyError) as exc:
            add(self._check("video.probe", "FAIL", str(exc)))
            return QualityReport(run_id=project.run_id, checks=checks + self._creative())

        add(self._check("video.probe", "PASS", observed=probe.format_name))

        video = probe.video
        if video is None:
            add(self._check("video.stream_present", "FAIL", "no video stream in output"))
        else:
            add(self._check("video.stream_present", "PASS", observed=video.codec_name))

            expected_w, expected_h = project.render.width, project.render.height
            dims_ok = (video.width, video.height) == (expected_w, expected_h)
            add(self._check(
                "video.dimensions", "PASS" if dims_ok else "FAIL",
                expected=f"{expected_w}x{expected_h}",
                observed=f"{video.width}x{video.height}",
                detail="" if dims_ok else "encoded dimensions do not match the render spec",
            ))

            expected_ratio = project.aspect.ratio
            actual_ratio = (video.width / video.height) if video.height else 0.0
            ratio_ok = abs(actual_ratio - expected_ratio) <= 0.02
            add(self._check(
                "video.aspect", "PASS" if ratio_ok else "FAIL",
                expected=f"{project.aspect.value} ({expected_ratio:.4f})",
                observed=f"{actual_ratio:.4f}",
            ))

            fps = video.avg_frame_rate or 0.0
            fps_ok = abs(fps - project.render.fps) <= max(0.5, project.render.fps * 0.02)
            add(self._check(
                "video.fps", "PASS" if fps_ok else "FAIL",
                expected=project.render.fps, observed=round(fps, 3),
            ))

        # --- duration -----------------------------------------------------
        tolerance = max(DURATION_TOLERANCE_FLOOR, planned * DURATION_TOLERANCE)
        drift = abs(probe.duration - planned)
        add(self._check(
            "video.duration", "PASS" if drift <= tolerance else "FAIL",
            f"drift {drift:.3f}s against a {tolerance:.3f}s tolerance",
            expected=f"{planned:.3f}s", observed=f"{probe.duration:.3f}s",
        ))

        # --- audio --------------------------------------------------------
        wants_audio = bool(outputs.get("audio"))
        if wants_audio:
            if probe.audio is None:
                add(self._check("audio.stream_present", "FAIL",
                                "audio was produced but is not present in the output"))
            else:
                add(self._check("audio.stream_present", "PASS",
                                observed=probe.audio.codec_name))
                peak = peak_amplitude(outputs["audio"])
                if peak == 0.0:
                    add(self._check("audio.peak", "NOT_VERIFIED",
                                    "peak could not be measured from this audio format"))
                elif peak < PEAK_FLOOR:
                    add(self._check("audio.peak", "FAIL",
                                    "master is effectively silent",
                                    expected=f">= {PEAK_FLOOR}", observed=round(peak, 4)))
                elif peak > PEAK_CEILING:
                    add(self._check("audio.peak", "FAIL", "master is clipping",
                                    expected=f"<= {PEAK_CEILING}", observed=round(peak, 4)))
                else:
                    add(self._check("audio.peak", "PASS", observed=round(peak, 4)))
        else:
            add(self._check("audio.stream_present", "NOT_APPLICABLE",
                            "this run produced no audio bed"))

        # --- decode -------------------------------------------------------
        ok, stderr = self.tools.decodes(video_path)
        add(self._check(
            "video.decodes", "PASS" if ok else "FAIL",
            "full decode pass succeeded" if ok else stderr[:500],
        ))

        # --- captions -----------------------------------------------------
        checks.extend(self._caption_checks(project, outputs, planned))

        return QualityReport(run_id=project.run_id, checks=checks + self._creative())

    # -- captions --------------------------------------------------------
    def _caption_checks(
        self, project: Project, outputs: dict[str, Path], planned: float
    ) -> list[QualityCheck]:
        cues = outputs.get("caption_cues") or []
        if not isinstance(cues, list) or not cues:
            return [self._check("captions.cues", "FAIL", "no caption cues were produced")]
        out = [self._check("captions.cues", "PASS", observed=len(cues))]

        overruns = [c for c in cues if float(c["end"]) > planned + 0.05]
        out.append(self._check(
            "captions.within_duration", "FAIL" if overruns else "PASS",
            f"{len(overruns)} cue(s) end after the video does" if overruns
            else "all cues land inside the timeline",
            expected=f"end <= {planned:.3f}s",
            observed=round(max(float(c["end"]) for c in cues), 3),
        ))

        inverted = [c for c in cues if float(c["end"]) <= float(c["start"])]
        out.append(self._check(
            "captions.monotonic", "FAIL" if inverted else "PASS",
            f"{len(inverted)} cue(s) end at or before they start" if inverted
            else "every cue has positive length",
        ))

        disordered = [
            (a, b) for a, b in zip(cues, cues[1:])
            if float(b["start"]) < float(a["start"]) - 0.001
        ]
        out.append(self._check(
            "captions.ordered", "FAIL" if disordered else "PASS",
            f"{len(disordered)} out-of-order cue pair(s)" if disordered
            else "cues are in chronological order",
        ))

        empty = [c for c in cues if not str(c.get("text", "")).strip()]
        out.append(self._check(
            "captions.non_empty", "FAIL" if empty else "PASS",
            f"{len(empty)} empty cue(s)" if empty else "no empty cues",
        ))
        return out

    # -- creative --------------------------------------------------------
    @staticmethod
    def _creative() -> list[QualityCheck]:
        """Creative checks.

        FreeVideoForge ships no perceptual evaluator, so these report
        NOT_VERIFIED rather than inventing a score. They exist as named slots so
        an evaluator can be added without changing the report schema.
        """
        reason = (
            "No local perceptual evaluator is installed. FreeVideoForge reports "
            "NOT_VERIFIED rather than fabricating a score."
        )
        return [
            QualityCheck(id="creative.subject_continuity", category="creative",
                         status="NOT_VERIFIED", detail=reason),
            QualityCheck(id="creative.prompt_adherence", category="creative",
                         status="NOT_VERIFIED", detail=reason),
            QualityCheck(id="creative.visual_coherence", category="creative",
                         status="NOT_VERIFIED", detail=reason),
            QualityCheck(id="creative.legibility", category="creative",
                         status="NOT_VERIFIED",
                         detail="Contrast is enforced at layout time (WCAG ratio "
                                "selection for caption ink), but no rendered-frame "
                                "legibility evaluator is installed."),
            QualityCheck(id="creative.pacing", category="creative",
                         status="NOT_VERIFIED", detail=reason),
        ]
