"""IMAGE_INTENT + SCENE_COMPILATION for the editorial vertical slice. Deterministic.

Inputs: ``IntentIR`` (from the PromptIR brief), ``BrandIR`` (approved/brand palette
projection), a selected ``StyleProfile`` and the ``ReferenceManifest``. Output: a
``SceneIR`` with a background, headline, geometric identity motif, gradient material
object, lighting layer and technical annotation, every object tagged with the
requirements it serves, plus the constraints the evaluator checks independently.

Colour choice follows contrast, not taste: the ground is the brand ground unless the
accent cannot sit on it (< 3:1 for graphics), in which case the ink becomes the
ground. That is the PSEM rule ("accents only on Charcoal") derived, not hard-coded.
"""

from __future__ import annotations

from typing import Optional

from services.langgraph.agency.execution_fabric.verifiers import delta_e76
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from . import materials
from .contracts import (Appearance, CompilationSpec, Composition, DocumentSpec, Evidence, Geometry, IntentIR, PathCommand,
                        Provenance, ReferenceManifest, ReferenceRole, SceneConstraint, SceneIR, SceneObject, BrandIR)
from .profiles import StyleProfile

GLYPH_ADVANCE_EM = 0.62  # conservative mean advance for bold neo-grotesk caps; an estimate, labelled as such
TEXT_MIN, GRAPHIC_MIN = 4.5, 3.0

_KEYWORDS = (
    ("motif", ("motif", "geometric", "identity", "mark", "symbol", "ring")),
    ("material", ("material", "gradient", "object", "sphere", "surface", "ceramic", "metal", "glass")),
    ("lighting", ("light", "lighting", "highlight", "shadow", "glow")),
    ("annotation", ("annotation", "technical", "caption", "label", "figure", "note")),
    ("headline", ("headline", "title", "wordmark", "type", "typography")),
    ("background", ("background", "ground", "negative space", "backdrop")),
)


def estimated_text_width(text: str, font_size: float) -> float:
    return len(text) * font_size * GLYPH_ADVANCE_EM


def _ratio(a: str, b: str) -> float:
    return wcag_contrast_ratio(a, b)


def _choose_colours(brand: BrandIR, refs: ReferenceManifest) -> tuple[dict[str, str], tuple[Evidence, ...]]:
    pal, roles = brand.palette, brand.roles
    accent_key = roles.get("accent")
    evidence: list[Evidence] = []
    colour_refs = [r for r in refs.references if r.role == ReferenceRole.COLOR]
    candidates = [k for k in (roles.get("accent"), roles.get("accent_2")) if k]
    if colour_refs and len(candidates) > 1:
        # Most saturated observed colour picks between brand-approved accents; it never adds a colour.
        def sat(h: str) -> float:
            rgb = [int(h[i:i + 2], 16) for i in (1, 3, 5)]
            return (max(rgb) - min(rgb)) / 255
        target = max((c for r in colour_refs for c, _ in r.observed_palette), key=sat)
        accent_key = min(candidates, key=lambda k: delta_e76(pal[k], target))
        evidence.append(Evidence(source=colour_refs[0].ref_id, observation=f"most saturated observed colour {target}",
                                 interpretation=f"selects brand accent {accent_key!r} (nearest by dE76); adds no colour",
                                 provenance=Provenance.INFERRED, confidence=0.6))
    ground, ink = pal[roles["ground"]], pal[roles["ink"]]
    accent = pal[accent_key] if accent_key else ink
    if _ratio(accent, ground) < GRAPHIC_MIN:
        evidence.append(Evidence(source=f"brand:{brand.source}",
                                 observation=f"accent {accent} on ground {ground} is {_ratio(accent, ground):.2f}:1",
                                 interpretation="below 3:1 for graphics: ink becomes the ground", provenance=Provenance.INFERRED,
                                 confidence=1.0))
        ground, ink = ink, pal[roles["ground"]]
        ground_key, ink_key = roles["ink"], roles["ground"]
    else:
        ground_key, ink_key = roles["ground"], roles["ink"]
    muted_key = roles.get("muted", ink_key)
    muted = pal[muted_key] if _ratio(pal[muted_key], ground) >= TEXT_MIN else ink
    secondary_key = roles.get("secondary", muted_key)
    return ({"ground": ground, "ink": ink, "accent": accent, "muted": muted, "secondary": pal[secondary_key],
             "ground_key": ground_key, "ink_key": ink_key, "accent_key": accent_key or ink_key,
             "secondary_key": secondary_key}, tuple(evidence))


