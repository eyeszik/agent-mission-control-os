"""VNEXUS Brand Genome: a versioned, layered, constraint-bearing description of a brand.

Pure and deterministic. Persistence, authorization and approvals live in
``persistence/vnexus.py`` and ``api/routes/vnexus.py``; this module only
defines the document, how layers resolve, and how two documents differ.

Resolution follows the client precheck in ``apps/web/lib/design/brand-genome.ts``
(PR #127) and extends it:

* Layers apply in scope order brand -> project -> page -> component -> asset.
  A layer out of order is skipped (``SCOPE_ORDER``).
* Only APPROVED layers are authoritative. Any other layer is reported key by
  key (``UNAPPROVED_OVERRIDE``) and skipped, unless it is the one draft being
  previewed, and then it is labelled preview and never authoritative.
* An ``IMMUTABLE`` constraint locks a key for every descendant scope; a
  different value is skipped (``IMMUTABLE_OVERRIDE``).
* Constraints accumulate. A descendant can add constraints but cannot remove
  an ancestor's; a descendant value that violates an inherited constraint is
  skipped (``CONSTRAINT_VIOLATION``).

Nothing here is a quality judgement. Constraint findings are deterministic
checks; whether a brand is good stays a human decision.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Iterable, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

GENOME_SCHEMA = "amc-vnexus-genome/v1"
MAX_KEYS_PER_CHROMOSOME = 200
MAX_CONSTRAINTS = 200
_KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+){0,5}$")
_HEX = re.compile(r"^#[0-9a-f]{6}$")

Scalar = Union[str, int, float, bool, None]
Value = Union[Scalar, list[str]]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Chromosome(str, Enum):
    STRATEGY = "strategy"
    VISUAL = "visual"
    VERBAL = "verbal"
    EXPERIENCE = "experience"
    PRODUCTION = "production"


CHROMOSOME_DOMAINS: dict[Chromosome, tuple[str, ...]] = {
    Chromosome.STRATEGY: ("positioning", "audience", "differentiation", "promise", "values", "competitive_territory"),
    Chromosome.VISUAL: ("color", "typography", "grid", "shape_grammar", "logo", "imagery", "motion"),
    Chromosome.VERBAL: ("voice", "tone", "vocabulary", "messaging", "content_rules"),
    Chromosome.EXPERIENCE: ("interaction", "accessibility", "navigation", "responsive"),
    Chromosome.PRODUCTION: ("output", "media", "platform", "licensing", "delivery"),
}


class Scope(str, Enum):
    BRAND = "brand"
    PROJECT = "project"
    PAGE = "page"
    COMPONENT = "component"
    ASSET = "asset"


SCOPE_ORDER: tuple[Scope, ...] = (Scope.BRAND, Scope.PROJECT, Scope.PAGE, Scope.COMPONENT, Scope.ASSET)


class VersionStatus(str, Enum):
    DRAFT = "DRAFT"
    EXPERIMENTAL = "EXPERIMENTAL"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


EDITABLE_STATUSES = frozenset({VersionStatus.DRAFT, VersionStatus.EXPERIMENTAL})
FROZEN_STATUSES = frozenset({VersionStatus.IN_REVIEW, VersionStatus.APPROVED, VersionStatus.REJECTED, VersionStatus.SUPERSEDED})

# action -> {from_status: to_status}. Anything absent is refused.
TRANSITIONS: dict[str, dict[VersionStatus, VersionStatus]] = {
    "submit": {VersionStatus.DRAFT: VersionStatus.IN_REVIEW},
    "approve": {VersionStatus.IN_REVIEW: VersionStatus.APPROVED},
    "reject": {VersionStatus.IN_REVIEW: VersionStatus.REJECTED},
    "withdraw": {VersionStatus.IN_REVIEW: VersionStatus.DRAFT},
    "supersede": {VersionStatus.APPROVED: VersionStatus.SUPERSEDED},
}


class GenomeTransitionError(ValueError):
    """The requested lifecycle move is not allowed from the version's current status."""


def next_status(current: VersionStatus, action: str) -> VersionStatus:
    target = TRANSITIONS.get(action, {}).get(VersionStatus(current))
    if target is None:
        raise GenomeTransitionError(f"cannot {action} a genome version in status {VersionStatus(current).value}")
    return target


