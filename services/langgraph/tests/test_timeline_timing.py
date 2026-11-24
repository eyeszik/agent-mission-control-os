"""Exact timing contract for timelines, transitions and cutdowns (no media rendered)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.langgraph.agency.timeline import (
    ClipSpec,
    Timebase,
    Timeline,
    TimingError,
    frames_to_seconds,
    seconds_to_frames,
    validate_cutdown,
)

FPS = "30"


def _clip(cid, role, frames, *, overlap=0, transition=None, ref=None):
    trans = transition or ("dissolve" if overlap else "cut")
    return ClipSpec(clip_id=cid, shot_ref=ref or cid, role=role, duration_frames=frames,
                    transition_in=trans, overlap_frames=overlap)


def _master(clips, fps=FPS, tid="launch-30s"):
    return Timeline(timeline_id=tid, kind="master", timebase=Timebase(fps=fps), clips=tuple(clips))


# --- arithmetic --------------------------------------------------------------------

def test_six_five_second_shots_with_five_point_four_second_dissolves_is_28_seconds():
    # 6 x 5s - 5 x 0.4s = 28s, the contract's stated transition accounting.
    five = seconds_to_frames("5", FPS)
    overlap = seconds_to_frames("0.4", FPS)
    roles = ["hook", "headline", "proof", "message", "proof", "cta"]
    clips = [_clip(f"s{i + 1}", r, five, overlap=0 if i == 0 else overlap) for i, r in enumerate(roles)]
    tl = _master(clips)
    assert tl.total_frames() == 840
    assert tl.total_seconds() == "28"


def test_reference_30_second_master_has_exact_frames_and_message_cta_ending():
    # 6 shots of 160f with 5 dissolves of 12f (0.4s at 30 fps): 6*160 - 5*12 = 900f = 30s.
    overlap = seconds_to_frames("0.4", FPS)
    roles = ["hook", "headline", "proof", "message", "proof", "cta"]
    clips = [_clip(f"m{i + 1}", r, 160, overlap=0 if i == 0 else overlap) for i, r in enumerate(roles)]
    tl = _master(clips)
    assert tl.total_frames() == 900
    assert tl.total_seconds() == "30"
    assert tl.starts() == [0, 148, 296, 444, 592, 740]


def test_rational_timebase_ntsc_frame_alignment_is_exact():
    # 30000/1001 fps: one NTSC frame is 1001/30000 s; 1001 frames = 1001/30000*1001 s, checked exactly.
    frames = seconds_to_frames("1001/30000", "30000/1001")
    assert frames == 1
    assert frames_to_seconds(30000, "30000/1001") == "1001"


def test_seconds_are_never_accepted_as_floats():
    with pytest.raises(TimingError):
        seconds_to_frames(0.4, FPS)  # type: ignore[arg-type]


def test_non_frame_aligned_transition_is_rejected_not_rounded():
    # 0.4s at 24 fps is 9.6 frames: must fail rather than silently round.
    with pytest.raises(TimingError, match="not frame-aligned"):
        seconds_to_frames("0.4", "24")


def test_unparseable_and_out_of_range_rates_are_rejected():
    with pytest.raises(TimingError):
        seconds_to_frames("five", FPS)
    with pytest.raises(ValidationError):
        Timebase(fps="0")
    with pytest.raises(ValidationError):
        Timebase(fps="25.5")


# --- structural rules --------------------------------------------------------------

def test_overlap_must_be_shorter_than_both_neighbours():
    clips = [_clip("a", "hook", 30), _clip("b", "cta", 30, overlap=30)]
    with pytest.raises(ValidationError, match="shorter than both"):
        _master(clips)


def test_cut_cannot_carry_overlap_and_dissolve_needs_overlap():
    with pytest.raises(ValidationError, match="cannot overlap"):
        _master([_clip("a", "hook", 30), ClipSpec(clip_id="b", shot_ref="b", role="cta",
                                                  duration_frames=30, transition_in="cut", overlap_frames=3)])
    with pytest.raises(ValidationError, match="needs overlap"):
        _master([_clip("a", "hook", 30), ClipSpec(clip_id="b", shot_ref="b", role="cta",
                                                  duration_frames=30, transition_in="dissolve", overlap_frames=0)])


def test_first_clip_cannot_have_transition():
    with pytest.raises(ValidationError, match="first clip"):
        _master([_clip("a", "hook", 30, overlap=5), _clip("b", "cta", 30)])


def test_timeline_must_end_on_cta_so_truncation_is_detected():
    with pytest.raises(ValidationError, match="end on a cta"):
        _master([_clip("a", "hook", 30), _clip("b", "message", 30)])


def test_duplicate_clip_ids_and_unsafe_ids_are_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        _master([_clip("a", "hook", 30), _clip("a", "cta", 30, overlap=5)])
    for bad in ["../etc", "Upper", "a/b", "", "x" * 70]:
        with pytest.raises(ValidationError):
            ClipSpec(clip_id=bad, shot_ref="ok", role="cta", duration_frames=10)


def test_extra_fields_and_zero_durations_are_rejected():
    with pytest.raises(ValidationError):
        ClipSpec(clip_id="a", shot_ref="a", role="cta", duration_frames=0)
    with pytest.raises(ValidationError):
        ClipSpec(clip_id="a", shot_ref="a", role="cta", duration_frames=10, shell="rm -rf /")  # type: ignore[call-arg]


# --- cutdowns ----------------------------------------------------------------------

def _reference_master():
    overlap = seconds_to_frames("0.4", FPS)
    roles = ["hook", "headline", "proof", "message", "proof", "cta"]
    return _master([_clip(f"m{i + 1}", r, 160, overlap=0 if i == 0 else overlap)
                    for i, r in enumerate(roles)])


def _cutdown(clips, tid="cut-15a"):
    return Timeline(timeline_id=tid, kind="cutdown", timebase=Timebase(fps=FPS),
                    clips=tuple(clips), master_timeline_id="launch-30s")


def test_two_fifteen_second_cutdowns_keep_message_and_cta_and_hit_exact_length():
    master = _reference_master()
    # 15s = 450f. Trims only (<=160f per source shot): 154+160+160 - 2*12 = 450.
    a = _cutdown([_clip("c1", "hook", 154, ref="m1"),
                  _clip("c2", "message", 160, overlap=12, ref="m4"),
                  _clip("c3", "cta", 160, overlap=12, ref="m6")], tid="cut-15a")
    b = _cutdown([_clip("d1", "headline", 160, ref="m2"),
                  _clip("d2", "proof", 154, overlap=12, ref="m3"),
                  _clip("d3", "cta", 160, overlap=12, ref="m6")], tid="cut-15b")
    assert validate_cutdown(master, a, target_seconds="15")["valid"] is True
    assert validate_cutdown(master, b, target_seconds="15")["total_frames"] == 450
    assert a.content_hash() != b.content_hash()


def test_cutdown_that_is_a_plain_truncation_is_rejected():
    _reference_master()
    # The first three master shots: no CTA at the end, so it is a truncation.
    with pytest.raises(ValidationError, match="end on a cta"):
        _cutdown([_clip("t1", "hook", 160, ref="m1"),
                  _clip("t2", "headline", 160, overlap=12, ref="m2"),
                  _clip("t3", "proof", 160, overlap=12, ref="m3")])


def test_cutdown_extending_a_master_shot_is_rejected():
    master = _reference_master()
    bad = _cutdown([_clip("e1", "hook", 200, ref="m1"),
                    _clip("e2", "message", 160, overlap=12, ref="m4"),
                    _clip("e3", "cta", 160, overlap=12, ref="m6")])
    with pytest.raises(TimingError, match="extends"):
        validate_cutdown(master, bad, target_seconds=frames_to_seconds(bad.total_frames(), FPS))


def test_cutdown_with_wrong_length_or_unknown_source_is_rejected():
    master = _reference_master()
    short = _cutdown([_clip("w1", "message", 100, ref="m4"),
                      _clip("w2", "cta", 100, overlap=12, ref="m6")])
    with pytest.raises(TimingError, match="target"):
        validate_cutdown(master, short, target_seconds="15")
    ghost = _cutdown([_clip("g1", "message", 150, ref="nope"),
                      _clip("g2", "cta", 160, overlap=12, ref="m6")])
    with pytest.raises(TimingError, match="unknown master shot"):
        validate_cutdown(master, ghost, target_seconds=frames_to_seconds(ghost.total_frames(), FPS))


def test_cutdown_must_reference_the_given_master_and_share_timebase():
    master = _reference_master()
    other = Timeline(timeline_id="cut-x", kind="cutdown", timebase=Timebase(fps="25"),
                     clips=(_clip("x0", "message", 50, ref="m4"),
                            _clip("x1", "cta", 50, overlap=10, ref="m6")),
                     master_timeline_id="other-master")
    with pytest.raises(TimingError, match="does not reference"):
        validate_cutdown(master, other, target_seconds="2")


# --- hashing -----------------------------------------------------------------------

def test_content_hash_is_deterministic_and_changes_with_timing():
    a = _reference_master()
    b = _reference_master()
    assert a.content_hash() == b.content_hash()
    changed = _master([_clip("m1", "hook", 161, overlap=0)] + [
        _clip(f"m{i + 1}", r, 160, overlap=12)
        for i, r in enumerate(["headline", "proof", "message", "proof", "cta"], start=1)])
    assert changed.content_hash() != a.content_hash()


def test_cutdown_cannot_relabel_a_master_shot_as_message_or_cta():
    master = _reference_master()
    false_message = _cutdown([_clip("f1", "message", 154, ref="m1"),
                              _clip("f2", "proof", 160, overlap=12, ref="m3"),
                              _clip("f3", "cta", 160, overlap=12, ref="m6")])
    with pytest.raises(TimingError, match="relabels"):
        validate_cutdown(master, false_message, target_seconds="15")
    false_cta = _cutdown([_clip("f1", "headline", 154, ref="m2"),
                          _clip("f2", "proof", 160, overlap=12, ref="m3"),
                          _clip("f3", "cta", 160, overlap=12, ref="m5")])
    with pytest.raises(TimingError, match="relabels"):
        validate_cutdown(master, false_cta, target_seconds="15")
