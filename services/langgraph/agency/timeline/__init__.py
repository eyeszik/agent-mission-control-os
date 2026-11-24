"""Exact timeline timing contract for film/video plans.

Pure, deterministic arithmetic only: no media, no provider, no rendering.
Time is held as integer frames on a rational timebase (``fps`` as ``num/den``),
so transition overlaps and totals are exact rather than float-approximated.

A ``Timeline`` is either a master or a cutdown. A cutdown is a re-edit that
references master shots by ``source_shot_ref`` and may trim (never extend) them,
and it must keep a message and the CTA, so a cutdown can never be a silent
truncation of the master.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_FPS = re.compile(r"^[1-9][0-9]{0,5}(/[1-9][0-9]{0,5})?$")
TRANSITIONS = ("cut", "dissolve")
ROLES = ("hook", "headline", "message", "proof", "cta", "bridge")


class TimingError(ValueError):
    """Raised when a timeline breaks an exact-timing or structural rule."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def parse_rate(text: str) -> Fraction:
    """Parse ``"30"`` or ``"30000/1001"``; floats and free text are rejected."""
    if not isinstance(text, str) or not _FPS.match(text):
        raise TimingError(f"fps must be an integer or num/den string, got {text!r}")
    rate = Fraction(text)
    if not (Fraction(1) <= rate <= Fraction(240)):
        raise TimingError(f"fps out of supported range 1..240: {text}")
    return rate


def seconds_to_frames(seconds: str, fps: str) -> int:
    """Convert an exact decimal/fraction string of seconds to frames; fail if not frame-aligned."""
    if not isinstance(seconds, str):
        raise TimingError("seconds must be passed as a string such as '5' or '0.4' (no floats)")
    try:
        value = Fraction(seconds)
    except (ValueError, ZeroDivisionError) as exc:
        raise TimingError(f"unparseable seconds {seconds!r}") from exc
    frames = value * parse_rate(fps)
    if frames.denominator != 1:
        raise TimingError(f"{seconds}s is not frame-aligned at {fps} fps ({float(frames):.4f} frames)")
    return int(frames)


def frames_to_seconds(frames: int, fps: str) -> str:
    """Exact seconds as a reduced fraction string, e.g. ``'28'`` or ``'16/3'``."""
    value = Fraction(frames) / parse_rate(fps)
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


class Timebase(_Model):
    fps: str

    @field_validator("fps")
    @classmethod
    def _rate_ok(cls, value: str) -> str:
        parse_rate(value)
        return value


class ClipSpec(_Model):
    clip_id: str
    shot_ref: str
    role: Literal["hook", "headline", "message", "proof", "cta", "bridge"]
    duration_frames: int = Field(gt=0, le=240 * 3600)
    transition_in: Literal["cut", "dissolve"] = "cut"
    overlap_frames: int = Field(default=0, ge=0)

    @field_validator("clip_id", "shot_ref")
    @classmethod
    def _id_ok(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError(f"invalid id {value!r}")
        return value


class Timeline(_Model):
    timeline_id: str
    kind: Literal["master", "cutdown"]
    timebase: Timebase
    clips: tuple[ClipSpec, ...] = Field(min_length=1)
    master_timeline_id: str | None = None

    @field_validator("timeline_id")
    @classmethod
    def _tl_id(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError(f"invalid timeline id {value!r}")
        return value

    @model_validator(mode="after")
    def _structure(self) -> "Timeline":
        ids = [c.clip_id for c in self.clips]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate clip_id")
        if self.kind == "master" and self.master_timeline_id is not None:
            raise ValueError("a master timeline cannot reference another master")
        if self.kind == "cutdown" and not self.master_timeline_id:
            raise ValueError("a cutdown must name its master_timeline_id")
        first = self.clips[0]
        if first.transition_in != "cut" or first.overlap_frames != 0:
            raise ValueError("the first clip cannot have a transition")
        prev: ClipSpec | None = None
        for clip in self.clips:
            if clip.transition_in == "cut" and clip.overlap_frames != 0:
                raise ValueError(f"cut into {clip.clip_id} cannot overlap")
            if clip.transition_in == "dissolve" and clip.overlap_frames == 0:
                raise ValueError(f"dissolve into {clip.clip_id} needs overlap_frames > 0")
            if prev is not None and clip.overlap_frames > 0:
                if clip.overlap_frames >= min(prev.duration_frames, clip.duration_frames):
                    raise ValueError(f"overlap into {clip.clip_id} must be shorter than both neighbours")
            prev = clip
        roles = [c.role for c in self.clips]
        if "cta" not in roles or self.clips[-1].role != "cta":
            raise ValueError("timeline must end on a cta clip (no silent truncation)")
        if not any(r in ("message", "headline") for r in roles):
            raise ValueError("timeline must carry a message or headline")
        return self

    # ---- computed (never stored) -------------------------------------------------
    def starts(self) -> list[int]:
        out, cursor, prev = [], 0, None
        for clip in self.clips:
            if prev is None:
                start = 0
            else:
                start = cursor - clip.overlap_frames
            out.append(start)
            cursor = start + clip.duration_frames
            prev = clip
        return out

    def total_frames(self) -> int:
        starts = self.starts()
        last = self.clips[-1]
        return starts[-1] + last.duration_frames

    def total_seconds(self) -> str:
        return frames_to_seconds(self.total_frames(), self.timebase.fps)

    def content_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def validate_cutdown(master: Timeline, cutdown: Timeline, *, target_seconds: str) -> dict:
    """Check a cutdown against its master: trims only, same timebase, exact target length."""
    if master.kind != "master" or cutdown.kind != "cutdown":
        raise TimingError("validate_cutdown needs a master and a cutdown")
    if cutdown.master_timeline_id != master.timeline_id:
        raise TimingError("cutdown does not reference this master")
    if cutdown.timebase != master.timebase:
        raise TimingError("cutdown must share the master timebase")
    by_ref = {c.clip_id: c for c in master.clips}
    for clip in cutdown.clips:
        source = by_ref.get(clip.shot_ref)
        if source is None:
            raise TimingError(f"cutdown references unknown master shot {clip.shot_ref}")
        if clip.role != source.role:
            raise TimingError(f"cutdown relabels {clip.shot_ref}; source shot role must be preserved")
        if clip.duration_frames > source.duration_frames:
            raise TimingError(f"cutdown extends {clip.shot_ref}; only trims are allowed")
    target = seconds_to_frames(target_seconds, master.timebase.fps)
    if cutdown.total_frames() != target:
        raise TimingError(
            f"cutdown is {cutdown.total_seconds()}s, target is {target_seconds}s")
    return {"valid": True, "total_frames": target, "content_hash": cutdown.content_hash()}


__all__ = [
    "ROLES", "TRANSITIONS", "ClipSpec", "Timebase", "Timeline", "TimingError",
    "frames_to_seconds", "parse_rate", "seconds_to_frames", "validate_cutdown",
]
