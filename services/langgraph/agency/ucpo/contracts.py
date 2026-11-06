"""Typed contracts for the website production line: brief -> requirements -> IR -> source -> build -> QA -> proof.

Every model is strict and frozen, and hashes with the repository's ``canonical_hash``.
The brief supplies all copy; nothing downstream writes a claim of its own. Every
text-bearing node carries the requirement ids it satisfies (``req_refs``), so a
requirement can be traced from the brief through the IR and the source files to
the rendered DOM, where the same ids appear as ``data-req`` attributes.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash

UCPO_VERSION = "amc-ucpo/v1"
COMPILER_VERSION = "amc-ucpo-site-compiler/v1"
FRAMEWORK_TARGET = "next-static-export"
_SLUG = r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$"
_ID = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,79}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


# ------------------------------------------------------------------------------ brief


class Item(_Strict):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=600)


class ImageAsset(_Strict):
    """An image the site may show. Procedural images are composed on this host and owned; others need a recorded licence."""

    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    alt: str = Field(min_length=1, max_length=240)
    rights: Literal["procedural_owned", "owned", "licensed"] = "procedural_owned"
    license_ref: Optional[str] = Field(default=None, max_length=200)
    source: Literal["procedural:psem"] = "procedural:psem"
    motif_seed: int = Field(default=0, ge=0, le=10_000)

    @model_validator(mode="after")
    def _licence(self) -> "ImageAsset":
        if self.rights == "licensed" and not self.license_ref:
            raise ValueError("a licensed image needs a license_ref")
        return self


SectionKind = Literal["hero", "editorial", "statement", "index", "gallery", "contact"]


class SectionBrief(_Strict):
    kind: SectionKind
    heading: str = Field(min_length=1, max_length=140)
    body: str = Field(default="", max_length=1200)
    label: str = Field(default="", max_length=40)                    # technical micro-label, e.g. "PLATE 03"
    items: tuple[Item, ...] = Field(default=(), max_length=12)
    image: Optional[str] = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    cta: bool = False                                                 # carries the site's call to action
    anchor: Optional[str] = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,39}$")  # in-page id, a cta_target can name it


class PageBrief(_Strict):
    slug: str = Field(pattern=_SLUG)                                  # "index" is the home page
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=200)
    sections: tuple[SectionBrief, ...] = Field(min_length=1, max_length=10)


class WebsiteBrief(_Strict):
    """What the operator asked for. A hint about the project is never authority (the server resolves the project)."""

    schema_version: Literal["amc-ucpo-brief/v1"] = "amc-ucpo-brief/v1"
    organization: str = Field(min_length=1, max_length=80)
    tagline: str = Field(default="", max_length=140)
    offering: str = Field(default="", max_length=300)
    audience: str = Field(default="", max_length=300)
    locale: str = Field(default="en", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    cta_label: str = Field(default="", max_length=40)
    cta_target: str = Field(default="", max_length=80)                # "<page-slug>#<section>" inside the site only
    pages: tuple[PageBrief, ...] = Field(min_length=1, max_length=8)
    images: tuple[ImageAsset, ...] = Field(default=(), max_length=16)
    required_phrases: tuple[str, ...] = Field(default=(), max_length=20)
    forbidden_phrases: tuple[str, ...] = Field(default=(), max_length=20)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31 - 1)
    existing_project_id: Optional[str] = None

    @field_validator("cta_target")
    @classmethod
    def _internal(cls, v: str) -> str:
        if v and not re.fullmatch(r"[a-z0-9-]{1,40}(?:#[a-z0-9-]{1,40})?", v):
            raise ValueError("cta_target must be an internal '<page-slug>#<anchor>' reference")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> "WebsiteBrief":
        slugs = [p.slug for p in self.pages]
        if len(set(slugs)) != len(slugs):
            raise ValueError("page slugs must be unique")
        if "index" not in slugs:
            raise ValueError("a site needs an 'index' page")
        images = {i.asset_id for i in self.images}
        if len(images) != len(self.images):
            raise ValueError("image asset ids must be unique")
        for page in self.pages:
            for section in page.sections:
                if section.image and section.image not in images:
                    raise ValueError(f"section image {section.image!r} is not declared in images")
        if bool(self.cta_label) != bool(self.cta_target):
            raise ValueError("cta_label and cta_target come together")
        if self.cta_target:
            page, _, anchor = self.cta_target.partition("#")
            target = next((p for p in self.pages if p.slug == page), None)
            if target is None:
                raise ValueError("cta_target names a page that does not exist")
            if anchor and anchor not in {s.anchor for s in target.sections}:
                raise ValueError("cta_target names an anchor that no section on that page declares")
        carriers = [s for p in self.pages for s in p.sections if s.cta]
        if carriers and not self.cta_label:
            raise ValueError("a section carries the call to action but the brief has no cta_label")
        if self.cta_label and not carriers:
            raise ValueError("cta_label is set but no section carries the call to action")
        for page in self.pages:
            anchors = [s.anchor for s in page.sections if s.anchor]
            if len(set(anchors)) != len(anchors):
                raise ValueError(f"section anchors on page {page.slug!r} must be unique")
        if any(p.lower() in f.lower() or f.lower() in p.lower() for p in self.required_phrases for f in self.forbidden_phrases):
            raise ValueError("a phrase cannot be both required and forbidden")
        return self


# ------------------------------------------------------------------------------ requirements

RequirementKind = Literal[
    "LANG", "PAGE_EXISTS", "NAV_LINK", "BRAND_ON_PAGE", "SECTION_HEADING", "SECTION_BODY", "ITEM_TEXT", "LABEL_TEXT",
    "REQUIRED_PHRASE", "FORBIDDEN_PHRASE", "CTA", "IMAGE_ALT", "IMAGE_RIGHTS", "PSEM_COLOUR", "A11Y_AUTOMATED",
    "RESPONSIVE_REFLOW", "TEXT_ZOOM", "REDUCED_MOTION", "KEYBOARD_FOCUS", "NO_CONSOLE_ERRORS", "NO_EXTERNAL_REQUESTS",
]
Stage = Literal["ir", "source", "rendered"]


class Requirement(_Strict):
    req_id: str
    kind: RequirementKind
    statement: str
    subject: dict[str, Any]                      # e.g. {"page": "index", "text": "..."}
    mandatory: bool = True
    source_ref: str                              # brief path, e.g. "brief.pages[0].sections[1].heading"
    stages: tuple[Stage, ...]                    # where it must be evidenced


class RequirementsPackage(_Strict):
    schema_version: Literal["amc-ucpo-requirements/v1"] = "amc-ucpo-requirements/v1"
    project_ref: str
    brief_hash: str
    requirements: tuple[Requirement, ...]
    capability_gaps: tuple[dict[str, str], ...] = ()

    def by_id(self) -> dict[str, Requirement]:
        return {r.req_id: r for r in self.requirements}


# ------------------------------------------------------------------------------ site IR


class RouteSpec(_Strict):
    page_id: str
    path: str                                    # "/" or "/<slug>/"
    title: str


class SectionSpec(_Strict):
    section_id: str                              # "<page>-s<n>"
    kind: SectionKind
    component_id: str
    scheme: Literal["paper", "charcoal"]         # PSEM ground
    accent: Literal["signal_red", "amber", "none"]
    serial: str                                  # "01 / 04"
    label: str
    heading: str
    body: str
    items: tuple[Item, ...] = ()
    image: Optional[str] = None
    cta: Optional[dict[str, str]] = None         # {"label": ..., "href": ...}
    req_refs: dict[str, str]                     # field -> req id ("heading", "body", "item:0", "label", "cta", "image")


class PageSpec(_Strict):
    page_id: str
    route: str
    title: str
    description: str
    sections: tuple[SectionSpec, ...]
    req_refs: dict[str, str]                     # "page", "brand", "title"


class ComponentSpec(_Strict):
    component_id: str
    version: str
    props: tuple[str, ...]
    variants: tuple[str, ...]
    states: tuple[str, ...]
    responsive: dict[str, str]
    accessibility: tuple[str, ...]
    invariants: tuple[str, ...]
    mutable_axes: tuple[str, ...]


class SiteArchitecture(_Strict):
    schema_version: Literal["amc-ucpo-site-architecture/v1"] = "amc-ucpo-site-architecture/v1"
    routes: tuple[RouteSpec, ...]
    navigation: tuple[str, ...]                  # page ids, in order
    layouts: tuple[str, ...] = ("root",)
    components: tuple[str, ...]
    assets: tuple[str, ...]
    interactions: tuple[str, ...]                # e.g. "skip_link", "nav_disclosure"
    metadata: dict[str, dict[str, str]]          # page id -> {"title", "description"}
    responsive_rules: dict[str, str]
    accessibility_contracts: tuple[str, ...]


class WebsiteIR(_Strict):
    schema_version: Literal["amc-ucpo-website-ir/v1"] = "amc-ucpo-website-ir/v1"
    project_ref: str
    organization: str
    tagline: str
    locale: str
    requirements_ref: str                        # RequirementsPackage content hash
    site_architecture_ref: str                   # SiteArchitecture content hash
    genome_ref: str                              # CreativeGenome content hash
    token_refs: dict[str, str]                   # {"dtcg_source_hash": ..., "css_hash": ...}
    pages: tuple[PageSpec, ...]
    components: tuple[ComponentSpec, ...]
    images: tuple[ImageAsset, ...]
    interaction_specs: tuple[str, ...]
    framework_target: Literal["next-static-export"] = FRAMEWORK_TARGET
    verification_contract: tuple[str, ...]       # requirement ids the rendered site must evidence
    compiler_version: str = COMPILER_VERSION


# ------------------------------------------------------------------------------ source, build, preview, QA


class SourceFile(_Strict):
    path: str
    sha256: str
    bytes: int
    role: Literal["config", "route", "layout", "component", "style", "content", "asset", "doc", "contract"]
    req_refs: tuple[str, ...] = ()


class SourceTreeManifest(_Strict):
    schema_version: Literal["amc-ucpo-source-manifest/v1"] = "amc-ucpo-source-manifest/v1"
    website_ir_ref: str
    files: tuple[SourceFile, ...]
    dependencies: dict[str, str]                 # exact versions, from the workspace lockfile install
    tree_hash: str


class BuildResult(_Strict):
    schema_version: Literal["amc-ucpo-build/v1"] = "amc-ucpo-build/v1"
    status: Literal["PASSED", "FAILED", "BLOCKED_ISOLATION", "TIMED_OUT"]
    source_tree_hash: str
    isolation: dict[str, Any]                    # what was actually enforced
    steps: tuple[dict[str, Any], ...]            # {"name", "command", "exit_status", "duration_s", "log_tail"}
    dependency_manifest: dict[str, str]
    output_hash: Optional[str] = None
    output_files: int = 0
    output_bytes: int = 0


class CheckResult(_Strict):
    check: str
    route: Optional[str] = None
    viewport: Optional[str] = None
    result: Literal["PASS", "FAIL", "NOT_RUN", "INCONCLUSIVE", "BLOCKED"]
    detail: str = ""
    req_refs: tuple[str, ...] = ()
    evidence_ref: Optional[str] = None


class BrowserVerification(_Strict):
    schema_version: Literal["amc-ucpo-browser-verification/v1"] = "amc-ucpo-browser-verification/v1"
    status: Literal["PASSED", "FAILED", "BLOCKED", "NOT_RUN"]
    build_output_hash: Optional[str]
    browser: dict[str, Any]
    checks: tuple[CheckResult, ...]
    dom_evidence: dict[str, dict[str, list[str]]]   # route -> req id -> rendered texts
    screenshots: dict[str, str] = Field(default_factory=dict)  # "<route>@<viewport>" -> sha256
    blocked_requests: tuple[str, ...] = ()
    note: str = "automated checks only; they do not certify WCAG conformance"


class ConstraintWitness(_Strict):
    constraint_ref: str
    artifact_revision: str
    viewport: Optional[str]
    expected: str
    observed: str
    verification_method: str
    evidence_ref: Optional[str]
    result: Literal["PASS", "FAIL", "NOT_RUN", "INCONCLUSIVE", "BLOCKED"]


# ------------------------------------------------------------------------------ semantic coverage


RequirementStatus = Literal["PRESERVED", "APPROVED_CHANGE", "UNAPPROVED_CHANGE", "OMITTED", "UNRESOLVED", "NOT_APPLICABLE"]


class CoverageEntry(_Strict):
    req_id: str
    kind: RequirementKind
    mandatory: bool
    status: RequirementStatus
    stages: dict[str, str]                        # stage -> "PASS" | "FAIL" | "NOT_RUN" | "N/A"
    loss_stage: Optional[Stage] = None
    detail: str = ""


class SemanticDebtEntry(_Strict):
    req_id: str
    origin_revision: str                          # requirements package hash
    loss_stage: Optional[Stage]
    affected_artifacts: tuple[str, ...]
    severity: Literal["blocking", "major", "minor"]
    repair_owner: str
    repair_proposal: str
    verification: str
    resolution: Literal["OPEN", "RESOLVED"] = "OPEN"


class SemanticCoverageReport(_Strict):
    schema_version: Literal["amc-ucpo-coverage/v1"] = "amc-ucpo-coverage/v1"
    requirements_ref: str
    entries: tuple[CoverageEntry, ...]
    mandatory_resolved: int
    mandatory_applicable: int
    coverage: float | Literal["NOT_APPLICABLE"]
    debt: tuple[SemanticDebtEntry, ...]
    release_blocked: bool


# ------------------------------------------------------------------------------ release proof


class ReleaseProof(_Strict):
    """Binds exact revisions. Any changed revision makes the proof stale; an approval never authorizes deployment."""

    schema_version: Literal["amc-ucpo-release-proof/v1"] = "amc-ucpo-release-proof/v1"
    project_ref: str
    site_id: str
    revisions: dict[str, str]                     # brief, requirements, genome, tokens, site_ir, source, build, browser_qa, coverage
    artifact_refs: dict[str, str]                 # stage -> "artifact:<id>@v<n>"
    gates: dict[str, str]                         # gate -> PASS | FAIL | NOT_RUN | BLOCKED
    eligible_for_approval: bool
    reasons: tuple[str, ...]
    deployment: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"


def is_id(value: str) -> bool:
    return bool(_ID.match(value))


__all__ = [
    "BrowserVerification", "BuildResult", "COMPILER_VERSION", "CheckResult", "ComponentSpec", "ConstraintWitness",
    "CoverageEntry", "FRAMEWORK_TARGET", "ImageAsset", "Item", "PageBrief", "PageSpec", "ReleaseProof", "Requirement",
    "RequirementsPackage", "RouteSpec", "SectionBrief", "SectionSpec", "SemanticCoverageReport", "SemanticDebtEntry",
    "SiteArchitecture", "SourceFile", "SourceTreeManifest", "UCPO_VERSION", "WebsiteBrief", "WebsiteIR", "is_id",
]
