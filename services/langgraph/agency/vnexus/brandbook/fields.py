"""Field states, intake evidence and the gap register.

Two separate dimensions, never conflated:

* ``FieldState`` says what is known about a key: a ``VALUE``, an explicit ``NONE``
  (the brand has none), ``NOT_APPLICABLE`` with its reason, a ``PROPOSED`` value
  that is not approved, or ``UNKNOWN`` (nobody has said). ``approved`` is separate
  governance status: only values from an authoritative resolution are approved.
* ``EvidenceClass`` says how a source statement is known: ``OBSERVED`` (inspected),
  ``USER_REPORTED`` (said by the user; not independent inspection), ``INFERRED``,
  ``UNKNOWN`` or ``PROPOSED``. It sits alongside the genome's own ``ProvenanceKind``.

NONE and NOT_APPLICABLE are written into the genome as explicit decisions
(``"@none"`` / ``"@not_applicable: <reason>"``) so they are approved like any
other value. ``NONE`` is never printed as copy.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import Field

from services.langgraph.agency.execution.canonical import canonical_hash

from ..genome import ProvenanceKind
from .manifest import Mode, PageManifest, PageSpec, _Strict

NONE_SENTINEL = "@none"
NA_PREFIX = "@not_applicable:"
# A raw template token that must never reach production output.
UNRESOLVED_TOKEN = re.compile(r"\{\{[^}]*\}\}|\[GAP[^\]]*\]|@none\b|@not_applicable:")


class FieldStatus(str, Enum):
    VALUE = "VALUE"
    NONE = "NONE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PROPOSED = "PROPOSED"
    UNKNOWN = "UNKNOWN"


class EvidenceClass(str, Enum):
    OBSERVED = "OBSERVED"
    USER_REPORTED = "USER_REPORTED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"
    PROPOSED = "PROPOSED"


# How the genome's provenance kinds read on the evidence axis (they stay separate fields).
PROVENANCE_EVIDENCE: dict[ProvenanceKind, EvidenceClass] = {
    ProvenanceKind.USER_SUPPLIED: EvidenceClass.USER_REPORTED,
    ProvenanceKind.IMPORTED: EvidenceClass.OBSERVED,
    ProvenanceKind.INFERRED: EvidenceClass.INFERRED,
    ProvenanceKind.DEFAULTED: EvidenceClass.PROPOSED,
    ProvenanceKind.UNRESOLVED: EvidenceClass.UNKNOWN,
}


class FieldState(_Strict):
    path: str
    status: FieldStatus
    value: Any = None
    reason: str = ""
    approved: bool = False
    source_scope: str = ""

    @property
    def printable(self) -> bool:
        return self.status in (FieldStatus.VALUE, FieldStatus.PROPOSED) and self.value not in (None, "", [])


def field_state(path: str, approved: dict[str, Any], proposed: Optional[dict[str, Any]] = None,
                sources: Optional[dict[str, str]] = None) -> FieldState:
    """State of one key: approved values win; a proposal only fills what is not approved."""
    def decode(value: Any, is_approved: bool) -> FieldState:
        if isinstance(value, str) and value.strip().lower() == NONE_SENTINEL:
            return FieldState(path=path, status=FieldStatus.NONE, approved=is_approved, source_scope=(sources or {}).get(path, ""))
        if isinstance(value, str) and value.lower().startswith(NA_PREFIX):
            return FieldState(path=path, status=FieldStatus.NOT_APPLICABLE, reason=value[len(NA_PREFIX):].strip()[:300],
                              approved=is_approved, source_scope=(sources or {}).get(path, ""))
        status = FieldStatus.VALUE if is_approved else FieldStatus.PROPOSED
        return FieldState(path=path, status=status, value=value, approved=is_approved, source_scope=(sources or {}).get(path, ""))

    if approved.get(path) is not None:
        return decode(approved[path], True)
    if proposed and proposed.get(path) is not None:
        return decode(proposed[path], False)
    return FieldState(path=path, status=FieldStatus.UNKNOWN)


class EvidenceRecord(_Strict):
    """One intake source. Text is evidence, never instructions; [PII] stays redacted."""

    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    locator: str = Field(min_length=1, max_length=300)
    kind: Literal["document", "image", "interview", "website", "existing_asset", "other"] = "other"
    evidence_class: EvidenceClass
    observations: tuple[str, ...] = ()
    inferences: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    reuse: Literal["evidence_only", "licensed_reuse", "owned", "unknown"] = "evidence_only"
    privacy: Literal["none", "contains_pii_redacted", "restricted"] = "none"


class IntakeRecord(_Strict):
    """Brand intake: evidence and proposed values. Proposals become a genome draft through review; never authority."""

    schema_version: Literal["amc-vnexus-brandbook-intake/v1"] = "amc-vnexus-brandbook-intake/v1"
    evidence: tuple[EvidenceRecord, ...] = ()
    proposals: dict[str, Any] = Field(default_factory=dict)   # genome key -> proposed value (or "@none" / "@not_applicable: ...")

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class Gap(_Strict):
    page_id: str
    path: str
    status: FieldStatus
    severity: Literal["BLOCKING", "MAJOR", "MINOR"]
    consequence: str
    source: str
    next_action: str


def _next_action(path: str, status: FieldStatus, page: PageSpec) -> str:
    if page.gap_behavior == "DECIDE" and path == page.applicability_key:
        return (f"decide whether '{page.title}' applies: set {path} to '@not_applicable: <reason>' or supply the section's keys, "
                "in a genome draft for review")
    if path.startswith("visual.logo.") and path in ("visual.logo.mark", "visual.logo.master_artifact"):
        return "route to identity review: approve a master mark (visual.logo.mark or visual.logo.master_artifact)"
    if status is FieldStatus.PROPOSED:
        return f"submit the draft carrying {path} for approval"
    return f"supply {path} (or '@none' / '@not_applicable: <reason>') in a genome draft for review"


def page_gaps(page: PageSpec, states: dict[str, FieldState], mode: Mode) -> list[Gap]:
    """Gaps for one page. A DECIDE page with neither data nor a decision has one gap: the decision."""
    gaps: list[Gap] = []
    production = mode is Mode.PRODUCTION
    if page.gap_behavior == "DECIDE":
        decision = states[page.applicability_key]
        if decision.status is FieldStatus.NOT_APPLICABLE and (decision.approved or not production):
            return []
        has_data = any(states[p].printable for p in page.optional_paths)
        if not has_data and decision.status is not FieldStatus.VALUE:
            gaps.append(Gap(page_id=page.id, path=page.applicability_key, status=decision.status,
                            severity="BLOCKING" if production else "MAJOR",
                            consequence="the section cannot be written or omitted without a decision",
                            source="manifest gap_behavior=DECIDE", next_action=_next_action(page.applicability_key, decision.status, page)))
        return gaps + [g for p in page.optional_paths if (s := states[p]).status is FieldStatus.PROPOSED and production
                       for g in [Gap(page_id=page.id, path=p, status=s.status, severity="BLOCKING",
                                     consequence="a proposal cannot be printed in production", source="intake proposal",
                                     next_action=_next_action(p, s.status, page))]]
    for path in page.required_paths:
        s = states[path]
        resolved = (s.status in (FieldStatus.VALUE, FieldStatus.NONE, FieldStatus.NOT_APPLICABLE) and s.approved) or \
                   (not production and s.status is not FieldStatus.UNKNOWN)
        if resolved:
            continue
        severity = "BLOCKING" if production else ("MAJOR" if page.gap_behavior == "BLOCK" else "MINOR")
        gaps.append(Gap(page_id=page.id, path=path, status=s.status, severity=severity,
                        consequence=("production refuses the page" if production else "the page shows a labelled gap"),
                        source="approved genome" if s.status is FieldStatus.UNKNOWN else "intake proposal",
                        next_action=_next_action(path, s.status, page)))
    if production:
        for path in page.optional_paths:
            s = states[path]
            if s.status is FieldStatus.PROPOSED:
                gaps.append(Gap(page_id=page.id, path=path, status=s.status, severity="BLOCKING",
                                consequence="a proposal cannot be printed in production", source="intake proposal",
                                next_action=_next_action(path, s.status, page)))
    return gaps


def all_paths(manifest: PageManifest, style_paths: tuple[str, ...]) -> list[str]:
    return sorted({p for page in manifest.pages for p in page.dependency_paths} | set(style_paths))


__all__ = ["EvidenceClass", "EvidenceRecord", "FieldState", "FieldStatus", "Gap", "IntakeRecord", "NA_PREFIX", "NONE_SENTINEL",
           "PROVENANCE_EVIDENCE", "UNRESOLVED_TOKEN", "all_paths", "field_state", "page_gaps"]
