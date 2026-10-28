"""The brand book page manifest: a versioned, typed template, not recovered source material.

The default manifest is a proposed 24-page implementation template. It names no
brand: every value a page prints comes from the approved genome (or, in a labelled
draft, a proposal). A page declares the genome keys it needs (``required_paths``)
and may use (``optional_paths``); those declarations are also its dependency set
for incremental rebuilds, so a page that reads a key must declare it.

``gap_behavior`` says what an unresolved required key does to a page:

* ``BLOCK``    production refuses the page; drafts print a labelled gap.
* ``LABEL``    the page renders with the gap labelled in every mode except PRODUCTION,
               where the gap blocks like ``BLOCK`` (production never prints a gap).
* ``DECIDE``   a conditional section: it needs an applicability decision
               (``production.brandbook.applicability.<page_id>``), never invented content.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash

TEMPLATE_ID = "amc-brandbook/default"
TEMPLATE_VERSION = "1.0.0"
APPLICABILITY_PREFIX = "production.brandbook.applicability."


class Mode(str, Enum):
    SYSTEM_SPEC_ONLY = "SYSTEM_SPEC_ONLY"   # manifest, field states and gaps; no page packages
    PROMPTS_ONLY = "PROMPTS_ONLY"           # page packages and readable prompts; nothing rendered or stored
    PREVIEW = "PREVIEW"                     # rendered and checked; proposals allowed, labelled
    PRODUCTION = "PRODUCTION"               # approved values only; no unresolved required key


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PageSpec(_Strict):
    id: str = Field(pattern=r"^p[0-9]{2}$")
    order: int = Field(ge=1, le=99)
    title: str = Field(min_length=1, max_length=60)
    objective: str = Field(min_length=1, max_length=400)
    required_paths: tuple[str, ...] = ()
    optional_paths: tuple[str, ...] = ()
    exact_copy: tuple[str, ...] = ()          # template copy printed verbatim (never brand facts)
    asset_refs: tuple[Literal["mark", "wordmark", "lockup"], ...] = ()
    evidence_refs: bool = False               # the page lists intake evidence
    layout: Literal["cover", "list", "grid", "specimen", "matrix", "table"] = "list"
    prohibitions: tuple[str, ...] = ()
    checks: tuple[str, ...] = ("no_overflow", "exact_copy", "no_unresolved_tokens")
    output_modes: tuple[Mode, ...] = (Mode.PROMPTS_ONLY, Mode.PREVIEW, Mode.PRODUCTION)
    gap_behavior: Literal["BLOCK", "LABEL", "DECIDE"] = "LABEL"
    reads_all_pages: bool = False             # contents / release: rebuilt whenever any page changes

    @property
    def applicability_key(self) -> str:
        return APPLICABILITY_PREFIX + self.id

    @property
    def dependency_paths(self) -> tuple[str, ...]:
        extra = (self.applicability_key,) if self.gap_behavior == "DECIDE" else ()
        return tuple(sorted(set(self.required_paths) | set(self.optional_paths) | set(extra)))


class PageManifest(_Strict):
    template_id: str
    template_version: str
    pages: tuple[PageSpec, ...]

    @model_validator(mode="after")
    def _ordered(self) -> "PageManifest":
        ids = [p.id for p in self.pages]
        orders = [p.order for p in self.pages]
        if len(set(ids)) != len(ids) or len(set(orders)) != len(orders):
            raise ValueError("page ids and orders must be unique")
        if orders != sorted(orders):
            raise ValueError("pages must be listed in order")
        return self

    @property
    def manifest_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def page(self, page_id: str) -> PageSpec:
        return next(p for p in self.pages if p.id == page_id)


# Keys every page's styling reads (palette and type set the whole book), so they belong to every page's dependency set.
STYLE_PATHS: tuple[str, ...] = (
    "visual.color.ink", "visual.color.paper", "visual.color.accent", "visual.color.accent_2", "visual.color.muted",
    "visual.typography.display", "visual.typography.body", "production.output.page_format",
)

_LOGO = ("visual.logo.mark", "visual.logo.master_artifact", "visual.logo.wordmark")
_P = PageSpec

DEFAULT_PAGES: tuple[PageSpec, ...] = (
    _P(id="p01", order=1, title="Cover", objective="Exact brand identity, document title, template version and approval status.",
       optional_paths=_LOGO, exact_copy=("Brand guidelines",), asset_refs=("mark", "wordmark"), layout="cover",
       prohibitions=("no invented slogan", "no invented date", "no endorsement"), gap_behavior="LABEL"),
    _P(id="p02", order=2, title="Contents and status", objective="Actual navigation from this manifest, scope, evidence and approval legend.",
       exact_copy=("Contents",), layout="table", reads_all_pages=True),
    _P(id="p03", order=3, title="Premise", objective="Offering, audience, positioning, differentiation and values behind the design.",
       required_paths=("strategy.positioning.statement", "strategy.audience.primary"),
       optional_paths=("strategy.positioning.promise", "strategy.audience.needs", "strategy.differentiation.statement",
                       "strategy.values.list", "strategy.competitive_territory.summary"), gap_behavior="BLOCK"),
    _P(id="p04", order=4, title="Voice", objective="Operational voice traits, channel tone, vocabulary and claims, with write/avoid samples.",
       required_paths=("verbal.voice.tone",),
       optional_paths=("verbal.voice.register", "verbal.tone.channels", "verbal.vocabulary.prefer", "verbal.vocabulary.avoid",
                       "verbal.content_rules.claims", "verbal.messaging.write", "verbal.messaging.avoid"),
       prohibitions=("no claim that is not in verbal.content_rules.claims",), gap_behavior="BLOCK"),
    _P(id="p05", order=5, title="References and evidence", objective="Per-source observations, inferences, unknowns, reuse and privacy limits.",
       evidence_refs=True, prohibitions=("never reconstruct [PII]", "source compositions stay evidence"), layout="table"),
    _P(id="p06", order=6, title="Identity overview", objective="Canonical identity, palette and type on one calibration page.",
       optional_paths=_LOGO, asset_refs=("mark", "wordmark"), layout="grid"),
    _P(id="p07", order=7, title="Primary logo", objective="The approved master, its exact text, contexts and placement.",
       required_paths=("visual.logo.mark",), optional_paths=("visual.logo.master_artifact", "visual.logo.wordmark", "visual.logo.placement"),
       asset_refs=("mark",), layout="specimen", gap_behavior="BLOCK"),
    _P(id="p08", order=8, title="Construction", objective="Real axes, boundaries and negative space of the master.",
       required_paths=("visual.logo.mark",), optional_paths=("visual.logo.master_artifact", "visual.logo.construction"),
       asset_refs=("mark",), layout="specimen", gap_behavior="BLOCK"),
    _P(id="p09", order=9, title="Wordmark", objective="Spelling, case, baseline and spacing of the wordmark.",
       optional_paths=("visual.logo.wordmark", "visual.logo.wordmark_case", "visual.logo.custom_lettering"),
       asset_refs=("wordmark",), layout="specimen"),
    _P(id="p10", order=10, title="Lockups", objective="Applicable primary, horizontal, stacked, wordmark-only and symbol-only lockups.",
       required_paths=("visual.logo.mark",), optional_paths=("visual.logo.master_artifact", "visual.logo.wordmark", "visual.logo.lockups"),
       asset_refs=("mark", "wordmark", "lockup"), layout="grid", gap_behavior="BLOCK"),
    _P(id="p11", order=11, title="Clear space", objective="Approved clear space with correct and crowded examples.",
       required_paths=("visual.logo.mark", "visual.logo.clear_space"), optional_paths=("visual.logo.master_artifact",),
       asset_refs=("mark",), layout="specimen", gap_behavior="LABEL"),
    _P(id="p12", order=12, title="Scale", objective="Approved minimum size and the mark at 16, 32, 64 and 128 px.",
       required_paths=("visual.logo.mark", "visual.logo.min_size"), optional_paths=("visual.logo.master_artifact", "visual.logo.small_size_variant"),
       asset_refs=("mark",), layout="specimen", gap_behavior="LABEL"),
    _P(id="p13", order=13, title="One colour and reverse", objective="Canonical silhouette in one colour and reversed, with pairings.",
       required_paths=("visual.logo.mark",), optional_paths=("visual.logo.master_artifact",), asset_refs=("mark",), layout="grid",
       gap_behavior="BLOCK"),
    _P(id="p14", order=14, title="Misuse", objective="Labelled misuse specimens, isolated from the masters.",
       required_paths=("visual.logo.mark",), optional_paths=("visual.logo.master_artifact",), asset_refs=("mark",), layout="grid",
       prohibitions=("misuse specimens are never masters",), gap_behavior="BLOCK"),
    _P(id="p15", order=15, title="Colour", objective="Colour roles, approved values, allowed pairings and measured contrast.",
       required_paths=("visual.color.ink", "visual.color.paper"), optional_paths=("visual.color.names", "visual.color.usage"),
       layout="matrix", gap_behavior="BLOCK"),
    _P(id="p16", order=16, title="Typography", objective="Type roles, specimens, hierarchy, licence and fallback status.",
       required_paths=("visual.typography.display",),
       optional_paths=("visual.typography.license", "visual.typography.fallback", "visual.typography.languages", "visual.typography.scale"),
       layout="specimen", gap_behavior="BLOCK"),
    _P(id="p17", order=17, title="Layout", objective="Grids, margins, rhythm and responsive rules.",
       optional_paths=("visual.grid.columns", "visual.grid.margin", "visual.grid.rhythm", "visual.grid.responsive"), gap_behavior="DECIDE"),
    _P(id="p18", order=18, title="Graphics", objective="Original primitives, icons, patterns and density.",
       optional_paths=("visual.shape_grammar.summary", "visual.shape_grammar.density", "visual.shape_grammar.icons"),
       prohibitions=("no copied compositions", "no competing marks"), gap_behavior="DECIDE"),
    _P(id="p19", order=19, title="Imagery", objective="Subjects, framing, light, treatment, rights and privacy.",
       optional_paths=("visual.imagery.style", "visual.imagery.subjects", "visual.imagery.rights", "visual.imagery.treatment"),
       prohibitions=("appearance is not a manufacturing specification",), gap_behavior="DECIDE"),
    _P(id="p20", order=20, title="Editorial and print", objective="Relevant cover, spread, imprint and collateral rules.",
       optional_paths=("production.output.print", "production.media.print_formats"),
       prohibitions=("no fictional client, contact or testimonial",), gap_behavior="DECIDE"),
    _P(id="p21", order=21, title="Digital", objective="Header, avatar, social and interface crops and responsiveness.",
       optional_paths=("production.platform.channels", "production.platform.avatar", "experience.responsive.rules"),
       prohibitions=("a static preview is not a working interface",), gap_behavior="DECIDE"),
    _P(id="p22", order=22, title="Motion", objective="Storyboard, transitions, continuity and the reduced-motion rule.",
       optional_paths=("visual.motion.pace", "visual.motion.emphasis", "visual.motion.reduced_motion"),
       prohibitions=("no claim of a rendered video",), gap_behavior="DECIDE"),
    _P(id="p23", order=23, title="Handoff", objective="Actual files, formats, licences, tokens and version references.",
       optional_paths=("production.licensing.fonts", "production.delivery.formats"), layout="table", reads_all_pages=True),
    _P(id="p24", order=24, title="Release", objective="Actual checks, unresolved decisions, approval and version records.",
       layout="table", reads_all_pages=True),
)

DEFAULT_MANIFEST = PageManifest(template_id=TEMPLATE_ID, template_version=TEMPLATE_VERSION, pages=DEFAULT_PAGES)

__all__ = ["APPLICABILITY_PREFIX", "DEFAULT_MANIFEST", "DEFAULT_PAGES", "Mode", "PageManifest", "PageSpec", "STYLE_PATHS",
           "TEMPLATE_ID", "TEMPLATE_VERSION"]
