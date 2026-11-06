"""Deterministic script engine and caption timing.

These assert *behaviour* - pacing rules, arc shape, provenance honesty, timing
invariants - rather than pinning exact generated strings, which would make any
copy improvement look like a regression.
"""

from __future__ import annotations

import pytest

from freevideoforge.models import ContentSpec, Project, Scene
from freevideoforge.providers.captions_script import (
    ScriptDerivedCaptionProvider,
    _split_into_cues,
    format_timestamp,
)
from freevideoforge.providers.script_template import (
    WORDS_PER_SECOND,
    TemplateScriptProvider,
    _noun_phrase,
    _shape,
)
from freevideoforge.providers.storyboard_planner import (
    STYLE_SYSTEMS,
    DeterministicStoryboardProvider,
)

BRIEF = (
    "The moon does not change shape. It is always a sphere lit by the sun from one "
    "side. What changes is how much of that lit half faces Earth as the moon orbits "
    "us. That orbit takes about 29.5 days, so the cycle repeats monthly."
)


@pytest.fixture
def script_provider() -> TemplateScriptProvider:
    return TemplateScriptProvider()


def make_project(**kwargs) -> Project:
    defaults = dict(run_id="r", topic="Why the moon changes shape", duration=30.0, seed=7)
    defaults.update(kwargs)
    return Project(**defaults)


class TestNarrativeShape:
    @pytest.mark.parametrize(
        "topic,expected",
        [
            ("How to bake sourdough", "how_to"),
            ("5 ways to cut cloud spend", "listicle"),
            ("The biggest myth about sleep", "myth_bust"),
            ("Rust vs Go for backend services", "comparison"),
            ("Why the moon changes shape", "question"),
            ("Photosynthesis", "explainer"),
        ],
    )
    def test_classifies_topics(self, topic, expected):
        assert _shape(topic) == expected

    @pytest.mark.parametrize(
        "topic,expected",
        [
            ("Why the moon changes shape", "the moon"),
            ("Quantum computing", "Quantum computing"),
            ("Rust vs Go for backend services", "Rust vs Go"),
            ("How to bake sourdough", "bake sourdough"),
        ],
    )
    def test_extracts_a_usable_noun_phrase(self, topic, expected):
        assert _noun_phrase(topic) == expected


class TestScriptGeneration:
    def test_always_opens_with_a_hook_and_closes_with_a_payoff(self, script_provider):
        for duration in (5, 15, 30, 60, 120):
            script = script_provider.generate(make_project(duration=float(duration)))
            roles = [beat["role"] for beat in script["beats"]]
            assert roles[0] == "hook", duration
            assert roles[-1] == "payoff", duration

    def test_scene_count_grows_with_duration(self, script_provider):
        counts = [
            len(script_provider.generate(make_project(duration=float(d)))["beats"])
            for d in (6, 20, 60)
        ]
        assert counts == sorted(counts)
        assert counts[0] < counts[-1]

    def test_is_deterministic_for_a_fixed_seed(self, script_provider):
        first = script_provider.generate(make_project(seed=99))
        second = script_provider.generate(make_project(seed=99))
        assert first == second

    def test_different_seeds_produce_different_copy(self, script_provider):
        variants = {
            tuple(b["voiceover"] for b in script_provider.generate(
                make_project(seed=seed))["beats"])
            for seed in range(6)
        }
        assert len(variants) > 1

    def test_no_beat_is_given_less_time_than_it_needs_to_be_spoken(self, script_provider):
        script = script_provider.generate(make_project(duration=30.0))
        for beat in script["beats"]:
            minimum = beat["word_count"] / WORDS_PER_SECOND
            assert beat["target_duration"] >= minimum, beat

    def test_never_emits_an_empty_or_truncated_dangling_line(self, script_provider):
        for duration in (5, 9, 17, 45):
            script = script_provider.generate(make_project(duration=float(duration)))
            for beat in script["beats"]:
                line = beat["voiceover"]
                assert line.strip()
                assert not line.rstrip().endswith((" the", " a", " an", " of", " to"))
                assert beat["headline"].strip()

    def test_declares_scaffold_provenance_without_a_brief(self, script_provider):
        script = script_provider.generate(make_project())
        assert script["content_source"] == "scaffold"
        assert "does not" in script["content_source_note"].lower() or \
            "asserts no facts" in script["content_source_note"]

    def test_uses_brief_sentences_as_body_copy(self, script_provider):
        script = script_provider.generate(make_project(brief=BRIEF, duration=40.0))
        assert script["content_source"] == "brief"
        body = " ".join(b["voiceover"] for b in script["beats"] if b["role"] == "body")
        assert "sphere" in body or "orbit" in body or "does not change shape" in body

    def test_unused_brief_sentences_are_reported_not_dropped_silently(self, script_provider):
        script = script_provider.generate(make_project(brief=BRIEF, duration=8.0))
        assert isinstance(script["unused_brief_sentences"], list)

    def test_respects_an_explicit_scene_count(self, script_provider):
        project = make_project(duration=30.0)
        project.providers["_scene_count"] = "5"
        assert len(script_provider.generate(project)["beats"]) == 5

    def test_planned_duration_matches_the_request_when_copy_fits(self, script_provider):
        script = script_provider.generate(make_project(duration=30.0))
        assert script["planned_duration"] == pytest.approx(30.0, abs=0.6)


