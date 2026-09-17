"""Tests for the brand_core compiler artifact's content shape.

This is a pure content-schema module -- no live pipeline node produces
brand_core yet (see agency/artifacts/brand.py's module docstring), so these
tests exercise the Pydantic model directly rather than a graph node.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from services.langgraph.agency.artifacts.brand import (
    BrandCore,
    BrandVoice,
    ColorRole,
    LogoLockup,
    LogoLockupType,
)


def _lockup(**overrides) -> dict:
    base = {
        "lockup_id": "primary-full-color",
        "lockup_type": "primary",
        "usage_context": "Default mark for all digital and print surfaces.",
        "minimum_size": "24px height digital / 0.5in height print",
        "clear_space_rule": "Clear space on all sides equal to the cap height of the wordmark.",
        "placement_notes": "Top-left on digital surfaces; bottom-right on print collateral.",
        "generation_reference": "A rounded wordmark in deep indigo with a small compass-needle mark to the left.",
    }
    base.update(overrides)
    return base


def _brand_core(**overrides) -> dict:
    base = {
        "brand_name": "Northwind Coffee",
        "positioning_essence": "The coffee for people who take their mornings seriously.",
        "voice": {
            "tone_attributes": ["confident", "warm", "direct"],
            "writing_dos": ["Use short sentences.", "Speak like a trusted neighbor."],
            "writing_donts": ["Never use exclamation points.", "Never say 'delicious'."],
        },
        "color_story": [
            {"role": "primary", "description": "A deep, confident blue that carries the brand's authority."},
            {"role": "accent", "description": "A warm amber that evokes the roast."},
        ],
        "typography_direction": "A humanist serif for headlines, a clean grotesk for body copy.",
        "imagery_style": "Natural light, unstyled hands, no studio gloss.",
        "logo_lockups": [_lockup()],
    }
    base.update(overrides)
    return base


def test_valid_brand_core_constructs():
    core = BrandCore(**_brand_core())
    assert core.brand_name == "Northwind Coffee"
    assert core.logo_lockups[0].lockup_type is LogoLockupType.primary


def test_requires_at_least_one_logo_lockup():
    with pytest.raises(ValidationError):
        BrandCore(**_brand_core(logo_lockups=[]))


def test_requires_exactly_one_primary_lockup_when_zero_present():
    with pytest.raises(ValidationError, match="exactly one primary lockup"):
        BrandCore(**_brand_core(logo_lockups=[_lockup(lockup_id="icon", lockup_type="icon_only")]))


def test_rejects_a_second_primary_lockup():
    with pytest.raises(ValidationError, match="exactly one primary lockup"):
        BrandCore(
            **_brand_core(
                logo_lockups=[
                    _lockup(lockup_id="primary-a"),
                    _lockup(lockup_id="primary-b"),
                ]
            )
        )


def test_multiple_non_primary_lockups_alongside_the_one_primary_is_valid():
    core = BrandCore(
        **_brand_core(
            logo_lockups=[
                _lockup(),
                _lockup(lockup_id="icon-only", lockup_type="icon_only"),
                _lockup(lockup_id="reversed", lockup_type="reversed"),
            ]
        )
    )
    assert len(core.logo_lockups) == 3


def test_rejects_duplicate_lockup_ids():
    with pytest.raises(ValidationError, match="duplicate lockup_id"):
        BrandCore(
            **_brand_core(
                logo_lockups=[
                    _lockup(lockup_id="dup"),
                    _lockup(lockup_id="dup", lockup_type="icon_only"),
                ]
            )
        )


def test_requires_at_least_one_tone_attribute():
    with pytest.raises(ValidationError):
        BrandVoice(tone_attributes=[])


def test_writing_dos_and_donts_default_to_empty():
    voice = BrandVoice(tone_attributes=["confident"])
    assert voice.writing_dos == []
    assert voice.writing_donts == []


def test_requires_at_least_one_color_role():
    with pytest.raises(ValidationError):
        BrandCore(**_brand_core(color_story=[]))


def test_color_role_is_qualitative_not_a_hex_value():
    role = ColorRole(role="primary", description="A deep, confident blue.")
    assert role.role == "primary"
    assert "description" in role.model_dump()
    assert "hex" not in role.model_dump()


@pytest.mark.parametrize("lockup_type", [item.value for item in LogoLockupType])
def test_every_declared_lockup_type_is_constructible(lockup_type):
    lockup = LogoLockup(**_lockup(lockup_id=f"variant-{lockup_type}", lockup_type=lockup_type))
    assert lockup.lockup_type.value == lockup_type


def test_unknown_lockup_type_is_rejected():
    with pytest.raises(ValidationError):
        LogoLockup(**_lockup(lockup_type="holographic"))


def test_blank_required_string_fields_are_rejected():
    with pytest.raises(ValidationError):
        BrandCore(**_brand_core(brand_name=""))
    with pytest.raises(ValidationError):
        LogoLockup(**_lockup(generation_reference=""))


def test_round_trips_through_json_without_loss():
    original = BrandCore(**_brand_core())
    restored = BrandCore(**json.loads(original.model_dump_json()))
    assert restored == original
