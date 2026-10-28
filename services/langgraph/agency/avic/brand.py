"""H2 governed brand mutations and H4 reproducible visual branches.

H2: a brand change is a ``MutationRecord`` with owner, reason, scope, approval and a
rollback reference. Protected invariants (the palette itself, the accent rules) are
never mutable here; allowed dimensions change only with an approval reference, and
the result is a new ``BrandIR`` with a new hash: nothing edits brand state in place.

H4: a ``VariantBranch`` is a reproducible exploration from a parent scene over
declared mutation axes, with the parent's immutable constraints carried unchanged.
Variants move PROPOSED -> RENDERED -> EVALUATED -> SELECTED (Pareto ranking).
APPROVED only ever comes from ``/approvals/{id}/decide`` on the variant's own bytes:
no branch inherits approval, and the branch record has nowhere to put one.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from pydantic import Field

from services.langgraph.agency.execution.canonical import canonical_hash

from . import materials, svg
from .contracts import BrandIR, CandidateStatus, Hash, IntentIR, ReferenceManifest, SceneIR, Strict
from .evaluate import evaluate
from .optimize import pareto
from .profiles import StyleProfile
from .scene import compile_scene

MAX_VARIANTS = 4
AXES = ("motif", "headline_scale", "material", "accent_choice")
_MOTIFS = ("rings", "bars", "modules", "axis")
_MATERIALS = ("ceramic", "metallic", "glossy", "matte")


class BrandMutationRejected(ValueError):
    pass


class MutationRecord(Strict):
    mutation_id: str = Field(pattern=r"^mut-[a-f0-9]{12}$")
    owner: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=300)
    scope: str
    change: dict[str, Any]
    constraints: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    affected_artifacts: tuple[str, ...] = ()
    approval: str = Field(min_length=1)
    rollback: Hash                          # parent BrandIR hash


def mutate_brand(brand: BrandIR, *, scope: Literal["accent_choice", "typography"], change: dict[str, Any], owner: str,
                 reason: str, approval_ref: Optional[str], affected_artifacts: tuple[str, ...] = ()
                 ) -> tuple[BrandIR, MutationRecord]:
    if not approval_ref:
        raise BrandMutationRejected("a brand mutation needs an approval reference")
    if scope in brand.protected_invariants or "palette" in change:
        raise BrandMutationRejected(f"{scope} is a protected brand invariant")
    if scope == "accent_choice":
        key = change.get("accent")
        allowed = {brand.roles.get("accent"), brand.roles.get("accent_2")} - {None}
        if key not in allowed:
            raise BrandMutationRejected(f"accent must be one of the brand's accents {sorted(allowed)}; mutations never add colour")
        roles = {**brand.roles, "accent": key, "accent_2": brand.roles["accent"]} if key != brand.roles["accent"] else brand.roles
        new = brand.model_copy(update={"roles": roles})
    else:
        fams = tuple(change.get("typography") or ())
        if not fams or len(fams) > 4:
            raise BrandMutationRejected("typography must name 1..4 families")
        new = brand.model_copy(update={"typography": fams})
    new = BrandIR.model_validate(new.model_dump())
    rec = MutationRecord(mutation_id="mut-" + canonical_hash({"p": brand.digest(), "c": change, "s": scope})[:12], owner=owner,
                         reason=reason, scope=scope, change=change, constraints=brand.protected_invariants,
                         affected_artifacts=affected_artifacts, approval=approval_ref, rollback=brand.digest())
    return new, rec


class VariantBranch(Strict):
    branch_id: str = Field(pattern=r"^br-[a-f0-9]{12}$")
    parent_version: Hash                    # parent scene hash
    immutable_constraints: tuple[str, ...]
    mutation_axes: dict[str, Any]
    input_hash: Hash
    renderer_version: Optional[str]
    scene_hash: Hash
    svg_sha256: Hash
    evaluation_refs: tuple[str, ...]
    status: CandidateStatus
    metrics: dict[str, Any] = Field(default_factory=dict)


Renderer = Callable[[str, int, int, Path], dict]


def explore(parent: SceneIR, *, intent: IntentIR, brand: BrandIR, profile: StyleProfile, refs: ReferenceManifest,
            axes: tuple[str, ...], n: int, seed: int, render: Renderer, work_dir: Path, renderer: str,
            renderer_version: Optional[str]) -> list[tuple[VariantBranch, str, Optional[bytes]]]:
    """Deterministic variants over ``axes`` (seeded), each rendered and evaluated; SELECTED = Pareto front.

    Returns ``(branch, svg, png)``. Axes that touch brand roles need the brand to allow that variation.
    """
    unknown = set(axes) - set(AXES)
    if unknown:
        raise ValueError(f"unknown mutation axes {sorted(unknown)}")
    if "accent_choice" in axes and "accent_choice" not in brand.allowed_variations:
        raise BrandMutationRejected("this brand does not allow accent variation; use a governed mutation first")
    n = max(1, min(n, MAX_VARIANTS))
    immutable = tuple(c.constraint_id for c in parent.constraints)
    branches: list[VariantBranch] = []
    outputs: dict[str, tuple[str, Optional[bytes]]] = {}
    seen = {hashlib.sha256(svg.emit(parent).encode()).hexdigest()}  # identical output == no variant
    for i in range(n * 3):  # bounded: at most 3n draws to find n variants that differ from the parent and each other
        if len(branches) >= n:
            break
        k = seed + i + 1
        change: dict[str, Any] = {}
        prof, mat, b = profile, None, brand
        if "motif" in axes:
            change["motif"] = _MOTIFS[k % len(_MOTIFS)]
            prof = dataclasses.replace(prof, motif=change["motif"])
        if "headline_scale" in axes:
            change["headline_scale"] = round(profile.headline_scale * (0.8 + 0.1 * (k % 4)), 4)
            prof = dataclasses.replace(prof, headline_scale=change["headline_scale"])
        if "material" in axes:
            fam = _MATERIALS[k % len(_MATERIALS)]
            change["material"] = fam
        if "accent_choice" in axes and brand.roles.get("accent_2"):
            key = brand.roles["accent"] if k % 2 else brand.roles["accent_2"]
            change["accent"] = key
            b = brand.model_copy(update={"roles": {**brand.roles, "accent": key,
                                                   "accent_2": brand.roles["accent"] if key != brand.roles["accent"]
                                                   else brand.roles["accent_2"]}})
        draft = compile_scene(intent, b, prof, refs, seed=parent.compilation.seed)
        if "material" in axes:
            c_ground = draft.object("background").appearance.fill
            inv = {v: key for key, v in brand.palette.items()}
            mat = materials.material(f"mat-{change['material']}", change["material"], surface=brand.roles.get("secondary", brand.roles["ink"]),
                                     light=inv.get(draft.object("headline").appearance.fill, brand.roles["ink"]),
                                     shade=inv.get(c_ground, brand.roles["ground"]), light_direction=135.0)
            draft = compile_scene(intent, b, prof, refs, seed=parent.compilation.seed, material=mat)
        text = svg.emit(draft)
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        bid = "br-" + hashlib.sha256(f"{parent.scene_hash}|{sorted(change.items())}".encode()).hexdigest()[:12]
        r = render(text, draft.document.width, draft.document.height, work_dir / bid)
        report = evaluate(draft, text, intent=intent, brand=brand, png_bytes=r.get("png"), renderer=renderer,
                          renderer_version=renderer_version)
        status = CandidateStatus.EVALUATED if report.passed else CandidateStatus.REJECTED
        branches.append(VariantBranch(branch_id=bid, parent_version=parent.scene_hash, immutable_constraints=immutable,
                                      mutation_axes=change, input_hash=canonical_hash({"parent": parent.scene_hash, "change": change,
                                                                                       "seed": k}),
                                      renderer_version=renderer_version, scene_hash=draft.scene_hash,
                                      svg_sha256=report.svg_sha256, evaluation_refs=(report.digest(),), status=status,
                                      metrics={"failures": len(report.failures()), "svg_bytes": len(text.encode()),
                                               **{k2: v for k2, v in report.metrics.items() if k2 == "luminance_std"}}))
        outputs[bid] = (text, r.get("png"))
    evaluated = [b for b in branches if b.status == CandidateStatus.EVALUATED]
    if evaluated:
        rows = [{"id": b.branch_id, "bytes": b.metrics["svg_bytes"], "flatness": -b.metrics.get("luminance_std", 0)} for b in evaluated]
        front = {r["id"] for r in pareto(rows, ("bytes", "flatness"))}
        branches = [b.model_copy(update={"status": CandidateStatus.SELECTED}) if b.branch_id in front else b for b in branches]
    return [(b, *outputs[b.branch_id]) for b in branches]


__all__ = ["AXES", "MAX_VARIANTS", "BrandMutationRejected", "MutationRecord", "VariantBranch", "explore", "mutate_brand"]