class ProvenanceKind(str, Enum):
    USER_SUPPLIED = "USER_SUPPLIED"
    IMPORTED = "IMPORTED"
    INFERRED = "INFERRED"
    DEFAULTED = "DEFAULTED"
    UNRESOLVED = "UNRESOLVED"


class ConstraintKind(str, Enum):
    IMMUTABLE = "IMMUTABLE"            # descendants may not change the value
    REQUIRED = "REQUIRED"              # the resolved genome must carry a value
    ALLOWED_VALUES = "ALLOWED_VALUES"  # params.values: list of allowed scalars
    RANGE = "RANGE"                    # params.min / params.max (numeric, inclusive)
    HEX_COLOR = "HEX_COLOR"            # value must be #rrggbb lower-case
    MIN_CONTRAST = "MIN_CONTRAST"      # params.against: key; params.ratio: WCAG 2.2 ratio


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKING = "BLOCKING"


class GenomeConstraint(_Strict):
    constraint_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,79}$")
    key: str
    kind: ConstraintKind
    params: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = Severity.BLOCKING
    rationale: str = Field(default="", max_length=500)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        chromosome, _, rest = value.partition(".")
        if chromosome not in {c.value for c in Chromosome} or not rest or not _KEY.match(rest):
            raise ValueError(f"constraint key {value!r} must be '<chromosome>.<key>'")
        return value

    @model_validator(mode="after")
    def _params(self) -> "GenomeConstraint":
        p = self.params
        if self.kind is ConstraintKind.ALLOWED_VALUES:
            values = p.get("values")
            if not isinstance(values, list) or not values or len(values) > 100:
                raise ValueError("ALLOWED_VALUES needs params.values: a non-empty list (<= 100)")
        elif self.kind is ConstraintKind.RANGE:
            lo, hi = p.get("min"), p.get("max")
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lo, hi)) or lo > hi:
                raise ValueError("RANGE needs numeric params.min <= params.max")
        elif self.kind is ConstraintKind.MIN_CONTRAST:
            if not isinstance(p.get("against"), str) or not isinstance(p.get("ratio"), (int, float)) or not 1 <= p["ratio"] <= 21:
                raise ValueError("MIN_CONTRAST needs params.against (a key) and params.ratio in [1, 21]")
        elif p:
            raise ValueError(f"{self.kind.value} takes no params")
        return self


class GenomeProvenance(_Strict):
    key: str
    kind: ProvenanceKind
    source_ref: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=300)


