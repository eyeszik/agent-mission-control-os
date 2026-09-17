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

Color, typography, and motion here are described qualitatively (a color's
role and character, not its hex value; a motion's pace, not its easing
curve). Literal design tokens are ``design_token_set``'s job -- it already
consumes ``brand_core`` in the N3 role contracts, compiling the qualitative
brand object into implementable values. Keeping that split means a rendering
can never invent an interpretation of the brand that ``brand_core`` didn't
authorize.

``ColorRole.reference_hex`` is the one deliberate, narrow exception: an
*indicative* anchor value, not the canonical token, that exists only so
early contrast validation (``color_contrast.py``) has something to compute
against before ``design_token_set`` compiles the real value.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from services.langgraph.agency.artifacts.color_contrast import (
    HEX_COLOR_RE,
    contrast_ratio,
)

# Below this, two brand colors don't read as distinct roles -- a design-
# quality heuristic this project chose, not a WCAG-defined metric. WCAG
# does not specify a "how different must two brand colors be" threshold;
# do not cite this number as a compliance requirement.
MINIMUM_COLOR_STORY_DISTINCTION_RATIO = 1.5


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
    that description becomes the *canonical* hex value.

    ``reference_hex`` is deliberately not that canonical value: it is an
    indicative anchor good enough for early contrast validation before the
    real token compile happens. design_token_set may land on a different
    exact value; that is not a drift bug, it is the compile step doing its
    job.
    """

    role: str = Field(min_length=1)
    description: str = Field(min_length=1)
    reference_hex: str | None = None

    @field_validator("reference_hex")
    @classmethod
    def _reference_hex_is_a_real_hex_color(cls, value: str | None) -> str | None:
        if value is not None and not HEX_COLOR_RE.match(value):
            raise ValueError(f"reference_hex '{value}' is not a 6-digit hex color (e.g. '#1a2b4c')")
        return value


class MotionCharacter(BaseModel):
    """The brand's kinetic personality, qualitative like voice and color_story.

    Literal duration/easing values are design_token_set's job, same split as
    color: brand_core says *what the brand's motion feels like*, the compile
    step turns that into a cubic-bezier and a duration scale.
    """

    pace: str = Field(min_length=1)
    # Which interactions earn motion emphasis vs. stay minimal -- most brands
    # over- or under-animate everything because nobody decided this.
    emphasis_moments: list[str] = Field(min_length=1)
    # Required, not optional: a brand with a kinetic identity that hasn't
    # answered "what happens under prefers-reduced-motion" has an
    # accessibility gap, not an open question. Same fail-closed posture as
    # everything else in this codebase.
    reduced_motion_fallback: str = Field(min_length=1)


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
    motion: MotionCharacter
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

    @model_validator(mode="after")
    def _color_roles_with_reference_hex_are_distinguishable(self) -> "BrandCore":
        swatches = [role for role in self.color_story if role.reference_hex is not None]
        for i, role_a in enumerate(swatches):
            for role_b in swatches[i + 1 :]:
                ratio = contrast_ratio(role_a.reference_hex, role_b.reference_hex)  # type: ignore[arg-type]
                if ratio < MINIMUM_COLOR_STORY_DISTINCTION_RATIO:
                    raise ValueError(
                        f"color_story roles '{role_a.role}' and '{role_b.role}' are not "
                        f"visually distinguishable (contrast {ratio:.2f}:1, need at least "
                        f"{MINIMUM_COLOR_STORY_DISTINCTION_RATIO}:1)"
                    )
        return self
