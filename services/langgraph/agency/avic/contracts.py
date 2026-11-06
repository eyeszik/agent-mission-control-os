"""AVIC typed records. Strict, frozen, versioned; identities are AMC-CANON-1 hashes.

These are typed projections over existing owners, not new authorities:

* the brief is a PromptIR ``AssetRequirement`` (``agency.prompt_compiler``);
* reference roles project onto PromptIR ``ReferenceRole`` (``PROMPT_ROLE``);
* ``BrandIR`` is a read-only projection of an approved palette/BrandCore source;
* persisted records are Project OS artifacts (Foundry ``store``), approvals are the
  shared ``approvals`` rows.

Every record carries ``schema_version``. Records are immutable; a change is a new
record with a new hash, never an in-place edit. Migration policy: a schema bump is a
new ``SCHEMA_VERSION`` and readers refuse versions they do not know.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash

SCHEMA_VERSION = "amc-avic/1"
COMPILER_VERSION = "amc-avic-compiler/0.1.0"
POLICY_VERSION = "amc-avic-policy/1"

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Hex = Annotated[str, Field(pattern=r"^#[0-9a-f]{6}$")]
Ident = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
Finite = Annotated[float, Field(allow_inf_nan=False, ge=-100_000, le=100_000)]
Unit = Annotated[float, Field(allow_inf_nan=False, ge=0, le=1)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def digest(self, *, exclude: frozenset[str] = frozenset()) -> str:
        return canonical_hash(self.model_dump(mode="json", exclude=set(exclude)))


class CapabilityState(str, Enum):
    IMPLEMENTED_VERIFIED = "IMPLEMENTED_VERIFIED"
    IMPLEMENTED_UNTESTED = "IMPLEMENTED_UNTESTED"
    PARTIAL = "PARTIAL"
    PROPOSED = "PROPOSED"
    BLOCKED = "BLOCKED"
    DEPRECATED = "DEPRECATED"
    UNKNOWN = "UNKNOWN"


class OutputProfile(str, Enum):
    NATIVE_EDITABLE_VECTOR = "NATIVE_EDITABLE_VECTOR"
    NATIVE_FIDELITY_VECTOR = "NATIVE_FIDELITY_VECTOR"
    STRUCTURED_ILLUSTRATIVE_VECTOR = "STRUCTURED_ILLUSTRATIVE_VECTOR"
    HYBRID_SVG = "HYBRID_SVG"
    RASTER_FINAL = "RASTER_FINAL"


NATIVE_PROFILES = frozenset({OutputProfile.NATIVE_EDITABLE_VECTOR, OutputProfile.NATIVE_FIDELITY_VECTOR,
                             OutputProfile.STRUCTURED_ILLUSTRATIVE_VECTOR})


class Classification(str, Enum):
    """ACE FILTER outcome for every extracted intent item."""
    VERIFIED = "VERIFIED"        # stated in an authoritative field of the brief
    INFERRED = "INFERRED"        # derived deterministically from stated facts
    PROPOSED = "PROPOSED"        # a default the compiler chose; mutable
    UNSUPPORTED = "UNSUPPORTED"  # asked for, but no implemented capability exists
    PROHIBITED = "PROHIBITED"    # asked for, and policy forbids it


class Provenance(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    ARTIST_DEFINED = "ARTIST_DEFINED"
    APPROXIMATED = "APPROXIMATED"


class Result(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_MEASURED = "NOT_MEASURED"


class ReferenceRole(str, Enum):
    COLOR = "COLOR"
    COMPOSITION = "COMPOSITION"
    GEOMETRY = "GEOMETRY"
    TYPOGRAPHY = "TYPOGRAPHY"
    MATERIAL = "MATERIAL"
    LIGHTING = "LIGHTING"
    ATMOSPHERE = "ATMOSPHERE"
    TEXTURE = "TEXTURE"
    IDENTITY = "IDENTITY"


# Projection onto the canonical PromptIR reference roles (agency.prompt_compiler.ReferenceRole).
PROMPT_ROLE: dict[ReferenceRole, str] = {
    ReferenceRole.IDENTITY: "IDENTITY",
    ReferenceRole.COMPOSITION: "COMPOSITION",
    ReferenceRole.GEOMETRY: "COMPOSITION",
    **{r: "STYLE" for r in (ReferenceRole.COLOR, ReferenceRole.TYPOGRAPHY, ReferenceRole.MATERIAL,
                            ReferenceRole.LIGHTING, ReferenceRole.ATMOSPHERE, ReferenceRole.TEXTURE)},
}


class Check(Strict):
    check: str = Field(min_length=1, max_length=80)
    level: Literal["Q0", "Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10"]
    result: Result
    detail: str = Field(default="", max_length=600)


# ------------------------------------------------------------------ intent


class IntentItem(Strict):
    item_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    kind: Literal["goal", "hard_requirement", "mutable", "acceptance", "exact_text", "negative", "output_profile"]
    text: str = Field(min_length=1, max_length=600)
    classification: Classification
    source: str = Field(min_length=1, max_length=120)
    reason: str = Field(default="", max_length=300)


class IntentIR(Strict):
    schema_version: Literal["amc-avic/1"] = SCHEMA_VERSION
    asset_id: str = Field(min_length=1, max_length=120)
    requirement_hash: Hash  # canonical hash of the PromptIR AssetRequirement
    output_profile: OutputProfile
    style_profile: str = Field(min_length=1, max_length=64)
    width: int = Field(ge=64, le=4096, strict=True)
    height: int = Field(ge=64, le=4096, strict=True)
    items: tuple[IntentItem, ...]
    exact_text: tuple[str, ...]

    @model_validator(mode="after")
    def unique_items(self):
        ids = [i.item_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate intent item ids")
        return self

    @property
    def intent_hash(self) -> str:
        return self.digest()

    def exact_text_ids(self) -> tuple[str, ...]:
        """Intent item ids aligned with ``exact_text`` (prohibited entries are in neither)."""
        return tuple(i.item_id for i in self.items if i.kind == "exact_text" and i.classification == Classification.VERIFIED)

    def blocked(self) -> tuple[IntentItem, ...]:
        # A prohibited goal blocks (the request asks for something policy forbids); negatives never block
        # ("do not publish" is fine). Unsupported only blocks what must be delivered.
        return tuple(i for i in self.items if
                     (i.classification == Classification.PROHIBITED and i.kind in {"goal", "hard_requirement", "exact_text",
                                                                                   "acceptance", "output_profile"})
                     or (i.classification == Classification.UNSUPPORTED and i.kind in {"hard_requirement", "exact_text",
                                                                                       "output_profile"}))


# ------------------------------------------------------------------ references and brand


class ReferenceAsset(Strict):
    ref_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    sha256: Hash
    role: ReferenceRole
    prompt_role: str
    mime_type: Literal["image/png", "image/jpeg"]
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    observed_palette: tuple[tuple[Hex, Unit], ...]
    rights: Literal["AUTHORIZED", "UNVERIFIED"]
    semantic_analysis: Literal["NOT_IMPLEMENTED"] = "NOT_IMPLEMENTED"


class ReferenceManifest(Strict):
    schema_version: Literal["amc-avic/1"] = SCHEMA_VERSION
    references: tuple[ReferenceAsset, ...] = ()
    excluded: tuple[str, ...] = ()        # ref ids dropped and why ("ref:reason")
    conflicts: tuple[str, ...] = ()       # explicit role conflicts, never silently resolved


class BrandIR(Strict):
    """Read-only projection of an approved palette/brand source. It can never widen authority."""
    schema_version: Literal["amc-avic/1"] = SCHEMA_VERSION
    source: str = Field(min_length=1, max_length=200)      # e.g. "foundry.psem.PALETTE" or an artifact ref
    source_hash: Hash
    approved: bool
    palette: dict[str, Hex]
    roles: dict[str, str]                                  # semantic role -> palette key
    typography: tuple[str, ...] = ("Helvetica Neue", "Arial", "sans-serif")
    protected_invariants: tuple[str, ...] = ()
    allowed_variations: tuple[str, ...] = ()
    max_signal_accents: int = Field(default=1, ge=0, le=6)

    @model_validator(mode="after")
    def roles_resolve(self):
        missing = [k for k, v in self.roles.items() if v not in self.palette]
        if missing:
            raise ValueError(f"brand roles reference unknown palette keys: {missing}")
        return self


# ------------------------------------------------------------------ scene


class GradientStop(Strict):
    offset: Unit
    color: Hex
    opacity: Unit = 1.0


class Gradient(Strict):
    gradient_id: Ident
    kind: Literal["linear", "radial"]
    # linear: x1,y1,x2,y2 ; radial: cx,cy,r,fx,fy  (objectBoundingBox fractions)
    coords: dict[str, Unit]
    stops: tuple[GradientStop, ...] = Field(min_length=2, max_length=16)
    provenance: Provenance = Provenance.ARTIST_DEFINED

    @model_validator(mode="after")
    def coords_match_kind(self):
        need = {"x1", "y1", "x2", "y2"} if self.kind == "linear" else {"cx", "cy", "r"}
        if not need <= set(self.coords) or set(self.coords) - need - {"fx", "fy"}:
            raise ValueError(f"{self.kind} gradient needs exactly {sorted(need)} (+fx/fy for radial)")
        if [s.offset for s in self.stops] != sorted(s.offset for s in self.stops):
            raise ValueError("gradient stops must be ordered")
        return self


class PathCommand(Strict):
    op: Literal["M", "L", "C", "Q", "Z"]
    coords: tuple[Finite, ...] = ()

    @model_validator(mode="after")
    def arity(self):
        n = {"M": 2, "L": 2, "C": 6, "Q": 4, "Z": 0}[self.op]
        if len(self.coords) != n:
            raise ValueError(f"{self.op} takes {n} coordinates")
        return self


class Geometry(Strict):
    primitive: Literal["rect", "circle", "ellipse", "polygon", "path", "text", "group"]
    params: dict[str, Finite] = Field(default_factory=dict)
    points: tuple[tuple[Finite, Finite], ...] = ()
    path: tuple[PathCommand, ...] = ()
    rotate: Finite = 0.0
    clip_to: Optional[Ident] = None

    @model_validator(mode="after")
    def required(self):
        need = {"rect": {"x", "y", "width", "height"}, "circle": {"cx", "cy", "r"}, "ellipse": {"cx", "cy", "rx", "ry"},
                "text": {"x", "y"}, "polygon": set(), "path": set(), "group": set()}[self.primitive]
        if not need <= set(self.params):
            raise ValueError(f"{self.primitive} needs {sorted(need)}")
        if self.primitive == "polygon" and len(self.points) < 3:
            raise ValueError("polygon needs at least three points")
        if self.primitive == "path" and (not self.path or self.path[0].op != "M"):
            raise ValueError("path must start with M")
        for k in ("width", "height", "r", "rx", "ry"):
            if k in self.params and self.params[k] <= 0:
                raise ValueError(f"{k} must be positive")
        return self


class Appearance(Strict):
    fill: Optional[str] = None            # "#rrggbb" or "url(#gradient-id)" or "none"
    stroke: Optional[str] = None
    stroke_width: Finite = 0.0
    opacity: Unit = 1.0
    font_size: Optional[Finite] = None
    font_weight: Optional[Literal[400, 500, 700, 900]] = None
    letter_spacing: Optional[Finite] = None
    text_anchor: Optional[Literal["start", "middle", "end"]] = None
    blur: Optional[Literal["soft", "grain"]] = None   # only the two allowlisted filters

    @model_validator(mode="after")
    def paints(self):
        import re

        for name in ("fill", "stroke"):
            v = getattr(self, name)
            if v is not None and not re.fullmatch(r"#[0-9a-f]{6}|none|url\(#[a-z][a-z0-9-]{0,63}\)", v):
                raise ValueError(f"{name} must be a lowercase hex colour, none, or a local gradient reference")
        return self


class SceneObject(Strict):
    object_id: Ident
    semantic_role: Literal["background", "headline", "motif", "material_object", "lighting", "annotation", "texture",
                           "shadow", "highlight", "region", "group", "rule"]
    parent_id: Optional[Ident] = None
    representation: Literal["native_vector", "text", "raster_embedded"] = "native_vector"
    geometry: Geometry
    appearance: Appearance = Field(default_factory=Appearance)
    text: Optional[str] = Field(default=None, max_length=300)
    dependencies: tuple[Ident, ...] = ()
    requirement_refs: tuple[str, ...] = ()
    protected: bool = False
    material_ref: Optional[str] = None

    @model_validator(mode="after")
    def text_only_on_text(self):
        if (self.geometry.primitive == "text") != (self.text is not None):
            raise ValueError("text content belongs exactly to text primitives")
        return self


class SceneConstraint(Strict):
    constraint_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    kind: Literal["exact_text", "protected_geometry", "palette", "contrast", "single_accent", "resource", "profile"]
    target: tuple[str, ...] = ()
    severity: Literal["CRITICAL", "MAJOR", "MINOR"] = "CRITICAL"
    tolerance: Optional[Finite] = None
    verification: str = Field(min_length=1, max_length=200)
    requirement_refs: tuple[str, ...] = ()


class Evidence(Strict):
    source: str = Field(min_length=1, max_length=120)          # ref id or "brief" or "profile:<id>"
    observation: str = Field(min_length=1, max_length=300)
    interpretation: str = Field(min_length=1, max_length=300)
    provenance: Provenance
    confidence: Unit


class DocumentSpec(Strict):
    width: int = Field(ge=64, le=4096, strict=True)
    height: int = Field(ge=64, le=4096, strict=True)
    color_space: Literal["sRGB"] = "sRGB"
    output_profile: OutputProfile
    title: str = Field(min_length=1, max_length=120)
    source_digest: Hash   # intent hash the scene was compiled from


class Composition(Strict):
    grid_columns: int = Field(ge=1, le=24)
    margin: Finite
    focal_object: Optional[Ident] = None
    negative_space_target: Unit = 0.4
    style_profile: str


class CompilationSpec(Strict):
    compiler_version: str = COMPILER_VERSION
    schema_version: Literal["amc-avic/1"] = SCHEMA_VERSION
    seed: int = Field(ge=0, le=2**31 - 1)
    brand_hash: Hash
    reference_manifest_hash: Hash
    max_objects: int = Field(default=400, ge=1, le=20_000)
    max_svg_bytes: int = Field(default=512_000, ge=1_000, le=3_000_000)


class SceneIR(Strict):
    schema_version: Literal["amc-avic/1"] = SCHEMA_VERSION
    document: DocumentSpec
    gradients: tuple[Gradient, ...] = ()
    objects: tuple[SceneObject, ...] = Field(min_length=1)
    composition: Composition
    constraints: tuple[SceneConstraint, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    compilation: CompilationSpec

    @model_validator(mode="after")
    def integrity(self):
        ids = [o.object_id for o in self.objects] + [g.gradient_id for g in self.gradients]
        if len(ids) != len(set(ids)):
            raise ValueError("object and gradient ids must be unique")
        known = {o.object_id for o in self.objects}
        grads = {g.gradient_id for g in self.gradients}
        for o in self.objects:
            for dep in o.dependencies:
                if dep not in known:
                    raise ValueError(f"{o.object_id} depends on unknown {dep}")
            if o.parent_id and o.parent_id not in known:
                raise ValueError(f"{o.object_id} has unknown parent {o.parent_id}")
            if o.geometry.clip_to and o.geometry.clip_to not in known:
                raise ValueError(f"{o.object_id} clips to unknown {o.geometry.clip_to}")
            for paint in (o.appearance.fill, o.appearance.stroke):
                if paint and paint.startswith("url(#") and paint[5:-1] not in grads:
                    raise ValueError(f"{o.object_id} references unknown gradient {paint}")
            if o.representation == "raster_embedded" and self.document.output_profile in NATIVE_PROFILES:
                raise ValueError("raster content is not allowed in a native vector profile")
        if len(self.objects) > self.compilation.max_objects:
            raise ValueError("object budget exceeded")
        return self

    @property
    def scene_hash(self) -> str:
        return self.digest()

    def object(self, object_id: str) -> SceneObject:
        for o in self.objects:
            if o.object_id == object_id:
                return o
        raise KeyError(object_id)


# ------------------------------------------------------------------ candidates, evaluation, defects, repair, release


class CandidateStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RENDERED = "RENDERED"
    EVALUATED = "EVALUATED"
    SELECTED = "SELECTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EvaluationReport(Strict):
    schema_version: Literal["amc-avic/1"] = SCHEMA_VERSION
    scene_hash: Hash
    svg_sha256: Hash
    png_sha256: Optional[Hash] = None
    renderer: str
    renderer_version: Optional[str] = None
    checks: tuple[Check, ...]
    metrics: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.result == Result.PASS for c in self.checks)

    def failures(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if c.result != Result.PASS)


class VectorCandidate(Strict):
    candidate_id: str = Field(pattern=r"^cand-[a-f0-9]{16}$")
    scene_hash: Hash
    svg_sha256: Hash
    output_profile: OutputProfile
    status: CandidateStatus
    parent_candidate: Optional[str] = None
    evaluation_hash: Optional[Hash] = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class DefectIR(Strict):
    schema_version: Literal["amc-avic/1"] = SCHEMA_VERSION
    defect_id: str = Field(pattern=r"^def-[a-f0-9]{12}$")
    artifact_version: Hash            # scene hash the defect was observed on
    kind: Literal["contrast", "off_palette", "accent_budget", "text_overflow", "exact_text", "protected_geometry",
                  "resource", "blank_render", "out_of_canvas"]
    region_refs: tuple[str, ...]
    requirement_refs: tuple[str, ...] = ()
    symptoms: str = Field(min_length=1, max_length=400)
    evidence_refs: tuple[str, ...]
    candidate_causes: tuple[str, ...]  # hypotheses, never asserted facts
    confidence: Unit
    severity: Literal["CRITICAL", "MAJOR", "MINOR"]
    dependency_refs: tuple[str, ...] = ()
    repair_options: tuple[str, ...] = ()
    verification_plan: str = Field(min_length=1, max_length=300)
    status: Literal["OBSERVED", "MISSING_EVIDENCE"] = "OBSERVED"

    @model_validator(mode="after")
    def evidence(self):
        if self.status == "OBSERVED" and not self.evidence_refs:
            raise ValueError("an observed defect needs evidence; use MISSING_EVIDENCE otherwise")
        return self


class TransformationRecord(Strict):
    object_id: Ident
    field: str = Field(min_length=1, max_length=80)
    before: Any
    after: Any


class RepairProposal(Strict):
    schema_version: Literal["amc-avic/1"] = SCHEMA_VERSION
    proposal_id: str = Field(pattern=r"^rep-[a-f0-9]{12}$")
    defect_id: str
    parent_scene_hash: Hash
    affected: tuple[str, ...]           # the minimal dependency closure that must be re-rendered
    transformations: tuple[TransformationRecord, ...] = Field(min_length=1)
    hypothesis: str = Field(min_length=1, max_length=300)
    rebuild: Literal["incremental", "full"]
    attempt: int = Field(ge=1, le=3)


class VerificationFinding(Strict):
    finding_id: str = Field(min_length=1, max_length=80)
    level: str
    result: Result
    detail: str = Field(default="", max_length=600)


class ReleaseManifest(Strict):
    schema_version: Literal["amc-avic/1"] = SCHEMA_VERSION
    project_id: str
    output_profile: OutputProfile
    compiler_version: str = COMPILER_VERSION
    renderer: str
    renderer_version: Optional[str]
    policy_version: str = POLICY_VERSION
    files: dict[str, dict[str, Any]]     # name -> {artifact_id, version, sha256}
    source_hashes: dict[str, str]
    quality: dict[str, str]              # check -> PASS/FAIL/BLOCKED/NOT_MEASURED
    approval_id: Optional[str] = None
    release_allowed: bool
    release_reasons: tuple[str, ...] = ()
    external_effects: Literal["none"] = "none"