class TestStoryboard:
    def test_every_scene_carries_separated_specs(self, script_provider):
        project = make_project()
        script = script_provider.generate(project)
        scenes = DeterministicStoryboardProvider().plan(project, script)
        assert len(scenes) == len(script["beats"])
        for scene in scenes:
            assert scene.content.voiceover
            assert scene.visual.motif and scene.visual.palette
            assert scene.motion.motion
            # The media prompt is derived, never the only place the spec lives.
            assert scene.visual.media_prompt
            assert scene.visual.negative_constraints

    def test_records_continuity_from_the_previous_scene(self, script_provider):
        project = make_project()
        scenes = DeterministicStoryboardProvider().plan(
            project, script_provider.generate(project)
        )
        assert "cold open" in scenes[0].visual.continuity
        for previous, current in zip(scenes, scenes[1:]):
            assert current.visual.continuity.startswith("continues from:")
            assert previous.visual.motif in current.visual.continuity

    def test_consecutive_scenes_never_repeat_the_same_camera_move(self, script_provider):
        project = make_project(duration=60.0)
        scenes = DeterministicStoryboardProvider().plan(
            project, script_provider.generate(project)
        )
        for previous, current in zip(scenes, scenes[1:]):
            assert previous.motion.motion != current.motion.motion

    def test_auto_style_resolves_to_a_real_palette(self, script_provider):
        project = make_project(style_system="auto")
        DeterministicStoryboardProvider().plan(project, script_provider.generate(project))
        assert project.style_system in STYLE_SYSTEMS

    def test_explicit_style_is_honoured(self, script_provider):
        project = make_project(style_system="neon")
        scenes = DeterministicStoryboardProvider().plan(
            project, script_provider.generate(project)
        )
        assert project.style_system == "neon"
        assert scenes[0].visual.palette == STYLE_SYSTEMS["neon"]["palette"]


class TestCaptions:
    @staticmethod
    def build_project(durations, texts, audio=None):
        project = Project(run_id="r", topic="t", duration=sum(durations))
        project.scenes = [
            Scene(
                id=f"s{i:02d}", index=i, duration=d,
                content=ContentSpec(voiceover=t),
                audio_duration=(audio[i] if audio else None),
            )
            for i, (d, t) in enumerate(zip(durations, texts))
        ]
        return project

    def test_cues_never_run_past_the_video(self, tmp_path):
        project = self.build_project(
            [4.0, 4.0],
            ["A fairly long sentence that has to be split across several caption "
             "lines because it keeps going.", "Short one."],
        )
        result = ScriptDerivedCaptionProvider().generate(project, tmp_path / "c.srt")
        total = sum(s.duration for s in project.scenes)
        assert result.cues
        assert max(c["end"] for c in result.cues) <= total + 0.05

    def test_cues_are_ordered_and_have_positive_length(self, tmp_path):
        project = self.build_project(
            [5.0, 5.0, 5.0],
            ["First scene narration here.", "Second scene narration here.",
             "Third scene narration, longer, with more words to split across lines."],
        )
        cues = ScriptDerivedCaptionProvider().generate(project, tmp_path / "c.srt").cues
        for cue in cues:
            assert cue["end"] > cue["start"]
        for previous, current in zip(cues, cues[1:]):
            assert current["start"] >= previous["start"] - 0.001

    def test_timing_follows_measured_audio_not_the_scene_length(self, tmp_path):
        project = self.build_project([10.0], ["Two words."], audio=[2.0])
        cues = ScriptDerivedCaptionProvider().generate(project, tmp_path / "c.srt").cues
        # Narration is 2s inside a 10s scene: the caption must end near the
        # speech, not linger for the whole scene.
        assert cues[-1]["end"] < 4.0

    def test_writes_a_parsable_srt(self, tmp_path):
        project = self.build_project([4.0], ["Hello there, this is a caption test."])
        path = tmp_path / "c.srt"
        ScriptDerivedCaptionProvider().generate(project, path)
        text = path.read_text(encoding="utf-8")
        assert text.startswith("1\n")
        assert " --> " in text

    def test_scene_with_no_narration_produces_no_cues_but_keeps_the_clock(self, tmp_path):
        project = self.build_project([3.0, 3.0], ["", "Second scene speaks."])
        cues = ScriptDerivedCaptionProvider().generate(project, tmp_path / "c.srt").cues
        assert all(c["scene_id"] == "s01" for c in cues)
        assert min(c["start"] for c in cues) >= 3.0

    @pytest.mark.parametrize(
        "seconds,expected",
        [(0, "00:00:00,000"), (1.5, "00:00:01,500"), (3661.25, "01:01:01,250")],
    )
    def test_timestamp_format(self, seconds, expected):
        assert format_timestamp(seconds) == expected

    def test_cue_splitting_respects_line_length(self):
        long_text = " ".join(["word"] * 40)
        for cue in _split_into_cues(long_text):
            assert len(cue) <= 60
