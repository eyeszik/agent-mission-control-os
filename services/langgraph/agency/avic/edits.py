"""Editing operations on a ``SceneIR``: inspect, recolor, change_text, set_geometry.

An edit returns a new scene plus ``TransformationRecord``s; the parent is never
mutated. Edits are refused (``EditRejected``) before anything is produced when they
would change exact text bound to the brief, move protected geometry, introduce a
colour outside the brand palette, or touch an object that does not exist. Whether
the result is acceptable (contrast, accent budget) is decided afterwards by the
independent evaluator, not by the edit.
"""

from __future__ import annotations

import re
from typing import Any

from .contracts import BrandIR, IntentIR, SceneIR, SceneObject, TransformationRecord


class EditRejected(ValueError):
    pass


def inspect(scene: SceneIR) -> list[dict[str, Any]]:
    return [{"object_id": o.object_id, "role": o.semantic_role, "primitive": o.geometry.primitive, "fill": o.appearance.fill,
             "stroke": o.appearance.stroke, "text": o.text, "protected": o.protected, "requirements": list(o.requirement_refs)}
            for o in scene.objects]


def _replace(scene: SceneIR, new: SceneObject) -> SceneIR:
    return scene.model_copy(update={"objects": tuple(new if o.object_id == new.object_id else o for o in scene.objects)})


def _get(scene: SceneIR, object_id: str) -> SceneObject:
    try:
        return scene.object(object_id)
    except KeyError:
        raise EditRejected(f"no object {object_id!r}") from None


def recolor(scene: SceneIR, brand: BrandIR, object_id: str, palette_key: str, *, field: str = "fill"
            ) -> tuple[SceneIR, tuple[TransformationRecord, ...]]:
    o = _get(scene, object_id)
    if field not in {"fill", "stroke"}:
        raise EditRejected("only fill or stroke can be recoloured")
    if palette_key not in brand.palette:
        raise EditRejected(f"{palette_key!r} is not a brand palette colour; edits cannot widen the palette")
    before = getattr(o.appearance, field)
    if before is None or before == "none" or before.startswith("url("):
        raise EditRejected(f"{object_id}.{field} is {before!r}; only solid paints can be recoloured")
    after = brand.palette[palette_key]
    new = o.model_copy(update={"appearance": o.appearance.model_copy(update={field: after})})
    return SceneIR.model_validate(_replace(scene, new).model_dump()), (TransformationRecord(object_id=object_id, field=field,
                                                                                            before=before, after=after),)


def change_text(scene: SceneIR, intent: IntentIR, object_id: str, text: str) -> tuple[SceneIR, tuple[TransformationRecord, ...]]:
    o = _get(scene, object_id)
    if o.geometry.primitive != "text":
        raise EditRejected(f"{object_id} is not text")
    bound = set(o.requirement_refs) & set(intent.exact_text_ids())
    if bound:
        raise EditRejected(f"{object_id} carries exact text {sorted(bound)} from the brief; change the brief, not the artwork")
    if not text or len(text) > 300 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        raise EditRejected("text must be 1..300 printable characters")
    new = o.model_copy(update={"text": text})
    return SceneIR.model_validate(_replace(scene, new).model_dump()), (TransformationRecord(object_id=object_id, field="text",
                                                                                            before=o.text, after=text),)


def set_geometry(scene: SceneIR, object_id: str, params: dict[str, float]) -> tuple[SceneIR, tuple[TransformationRecord, ...]]:
    o = _get(scene, object_id)
    if o.protected:
        raise EditRejected(f"{object_id} is protected geometry")
    unknown = set(params) - set(o.geometry.params)
    if unknown:
        raise EditRejected(f"{object_id} has no geometry parameters {sorted(unknown)}")
    merged = {**o.geometry.params, **params}
    new = o.model_copy(update={"geometry": o.geometry.model_copy(update={"params": merged})})
    records = tuple(TransformationRecord(object_id=object_id, field=f"geometry.{k}", before=o.geometry.params[k], after=v)
                    for k, v in sorted(params.items()))
    return SceneIR.model_validate(_replace(scene, new).model_dump()), records


__all__ = ["EditRejected", "change_text", "inspect", "recolor", "set_geometry"]