def _requirement_targets(intent: IntentIR) -> dict[str, list[str]]:
    targets: dict[str, list[str]] = {}
    for item in intent.items:
        if item.kind != "hard_requirement" or item.classification.value != "VERIFIED":
            continue
        text = item.text.lower()
        for target, words in _KEYWORDS:
            if any(w in text for w in words):
                targets.setdefault(target, []).append(item.item_id)
                break
    return targets


def _motif(profile: StyleProfile, c: dict[str, str], W: int, H: int, m: float, refs: tuple[str, ...]) -> list[SceneObject]:
    sw = max(1.5, W * 0.006)
    obj = []
    if profile.motif == "rings":
        cx, cy, r = W * 0.66, H * 0.42, min(W, H) * 0.24
        obj += [SceneObject(object_id="motif-ring-outer", semantic_role="motif", geometry=Geometry(primitive="circle",
                            params={"cx": cx, "cy": cy, "r": r}), appearance=Appearance(fill="none", stroke=c["accent"],
                            stroke_width=sw), protected=True, requirement_refs=refs),
                SceneObject(object_id="motif-ring-inner", semantic_role="motif", geometry=Geometry(primitive="circle",
                            params={"cx": cx, "cy": cy, "r": r * 0.6}), appearance=Appearance(fill="none", stroke=c["ink"],
                            stroke_width=sw * 0.5), protected=True, requirement_refs=refs),
                SceneObject(object_id="motif-axis", semantic_role="motif", geometry=Geometry(primitive="path", path=(
                            PathCommand(op="M", coords=(m, cy)), PathCommand(op="L", coords=(W - m, cy)))),
                            appearance=Appearance(fill="none", stroke=c["ink"], stroke_width=sw * 0.35), protected=True,
                            requirement_refs=refs)]
    elif profile.motif == "bars":
        col = (W - 2 * m) / profile.grid_columns
        for i, frac in enumerate((0.55, 0.8, 0.35)):
            x = m + col * (profile.grid_columns - 4 + i)
            obj.append(SceneObject(object_id=f"motif-bar-{i}", semantic_role="motif", geometry=Geometry(primitive="rect",
                       params={"x": x, "y": H * 0.62 - H * 0.4 * frac, "width": col * 0.7, "height": H * 0.4 * frac}),
                       appearance=Appearance(fill=c["accent"] if i == 1 else c["ink"]), protected=True, requirement_refs=refs))
    elif profile.motif == "modules":
        size = (W - 2 * m) / profile.grid_columns
        for i in range(3):
            obj.append(SceneObject(object_id=f"motif-module-{i}", semantic_role="motif", geometry=Geometry(primitive="rect",
                       params={"x": W - m - size * (i + 1) * 1.1, "y": H * 0.3, "width": size, "height": size}),
                       appearance=Appearance(fill=c["accent"] if i == 0 else "none", stroke=c["ink"], stroke_width=sw * 0.5),
                       protected=True, requirement_refs=refs))
    else:  # axis
        y = H * 0.55
        obj.append(SceneObject(object_id="motif-axis", semantic_role="motif", geometry=Geometry(primitive="path", path=(
                   PathCommand(op="M", coords=(m, y)), PathCommand(op="L", coords=(W - m, y)))),
                   appearance=Appearance(fill="none", stroke=c["accent"], stroke_width=sw * 0.5), protected=True,
                   requirement_refs=refs))
        for i in range(9):
            x = m + i * (W - 2 * m) / 8
            obj.append(SceneObject(object_id=f"motif-tick-{i}", semantic_role="motif", geometry=Geometry(primitive="path",
                       path=(PathCommand(op="M", coords=(x, y - H * 0.012)), PathCommand(op="L", coords=(x, y + H * 0.012)))),
                       appearance=Appearance(fill="none", stroke=c["ink"], stroke_width=sw * 0.35), protected=True,
                       requirement_refs=refs))
    return obj