class GenomeDocument(_Strict):
    """One scope's contribution: chromosome values, the constraints it adds, and where values came from."""

    schema_version: str = GENOME_SCHEMA
    chromosomes: dict[Chromosome, dict[str, Value]] = Field(default_factory=dict)
    constraints: tuple[GenomeConstraint, ...] = ()
    provenance: tuple[GenomeProvenance, ...] = ()

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, value: str) -> str:
        if value != GENOME_SCHEMA:
            raise ValueError(f"unsupported genome schema {value!r}")
        return value

    @field_validator("chromosomes")
    @classmethod
    def _values(cls, value: dict[Chromosome, dict[str, Value]]) -> dict[Chromosome, dict[str, Value]]:
        for chromosome, entries in value.items():
            if len(entries) > MAX_KEYS_PER_CHROMOSOME:
                raise ValueError(f"{chromosome.value}: more than {MAX_KEYS_PER_CHROMOSOME} keys")
            for key, item in entries.items():
                if not _KEY.match(key):
                    raise ValueError(f"{chromosome.value}.{key}: keys are lower-case dotted identifiers")
                if isinstance(item, float) and item != item:
                    raise ValueError(f"{chromosome.value}.{key}: NaN is not a value")
                if isinstance(item, str) and len(item) > 2000:
                    raise ValueError(f"{chromosome.value}.{key}: value longer than 2000 characters")
                if isinstance(item, list) and (len(item) > 50 or not all(isinstance(x, str) and len(x) <= 300 for x in item)):
                    raise ValueError(f"{chromosome.value}.{key}: lists hold <= 50 strings of <= 300 characters")
        return value

    @model_validator(mode="after")
    def _constraints(self) -> "GenomeDocument":
        if len(self.constraints) > MAX_CONSTRAINTS:
            raise ValueError(f"more than {MAX_CONSTRAINTS} constraints")
        ids = [c.constraint_id for c in self.constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("constraint ids must be unique within a document")
        return self

    def flatten(self) -> dict[str, Value]:
        return {f"{c.value}.{k}": v for c, entries in sorted(self.chromosomes.items(), key=lambda kv: kv[0].value)
                for k, v in sorted(entries.items())}

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def document_from_flat(values: dict[str, Value], *, constraints: Sequence[GenomeConstraint] = (),
                       provenance: Sequence[GenomeProvenance] = ()) -> GenomeDocument:
    chromosomes: dict[Chromosome, dict[str, Value]] = {}
    for key, value in values.items():
        head, _, rest = key.partition(".")
        chromosomes.setdefault(Chromosome(head), {})[rest] = value
    return GenomeDocument(chromosomes=chromosomes, constraints=tuple(constraints), provenance=tuple(provenance))


class GenomeLayer(_Strict):
    scope: Scope
    scope_ref: str = Field(min_length=1, max_length=300)
    status: VersionStatus
    document: GenomeDocument
    version_id: Optional[str] = None
    version: Optional[int] = None


class ConflictReason(str, Enum):
    SCOPE_ORDER = "SCOPE_ORDER"
    UNAPPROVED_OVERRIDE = "UNAPPROVED_OVERRIDE"
    IMMUTABLE_OVERRIDE = "IMMUTABLE_OVERRIDE"
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"


class GenomeConflict(_Strict):
    key: str
    reason: ConflictReason
    scope_ref: str
    detail: str = ""
    constraint_id: Optional[str] = None


class ConstraintFinding(_Strict):
    constraint_id: str
    key: str
    kind: ConstraintKind
    severity: Severity
    passed: bool
    detail: str
    declared_by: str


class Resolution(_Strict):
    values: dict[str, Value]
    sources: dict[str, str]                 # key -> scope_ref that supplied the winning value
    constraints: tuple[GenomeConstraint, ...]
    constraint_owner: dict[str, str]        # constraint_id -> scope_ref that declared it
    conflicts: tuple[GenomeConflict, ...]
    findings: tuple[ConstraintFinding, ...]
    applied_scopes: tuple[str, ...]
    preview_scope: Optional[str] = None
    authoritative: bool

    @property
    def blocking(self) -> list[ConstraintFinding]:
        return [f for f in self.findings if not f.passed and f.severity is Severity.BLOCKING]

    @property
    def resolution_hash(self) -> str:
        return canonical_hash({"values": self.values, "constraints": [c.model_dump(mode="json") for c in self.constraints],
                               "applied": list(self.applied_scopes), "preview": self.preview_scope})


def _check_value(constraint: GenomeConstraint, value: Value, values: dict[str, Value]) -> Optional[str]:
    """None when the value satisfies the constraint, else a reason. IMMUTABLE/REQUIRED are handled by callers."""
    kind, p = constraint.kind, constraint.params
    if kind is ConstraintKind.ALLOWED_VALUES:
        if isinstance(value, list):
            outside = [v for v in value if v not in p["values"]]
            return f"{outside} not in allowed values" if outside else None
        return None if value in p["values"] else f"{value!r} not in allowed values {p['values']}"
    if kind is ConstraintKind.RANGE:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return f"{value!r} is not numeric"
        return None if p["min"] <= value <= p["max"] else f"{value} outside [{p['min']}, {p['max']}]"
    if kind is ConstraintKind.HEX_COLOR:
        return None if isinstance(value, str) and _HEX.match(value) else f"{value!r} is not a #rrggbb colour"
    if kind is ConstraintKind.MIN_CONTRAST:
        other = values.get(p["against"])
        if not (isinstance(value, str) and _HEX.match(value) and isinstance(other, str) and _HEX.match(other)):
            return None  # evaluated on the resolved genome, where a missing pair is its own finding
        ratio = wcag_contrast_ratio(value, other)
        return None if ratio >= float(p["ratio"]) else f"contrast {ratio}:1 against {p['against']} is below {p['ratio']}:1"
    return None


def evaluate_constraints(values: dict[str, Value], constraints: Iterable[GenomeConstraint],
                         owner: Optional[dict[str, str]] = None) -> tuple[ConstraintFinding, ...]:
    """Deterministic findings for every constraint over a resolved value map."""
    out: list[ConstraintFinding] = []
    for c in sorted(constraints, key=lambda c: c.constraint_id):
        present = values.get(c.key) is not None
        if c.kind is ConstraintKind.IMMUTABLE:
            reason = None
        elif c.kind is ConstraintKind.REQUIRED or not present:
            reason = None if present else "no value resolved for a constrained key"
        elif c.kind is ConstraintKind.MIN_CONTRAST and not all(
                isinstance(values.get(k), str) and _HEX.match(values[k]) for k in (c.key, c.params["against"])):
            reason = f"contrast pair {c.key}/{c.params['against']} is not two colours"
        else:
            reason = _check_value(c, values[c.key], values)
        detail = "locked for descendant scopes" if c.kind is ConstraintKind.IMMUTABLE else (reason or "satisfied")
        out.append(ConstraintFinding(constraint_id=c.constraint_id, key=c.key, kind=c.kind, severity=c.severity,
                                     passed=reason is None, detail=detail, declared_by=(owner or {}).get(c.constraint_id, "")))
    return tuple(out)


def resolve(layers: Sequence[GenomeLayer], *, preview_ref: Optional[str] = None) -> Resolution:
    """Resolve layers into one value map. ``preview_ref`` names a non-approved layer to apply as a preview."""
    values: dict[str, Value] = {}
    sources: dict[str, str] = {}
    constraints: dict[str, GenomeConstraint] = {}
    owner: dict[str, str] = {}
    conflicts: list[GenomeConflict] = []
    applied: list[str] = []
    last = -1
    previewed: Optional[str] = None
    for layer in layers:
        order = SCOPE_ORDER.index(layer.scope)
        if order < last:
            conflicts.append(GenomeConflict(key="*", reason=ConflictReason.SCOPE_ORDER, scope_ref=layer.scope_ref,
                                            detail=f"{layer.scope.value} layer after a narrower scope"))
            continue
        last = order
        is_preview = preview_ref is not None and layer.scope_ref == preview_ref and layer.status is not VersionStatus.APPROVED
        if layer.status is not VersionStatus.APPROVED and not is_preview:
            for key in layer.document.flatten():
                conflicts.append(GenomeConflict(key=key, reason=ConflictReason.UNAPPROVED_OVERRIDE, scope_ref=layer.scope_ref,
                                                detail=f"{layer.status.value} layers are not authoritative"))
            continue
        if is_preview:
            previewed = layer.scope_ref
        applied.append(layer.scope_ref)
        inherited = dict(constraints)
        for key, value in layer.document.flatten().items():
            locked = next((c for c in inherited.values() if c.key == key and c.kind is ConstraintKind.IMMUTABLE), None)
            if locked is not None and key in values and values[key] != value:
                conflicts.append(GenomeConflict(key=key, reason=ConflictReason.IMMUTABLE_OVERRIDE, scope_ref=layer.scope_ref,
                                                constraint_id=locked.constraint_id,
                                                detail=f"locked by {owner[locked.constraint_id]}"))
                continue
            violated = next(((c, r) for c in sorted(inherited.values(), key=lambda c: c.constraint_id)
                             if c.key == key and (r := _check_value(c, value, {**values, key: value}))), None)
            if violated is not None:
                c, reason = violated
                conflicts.append(GenomeConflict(key=key, reason=ConflictReason.CONSTRAINT_VIOLATION, scope_ref=layer.scope_ref,
                                                constraint_id=c.constraint_id, detail=reason))
                continue
            values[key] = value
            sources[key] = layer.scope_ref
        for c in layer.document.constraints:
            if c.constraint_id in constraints and constraints[c.constraint_id] != c:
                conflicts.append(GenomeConflict(key=c.key, reason=ConflictReason.CONSTRAINT_VIOLATION, scope_ref=layer.scope_ref,
                                                constraint_id=c.constraint_id,
                                                detail=f"cannot redefine constraint declared by {owner[c.constraint_id]}"))
                continue
            if c.constraint_id not in constraints:
                constraints[c.constraint_id] = c
                owner[c.constraint_id] = layer.scope_ref
    ordered = tuple(sorted(constraints.values(), key=lambda c: c.constraint_id))
    return Resolution(values=dict(sorted(values.items())), sources=dict(sorted(sources.items())), constraints=ordered,
                      constraint_owner=dict(sorted(owner.items())), conflicts=tuple(conflicts),
                      findings=evaluate_constraints(values, ordered, owner), applied_scopes=tuple(applied),
                      preview_scope=previewed, authoritative=previewed is None)


class ValueChange(_Strict):
    key: str
    before: Value = None
    after: Value = None


class DocumentDiff(_Strict):
    added: tuple[ValueChange, ...]
    removed: tuple[ValueChange, ...]
    modified: tuple[ValueChange, ...]
    unchanged: tuple[str, ...]
    constraints_added: tuple[str, ...]
    constraints_removed: tuple[str, ...]
    constraints_modified: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.modified or self.constraints_added or self.constraints_removed
                    or self.constraints_modified)


