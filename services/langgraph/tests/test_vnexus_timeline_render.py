"""Procedural edits use exact timeline frames, real dissolves and source-only cutdowns."""
from __future__ import annotations

import pytest

from services.langgraph.agency.foundry.contracts import UserBrief
from services.langgraph.agency.foundry.genome import compile_genome
from services.langgraph.agency.timeline import ClipSpec, Timebase, Timeline, validate_cutdown
from services.langgraph.agency.vnexus.media_fabric import svg_problems
from services.langgraph.agency.vnexus.timeline_render import captions, compose_frames
from services.langgraph.agency.vnexus.video import Shot, ShotKind, shot_frame


def clip(cid, role, duration, *, ref=None, overlap=0):
    return ClipSpec(clip_id=cid, shot_ref=ref or cid, role=role, duration_frames=duration,
                    transition_in="dissolve" if overlap else "cut", overlap_frames=overlap)


def fixture():
    master = Timeline(timeline_id="master", kind="master", timebase=Timebase(fps="10"), clips=(
        clip("m1", "hook", 30), clip("m2", "headline", 30, overlap=5), clip("m3", "cta", 30, overlap=5)))
    shots = {"m1": Shot(shot_id="m1", kind=ShotKind.MARK_REVEAL, duration_s=3, text=("Northline",),
                         camera="static", transition="cut", path="A_PROCEDURAL"),
             "m2": Shot(shot_id="m2", kind=ShotKind.HEADLINE, duration_s=3, text=("A clear workflow",),
                         camera="static", transition="cut", path="A_PROCEDURAL"),
             "m3": Shot(shot_id="m3", kind=ShotKind.CALL_TO_ACTION, duration_s=3, text=("Discuss your workflow",),
                         camera="static", transition="cut", path="A_PROCEDURAL")}
    genome = compile_genome(UserBrief(organization="Northline"), project_id="p")
    return master, shots, genome


def test_real_dissolve_is_composed_and_cutdown_reuses_master_shot_sources():
    master, shots, genome = fixture()
    rendered = compose_frames(master, master, shots, genome, width=320, height=180)
    assert len(rendered) == master.total_frames() == 80
    assert '<g opacity="0.000000">' in rendered[25]
    assert '<g opacity="0.500000">' in rendered[27]
    assert '<g opacity="1.000000">' in rendered[29]
    assert all(not svg_problems(frame) for frame in rendered)
    cut = Timeline(timeline_id="cut", kind="cutdown", master_timeline_id="master", timebase=master.timebase,
                   clips=(clip("c1", "headline", 20, ref="m2"), clip("c2", "cta", 20, ref="m3", overlap=5)))
    assert validate_cutdown(master, cut, target_seconds="3.5")["valid"]
    cut_frames = compose_frames(master, cut, shots, genome, width=320, height=180)
    assert len(cut_frames) == 35
    # The first trimmed frame is identical to the first source-shot frame of the master.
    assert cut_frames[0] == shot_frame(shots["m2"], genome, 0.0, width=320, height=180)
    assert "Discuss your workflow" in cut_frames[-1]
    text = captions(master, cut, shots, width=320, height=180)
    assert "NOTE Silent animation" in text and "00:00:00.300 --> 00:00:01.700" in text
    assert "00:00:01.900 --> 00:00:03.500" in text and "Discuss your workflow" in text


def test_cutdown_cannot_spoof_role_or_extend_sources():
    master, shots, genome = fixture()
    bad_role = Timeline(timeline_id="bad", kind="cutdown", master_timeline_id="master", timebase=master.timebase,
                        clips=(clip("a", "message", 20, ref="m1"), clip("b", "cta", 20, ref="m3")))
    with pytest.raises(ValueError, match="relabels"):
        compose_frames(master, bad_role, shots, genome, width=320, height=180)
    too_long = bad_role.model_copy(update={"clips": (clip("a", "headline", 31, ref="m2"), clip("b", "cta", 20, ref="m3"))})
    with pytest.raises(ValueError, match="extends"):
        compose_frames(master, too_long, shots, genome, width=320, height=180)
    incomplete = {**shots, "m3": shots["m3"].model_copy(update={"path": "B_AI_PROVIDER"})}
    with pytest.raises(ValueError, match="not procedural"):
        compose_frames(master, master, incomplete, genome, width=320, height=180)


def test_three_way_overlaps_and_over_budget_are_refused():
    master, shots, genome = fixture()
    triple = Timeline(timeline_id="triple", kind="master", timebase=master.timebase,
                      clips=(clip("m1", "hook", 30), clip("m2", "headline", 30, overlap=20),
                             clip("m3", "cta", 30, overlap=20)))
    with pytest.raises(ValueError, match="three-way"):
        compose_frames(triple, triple, shots, genome, width=320, height=180)
    over_budget = Timeline(timeline_id="large", kind="master", timebase=master.timebase,
                           clips=(clip("m1", "hook", 60), clip("m2", "headline", 60, overlap=5),
                                  clip("m3", "cta", 60, overlap=5)))
    with pytest.raises(ValueError, match="budget"):
        compose_frames(over_budget, over_budget, shots, genome, width=1920, height=1920)


def test_vtt_copy_is_not_interpreted_as_markup_or_extra_cues():
    master, shots, _ = fixture()
    shots["m2"] = shots["m2"].model_copy(update={"text": ("Hello <world>\n\n00:00:00.000 --> evil",)})
    text = captions(master, master, shots, width=320, height=180)
    assert "&lt;world&gt;" in text and "--&gt; evil" in text
    assert text.count(" --> ") == 3


def test_text_alternative_waits_for_reveal_and_rejects_too_short_a_clip():
    master, shots, _ = fixture()
    text = captions(master, master, shots, width=320, height=180)
    # The mark shot's brand name is initially hidden: never claim it is shown at zero.
    assert "00:00:00.000 -->" not in text
    assert "00:00:01.500 --> 00:00:02.700" in text
    short = Timeline(timeline_id="too-short", kind="cutdown", master_timeline_id="master", timebase=master.timebase,
                     clips=(clip("c1", "headline", 3, ref="m2"), clip("c2", "cta", 20, ref="m3")))
    with pytest.raises(ValueError, match="not sufficiently visible"):
        captions(master, short, shots, width=320, height=180)


def test_video_copy_that_cannot_fit_is_rejected_instead_of_clipped():
    _, shots, genome = fixture()
    unbroken = shots["m2"].model_copy(update={"text": ("word" * 50,)})
    with pytest.raises(ValueError, match="VIDEO_COPY_EXCEEDS_LAYOUT"):
        shot_frame(unbroken, genome, 0.5, width=320, height=180)
    lengthy = shots["m2"].model_copy(update={"text": ("many words " * 80,)})
    with pytest.raises(ValueError, match="VIDEO_COPY_EXCEEDS_LAYOUT"):
        shot_frame(lengthy, genome, 0.5, width=320, height=180)
    wide_mark = shots["m1"].model_copy(update={"text": ("A very long wordmark " * 30,)})
    with pytest.raises(ValueError, match="VIDEO_COPY_EXCEEDS_LAYOUT"):
        shot_frame(wide_mark, genome, 0.5, width=320, height=180)
