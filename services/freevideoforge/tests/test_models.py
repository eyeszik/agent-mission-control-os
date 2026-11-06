"""Domain model behaviour."""

from __future__ import annotations

import pytest

from freevideoforge.errors import ConfigError
from freevideoforge.models import (
    Aspect,
    GenerateRequest,
    JobState,
    project_from_dict,
    scene_from_dict,
    slugify,
    to_jsonable,
)
from freevideoforge.models import Project, Scene


class TestAspect:
    def test_parses_every_supported_form(self):
        assert Aspect.parse("9:16") is Aspect.VERTICAL
        assert Aspect.parse("16x9") is Aspect.LANDSCAPE
        assert Aspect.parse("1/1") is Aspect.SQUARE
        assert Aspect.parse(Aspect.CLASSIC) is Aspect.CLASSIC

    def test_rejects_unknown_aspect_with_a_useful_message(self):
        with pytest.raises(ConfigError, match="Supported"):
            Aspect.parse("3:2")

    @pytest.mark.parametrize("aspect", list(Aspect))
    def test_resolution_is_always_even(self, aspect: Aspect):
        width, height = aspect.resolution(1080)
        assert width % 2 == 0 and height % 2 == 0

    def test_resolution_preserves_the_ratio(self):
        width, height = Aspect.VERTICAL.resolution(1920)
        assert abs(width / height - Aspect.VERTICAL.ratio) < 0.01


class TestGenerateRequest:
    def test_accepts_a_reasonable_request(self):
        GenerateRequest(topic="anything").validate()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"topic": ""},
            {"topic": "  "},
            {"topic": "t", "duration": 1},
            {"topic": "t", "duration": 9999},
            {"topic": "t", "aspect": "3:2"},
            {"topic": "t", "fps": 0},
            {"topic": "t", "scenes": 0},
            {"topic": "t", "quality_preset": "ultra"},
            {"topic": "t", "music": "jazz"},
        ],
    )
    def test_rejects_invalid_input(self, kwargs):
        with pytest.raises(ConfigError):
            GenerateRequest(**kwargs).validate()

    def test_rejects_unknown_fields_rather_than_ignoring_them(self):
        with pytest.raises(ConfigError, match="Unknown request fields"):
            GenerateRequest.from_dict({"topic": "t", "surprise": 1})

    def test_round_trips_through_a_dict(self):
        original = GenerateRequest(topic="t", duration=12, seed=7)
        assert GenerateRequest.from_dict(to_jsonable(original)) == original


class TestProjectSerialisation:
    def test_project_round_trips(self):
        project = Project(run_id="r1", topic="t", duration=10.0)
        project.scenes = [Scene(id="s01", index=0, duration=5.0)]
        restored = project_from_dict(to_jsonable(project))
        assert restored.run_id == project.run_id
        assert restored.aspect is project.aspect
        assert [s.id for s in restored.scenes] == ["s01"]

    def test_scene_round_trips_with_nested_specs(self):
        scene = Scene(id="s01", index=0, duration=3.0)
        scene.visual.motif = "orbit"
        scene.motion.zoom_end = 1.25
        scene.content.voiceover = "hello"
        restored = scene_from_dict(to_jsonable(scene))
        assert restored.visual.motif == "orbit"
        assert restored.motion.zoom_end == 1.25
        assert restored.content.voiceover == "hello"


class TestProjectValidation:
    def test_rejects_a_project_with_no_scenes(self):
        with pytest.raises(ConfigError, match="no scenes"):
            Project(run_id="r", topic="t").validate()

    def test_rejects_a_zero_length_scene(self):
        project = Project(run_id="r", topic="t")
        project.scenes = [Scene(id="s01", index=0, duration=0.0)]
        with pytest.raises(ConfigError, match="non-positive duration"):
            project.validate()

    def test_rejects_odd_dimensions(self):
        project = Project(run_id="r", topic="t")
        project.render.width = 1081
        with pytest.raises(ConfigError, match="even"):
            project.render.validate()


def test_job_state_terminal_set_is_correct():
    from freevideoforge.models import RESUMABLE_STATES, TERMINAL_STATES

    assert JobState.COMPLETED in TERMINAL_STATES
    assert JobState.FAILED in RESUMABLE_STATES
    assert not (TERMINAL_STATES & RESUMABLE_STATES)


def test_slugify_is_filesystem_safe():
    assert slugify("Why the Moon Changes Shape!") == "why-the-moon-changes-shape"
    assert slugify("///") == "untitled"