def diff_documents(before: GenomeDocument, after: GenomeDocument) -> DocumentDiff:
    a, b = before.flatten(), after.flatten()
    ca = {c.constraint_id: c for c in before.constraints}
    cb = {c.constraint_id: c for c in after.constraints}
    return DocumentDiff(
        added=tuple(ValueChange(key=k, after=b[k]) for k in sorted(set(b) - set(a))),
        removed=tuple(ValueChange(key=k, before=a[k]) for k in sorted(set(a) - set(b))),
        modified=tuple(ValueChange(key=k, before=a[k], after=b[k]) for k in sorted(set(a) & set(b)) if a[k] != b[k]),
        unchanged=tuple(k for k in sorted(set(a) & set(b)) if a[k] == b[k]),
        constraints_added=tuple(sorted(set(cb) - set(ca))),
        constraints_removed=tuple(sorted(set(ca) - set(cb))),
        constraints_modified=tuple(sorted(k for k in set(ca) & set(cb) if ca[k] != cb[k])),
    )


def self_check(document: GenomeDocument) -> tuple[ConstraintFinding, ...]:
    """A document's own values against its own constraints (REQUIRED is checked only after resolution)."""
    values = document.flatten()
    return tuple(f for f in evaluate_constraints(values, [c for c in document.constraints if c.kind is not ConstraintKind.REQUIRED
                                                          and c.key in values]) if not f.passed)


