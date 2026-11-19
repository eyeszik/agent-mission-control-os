"""Strict mapping from approved VNEXUS copy to UCPO. Mapping text is never copy or authority."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import SectionKind

_KEY = r"^(?:verbal\.messaging|strategy\.(?:positioning|audience))\.[a-z0-9_]+(?:\.[a-z0-9_]+)*$"
_SLUG = r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrandSectionMapping(_Strict):
    kind: SectionKind
    heading_key: str = Field(pattern=_KEY)
    body_key: Optional[str] = Field(default=None, pattern=_KEY)
    label_key: Optional[str] = Field(default=None, pattern=_KEY)
    cta: bool = False
    anchor: Optional[str] = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,39}$")
    image: Optional[str] = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")


class BrandPageMapping(_Strict):
    slug: str = Field(pattern=_SLUG)
    title_key: str = Field(pattern=_KEY)
    description_key: str = Field(pattern=_KEY)
    sections: tuple[BrandSectionMapping, ...] = Field(min_length=1, max_length=10)


class BrandImageMapping(_Strict):
    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    alt_key: str = Field(pattern=_KEY)
    motif_seed: int = Field(default=0, ge=0, le=10_000)


class BrandWebsiteMapping(_Strict):
    schema_version: Literal["amc-brand-website-map/v1"] = "amc-brand-website-map/v1"
    organization_key: str = Field(default="verbal.messaging.organization", pattern=_KEY)
    tagline_key: str = Field(default="verbal.messaging.tagline", pattern=_KEY)
    offering_key: str = Field(default="strategy.positioning.statement", pattern=_KEY)
    audience_key: str = Field(default="strategy.audience.primary", pattern=_KEY)
    cta_label_key: str = Field(default="verbal.messaging.cta", pattern=_KEY)
    cta_target: str = Field(pattern=r"^[a-z0-9-]{1,40}(?:#[a-z0-9-]{1,40})?$")
    locale: str = Field(default="en", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    pages: tuple[BrandPageMapping, ...] = Field(min_length=1, max_length=8)
    images: tuple[BrandImageMapping, ...] = Field(default=(), max_length=16)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)

    @model_validator(mode="after")
    def _unique(self) -> "BrandWebsiteMapping":
        if len({p.slug for p in self.pages}) != len(self.pages):
            raise ValueError("page slugs must be unique")
        if len({i.asset_id for i in self.images}) != len(self.images):
            raise ValueError("image asset ids must be unique")
        return self


class BrandSiteRequest(_Strict):
    site_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    brand_id: str = Field(min_length=1, max_length=128)
    mapping: BrandWebsiteMapping
