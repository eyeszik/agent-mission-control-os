"""TriDiff: MissionIR / ArtifactIR / render semantic diff around a correction.

- D1 (mission): which hard-constraint verdicts changed. A constraint that held
  before the correction and fails after it is a ``REGRESSION`` (critical).
- D2 (artifact): which ArtifactIR fields changed. A change outside the
  correction's declared repair scopes is an ``UNINTENDED_CHANGE`` (major).
- D3 (render): tag-sequence edit distance and literal-colour changes. A render
  change that neither D2 nor a ``style`` scope explains is an
  ``UNEXPLAINED_RENDER_CHANGE`` (major).

``passed`` is true only when there are no critical or major findings.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from services.langgraph.agency.execution_fabric.verifiers import colors_in, dom_tag_edit_distance

from .critics import Feasibility
from .ir import ArtifactIR, Finding, MissionIR

# ArtifactIR path prefix -> repair scope that may change it.
_SCOPE_OF = {
    "landing_page.headline": "headline",
    "landing_page.subheadline": "subheadline",
    "landing_page.cta": "cta",
    "landing_page.sections": "structure",
    "hierarchy": "structure",
    "content_structure": "structure",
}
_IGNORED = {"hash", "version", "provenance", "artifact_id"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TriDiff(_Strict):
    d1_mission: tuple[dict, ...]
    d2_artifact: tuple[str, ...]
    d3_render: dict
    findings: tuple[Finding, ...]
    passed: bool


def _paths(a: Any, b: Any, prefix: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for key in sorted(set(a) | set(b)):
            if not prefix and key in _IGNORED:
                continue
            out += _paths(a.get(key), b.get(key), f"{prefix}.{key}" if prefix else key)
        return out
    return [] if a == b else [prefix]


def _scope(path: str) -> str:
    for prefix, scope in _SCOPE_OF.items():
        if path == prefix or path.startswith(prefix + "."):
            return scope
    return "other"


def _violated(feasibility: Feasibility) -> set[str]:
    return {f.evidence_ref.split(":", 1)[0] for f in feasibility.violations}


def tri_diff(mission: MissionIR, before: tuple[ArtifactIR, str, Feasibility], after: tuple[ArtifactIR, str, Feasibility],
             allowed_scopes: set[str] | frozenset[str]) -> TriDiff:
    (a_ir, a_html, a_feas), (b_ir, b_html, b_feas) = before, after
    findings: list[Finding] = []

    before_bad, after_bad = _violated(a_feas), _violated(b_feas)
    d1 = []
    for c in mission.all_constraints():
        was, now = c.constraint_id not in before_bad, c.constraint_id not in after_bad
        if was != now:
            d1.append({"constraint_id": c.constraint_id, "before": "held" if was else "violated", "after": "held" if now else "violated"})
            if was and not now:
                findings.append(Finding(code="REGRESSION", severity="critical", confidence=1.0, evidence_ref=c.constraint_id))
    if a_feas.verdict != "INFEASIBLE" and b_feas.verdict == "INFEASIBLE":
        findings.append(Finding(code="REGRESSION", severity="critical", confidence=1.0, evidence_ref="feasibility"))

    d2 = _paths(a_ir.model_dump(mode="json"), b_ir.model_dump(mode="json"))
    for path in d2:
        if _scope(path) not in allowed_scopes:
            findings.append(Finding(code="UNINTENDED_CHANGE", severity="major", confidence=1.0, evidence_ref=path))

    edit = dom_tag_edit_distance(a_html, b_html)
    added = sorted(set(colors_in(b_html)) - set(colors_in(a_html)))
    removed = sorted(set(colors_in(a_html)) - set(colors_in(b_html)))
    d3 = {"tag_edit_distance": edit, "colours_added": added, "colours_removed": removed,
          "render_changed": a_html != b_html}
    explained = bool(d2) or "style" in allowed_scopes
    if a_html != b_html and not explained:
        findings.append(Finding(code="UNEXPLAINED_RENDER_CHANGE", severity="major", confidence=0.9, evidence_ref="render"))
    if added:
        findings.append(Finding(code="NEW_LITERAL_COLOUR", severity="minor", confidence=1.0, evidence_ref=",".join(added)))

    passed = not any(f.severity in {"critical", "major"} for f in findings)
    return TriDiff(d1_mission=tuple(d1), d2_artifact=tuple(d2), d3_render=d3, findings=tuple(findings), passed=passed)


__all__ = ["TriDiff", "tri_diff"]