def scope_ref_project(scope: Scope, scope_ref: str, *, brand_owner_project: str) -> str:
    """The project that authorizes a scope.

    A brand scope is authorized by the brand's owner project. Narrower scopes
    are paths rooted at a project: ``p1``, ``p1/page``, ``p1/page/component``,
    ``p1/page/component/asset`` (exactly one segment per scope level).
    """
    if scope is Scope.BRAND:
        return brand_owner_project
    parts = scope_ref.split("/")
    depth = SCOPE_ORDER.index(scope)
    if len(parts) != depth or not all(re.match(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$", part) for part in parts):
        raise ValueError(f"a {scope.value} scope_ref has {depth} '/'-separated segment(s), starting with the project id")
    return parts[0]


def ancestor_refs(scope: Scope, scope_ref: str, brand_id: str) -> list[tuple[Scope, str]]:
    """The scope chain for a target, outermost first: the brand, then each path prefix of ``scope_ref``."""
    chain: list[tuple[Scope, str]] = [(Scope.BRAND, brand_id)]
    if scope is Scope.BRAND:
        return chain
    parts = scope_ref.split("/")
    chain += [(SCOPE_ORDER[i], "/".join(parts[:i])) for i in range(1, SCOPE_ORDER.index(scope) + 1)]
    return chain


__all__ = [
    "CHROMOSOME_DOMAINS", "Chromosome", "ConflictReason", "ConstraintFinding", "ConstraintKind", "DocumentDiff",
    "EDITABLE_STATUSES", "FROZEN_STATUSES", "GENOME_SCHEMA", "GenomeConflict", "GenomeConstraint", "GenomeDocument",
    "GenomeLayer", "GenomeProvenance", "GenomeTransitionError", "ProvenanceKind", "Resolution", "SCOPE_ORDER", "Scope",
    "Severity", "TRANSITIONS", "ValueChange", "VersionStatus", "ancestor_refs", "diff_documents", "document_from_flat",
    "evaluate_constraints", "next_status", "resolve", "scope_ref_project", "self_check",
]