def compile_scene(intent: IntentIR, brand: BrandIR, profile: StyleProfile, refs: ReferenceManifest, *, seed: int = 0,
                  material: Optional[materials.MaterialSpec] = None, reference_evidence: tuple[Evidence, ...] = (),
                  annotation: Optional[str] = None) -> SceneIR:
    if not intent.exact_text:
        raise ValueError("the editorial slice needs a headline in exact_text")
    W, H = intent.width, intent.height
    m = round(min(W, H) * profile.margin, 2)
    c, colour_evidence = _choose_colours(brand, refs)
    targets = _requirement_targets(intent)
    text_ids = intent.exact_text_ids()
    headline_text = intent.exact_text[0]
    annotation_text = intent.exact_text[1] if len(intent.exact_text) > 1 else (annotation or f"FIG. 01 / {intent.asset_id.upper()}")
    annotation_exact = len(intent.exact_text) > 1
    # Fit the headline on one line inside the margins (estimate), never rewriting it.
    fs = min(W * profile.headline_scale, (W - 2 * m) / max(1, len(headline_text) * GLYPH_ADVANCE_EM))
    fs = round(max(fs, 12.0), 2)
    head_refs = (text_ids[0], *targets.get("headline", ()))
    objects: list[SceneObject] = [
        SceneObject(object_id="background", semantic_role="background",
                    geometry=Geometry(primitive="rect", params={"x": 0, "y": 0, "width": W, "height": H}),
                    appearance=Appearance(fill=c["ground"]), requirement_refs=tuple(targets.get("background", ()))),
    ]
    if profile.grain:
        objects.append(SceneObject(object_id="grain", semantic_role="texture",
                                   geometry=Geometry(primitive="rect", params={"x": 0, "y": 0, "width": W, "height": H}),
                                   appearance=Appearance(fill=c["ink"], opacity=0.07, blur="grain"), dependencies=("background",)))
    motif = _motif(profile, c, W, H, m, tuple(targets.get("motif", ())))
    objects += motif
    mat = material or materials.material("mat-ceramic", "ceramic", surface=c["secondary_key"], light=c["ink_key"],
                                         shade=c["ground_key"], light_direction=135.0, texture_scale=0.0)
    grads, mat_objs = materials.shade_disc(mat, brand.palette, object_id="material-object", cx=W * 0.27, cy=H * 0.74,
                                           r=min(W, H) * 0.13, ground=c["ground"], requirement_refs=tuple(targets.get("material", ())))
    objects += list(mat_objs)
    light_refs = tuple(targets.get("lighting", ()))
    objects.append(SceneObject(object_id="lighting-key", semantic_role="lighting",
                               geometry=Geometry(primitive="ellipse", params={"cx": W * 0.2, "cy": H * 0.22, "rx": W * 0.3,
                                                                              "ry": H * 0.12}, rotate=-20),
                               appearance=Appearance(fill=c["ink"], opacity=0.06, blur="soft"), requirement_refs=light_refs))
    objects.append(SceneObject(object_id="headline", semantic_role="headline",
                               geometry=Geometry(primitive="text", params={"x": m, "y": m + fs}),
                               appearance=Appearance(fill=c["ink"], font_size=fs, font_weight=profile.headline_weight,  # type: ignore[arg-type]
                                                     letter_spacing=round(-0.02 * fs, 2)),
                               text=headline_text, requirement_refs=head_refs, protected=True))
    afs = round(max(10.0, W * 0.014), 2)
    ann_refs = ((text_ids[1],) if annotation_exact else ()) + tuple(targets.get("annotation", ()))
    objects += [
        SceneObject(object_id="annotation-rule", semantic_role="rule",
                    geometry=Geometry(primitive="path", path=(PathCommand(op="M", coords=(m, H - m - afs * 2.2)),
                                                              PathCommand(op="L", coords=(m + W * 0.22, H - m - afs * 2.2)))),
                    appearance=Appearance(fill="none", stroke=c["muted"], stroke_width=1), requirement_refs=ann_refs),
        SceneObject(object_id="annotation", semantic_role="annotation",
                    geometry=Geometry(primitive="text", params={"x": m, "y": H - m}),
                    appearance=Appearance(fill=c["muted"], font_size=afs, font_weight=400, letter_spacing=round(afs * 0.08, 2)),
                    text=annotation_text, requirement_refs=ann_refs, protected=annotation_exact),
    ]
    constraints = [
        SceneConstraint(constraint_id="exact.headline", kind="exact_text", target=("headline",), verification="SVG text == brief",
                        requirement_refs=(text_ids[0],)),
        SceneConstraint(constraint_id="protected.motif", kind="protected_geometry", target=tuple(o.object_id for o in motif),
                        verification="geometry attributes unchanged by any edit or repair"),
        SceneConstraint(constraint_id="palette", kind="palette", target=(), tolerance=2.3,
                        verification="every literal colour within dE76 2.3 of the brand palette"),
        SceneConstraint(constraint_id="contrast.headline", kind="contrast", target=("headline", "background"), tolerance=TEXT_MIN,
                        verification="WCAG 2.2 ratio of headline fill on ground"),
        SceneConstraint(constraint_id="contrast.annotation", kind="contrast", target=("annotation", "background"),
                        tolerance=TEXT_MIN, verification="WCAG 2.2 ratio of annotation fill on ground"),
        SceneConstraint(constraint_id="contrast.motif", kind="contrast", target=(motif[0].object_id, "background"),
                        tolerance=GRAPHIC_MIN, verification="WCAG 2.2 graphic contrast of the accent motif on ground"),
        SceneConstraint(constraint_id="accent.single", kind="single_accent", target=(), tolerance=brand.max_signal_accents,
                        verification="at most N accent colours used"),
        SceneConstraint(constraint_id="profile", kind="profile", target=(), verification="no raster in a native profile"),
    ]
    if annotation_exact:
        constraints.insert(1, SceneConstraint(constraint_id="exact.annotation", kind="exact_text", target=("annotation",),
                                              verification="SVG text == brief", requirement_refs=(text_ids[1],)))
    evidence = (*reference_evidence, *colour_evidence,
                Evidence(source=f"profile:{profile.profile_id}", observation="; ".join(profile.notes) or profile.name,
                         interpretation="layout and motif chosen by the selected profile", provenance=Provenance.ARTIST_DEFINED,
                         confidence=1.0),
                Evidence(source="compiler", observation=f"headline {len(headline_text)} chars at {fs}px",
                         interpretation=f"estimated width {estimated_text_width(headline_text, fs):.0f}px "
                                        f"(advance {GLYPH_ADVANCE_EM}em, an estimate)", provenance=Provenance.APPROXIMATED,
                         confidence=0.7))
    return SceneIR(document=DocumentSpec(width=W, height=H, output_profile=intent.output_profile,
                                         title=headline_text[:120], source_digest=intent.intent_hash),
                   gradients=grads, objects=tuple(objects),
                   composition=Composition(grid_columns=profile.grid_columns, margin=m, focal_object=motif[0].object_id,
                                           negative_space_target=profile.negative_space, style_profile=profile.profile_id),
                   constraints=tuple(constraints), evidence=evidence,
                   compilation=CompilationSpec(seed=seed, brand_hash=brand.digest(), reference_manifest_hash=refs.digest()))


def requirement_coverage(intent: IntentIR, scene: SceneIR) -> dict:
    """Every VERIFIED hard requirement and exact text maps to at least one scene object, or is reported uncovered."""
    served: dict[str, list[str]] = {}
    for o in scene.objects:
        for ref in o.requirement_refs:
            served.setdefault(ref, []).append(o.object_id)
    needed = [i for i in intent.items if i.classification.value == "VERIFIED" and i.kind in {"hard_requirement", "exact_text"}]
    rows = [{"requirement": i.item_id, "text": i.text, "objects": served.get(i.item_id, []),
             "status": "MAPPED" if served.get(i.item_id) else "UNMAPPED"} for i in needed]
    return {"rows": rows, "coverage": (sum(r["status"] == "MAPPED" for r in rows) / len(rows)) if rows else 1.0,
            "unmapped": [r["requirement"] for r in rows if r["status"] == "UNMAPPED"]}


__all__ = ["GLYPH_ADVANCE_EM", "compile_scene", "estimated_text_width", "requirement_coverage"]
