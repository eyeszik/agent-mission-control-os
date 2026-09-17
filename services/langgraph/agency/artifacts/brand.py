"""Typed content for the N1 compiler artifacts that have no live producer yet.

``graph/agency/models.py`` holds the shapes the running 9-node pipeline
actually writes into ``GraphState``. The eleven compiler artifact types added
to the N1 ontology (``brand_core``, ``asset_prompt_set``, etc.) are legal for
their owning roles to produce, but nothing dispatches work to those roles yet
-- the N4 artifact registry stores their content as an opaque
``content_hash``, not a typed shape. This module is where that shape lives,
starting with the one every other compiler artifact in the brand/design chain
depends on: ``brand_core`` is authored once by ``brand_architect``, and every
downstream rendering -- ``design_token_set``, ``brand_guidelines_doc``, and
eventually a generation-prompt compiler -- is a function of it.

Color and typography here are described qualitatively (a color's role and
character, not its hex value). Literal design tokens are
``design_token_set``'s job -- it already consumes ``brand_core`` in the N3
role contracts, compiling the qualitative brand object into implementable
values. Keeping that split means a rendering can never invent an
interpretation of the brand that ``brand_core`` didn't authorize.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class LogoLockupType(str, Enum):
    """The standard lockup categories a brand identity system distinguishes."""

    primary = "primary"
    secondary = "secondary"
    icon_only = "icon_only"
    wordmark = "wordmark"
    horizontal = "horizontal"
    stacked = "stacked"
    reversed = "reversed"
    monochrome = "monochrome"


class LogoLockup(BaseModel):
    """One logo variant and the rules governing where and how it appears.

    ``generation_reference`` is deliberately the field precise enough to seed
    a future prompt compiler: a description exact enough that regenerating
    this lockup from scratch would produce a recognizably consistent result.
    """

    lockup_id: str = Field(min_length=1)
    lockup_type: LogoLockupType
    usage_context: str = Field(min_length=1)
    minimum_size: str = Field(min_length=1)
    clear_space_rule: str = Field(min_length=1)
    placement_notes: str = Field(min_length=1)
    generation_reference: str = Field(min_length=1)


class BrandVoice(BaseModel):
    tone_attributes: list[str] = Field(min_length=1)
    writing_dos: list[str] = Field(default_factory=list)
    writing_donts: list[str] = Field(default_factory=list)


class ColorRole(BaseModel):
    """A color's role in the brand system, not its literal value.

    e.g. role="primary", description="A deep, confident blue that carries
    the brand's authority across every surface." design_token_set is where
    that description becomes a hex value.
    """

    role: str = Field(min_length=1)
    description: str = Field(min_length=1)


class BrandCore(BaseModel):
    """The canonical brand object every rendering derives from.

    Matches N3's brand_architect contract: produced only by brand_architect,
    with a min_evidence floor of 2 because this object may not be invented
    from a single source.
    """

    brand_name: str = Field(min_length=1)
    positioning_essence: str = Field(min_length=1)
    voice: BrandVoice
    color_story: list[ColorRole] = Field(min_length=1)
    typography_direction: str = Field(min_length=1)
    imagery_style: str = Field(min_length=1)
    logo_lockups: list[LogoLockup] = Field(min_length=1)

    @field_validator("logo_lockups")
    @classmethod
    def _lockup_ids_are_unique(cls, value: list[LogoLockup]) -> list[LogoLockup]:
        ids = [lockup.lockup_id for lockup in value]
        if len(ids) != len(set(ids)):
            duplicates = sorted({lockup_id for lockup_id in ids if ids.count(lockup_id) > 1})
            raise ValueError(f"logo_lockups contains duplicate lockup_id(s): {duplicates}")
        return value

    @model_validator(mode="after")
    def _exactly_one_primary_lockup(self) -> "BrandCore":
        primary_count = sum(
            1 for lockup in self.logo_lockups if lockup.lockup_type is LogoLockupType.primary
        )
        if primary_count != 1:
            raise ValueError(
                f"logo_lockups must contain exactly one primary lockup, found {primary_count}"
            )
        return self
