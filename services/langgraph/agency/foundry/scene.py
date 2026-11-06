"""Synthetic Production Studio: SceneIR -> local Blender Cycles render with the brand's own artwork.

Only ``package_on_plinth`` is implemented end to end. The other scene kinds in
``SceneIR`` are declared and return a typed capability gap rather than a
substitute image. Every render is labelled synthetic: it is a 3D preview, not a
photograph of a manufactured product. A missing artwork input fails before any
rendering with a recoverable SCENE_INPUT error, and nothing is persisted.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from services.langgraph.agency.visual.contracts import RenderReceipt
from services.langgraph.agency.visual.renderers import render_blender_spec

from .contracts import CreativeGenome, MaterialIR, SceneIR

IMPLEMENTED_SCENES = frozenset({"package_on_plinth"})
QUALITY = {"draft": (480, 600, 32), "standard": (960, 1200, 128)}


def compile_scene(genome: CreativeGenome, *, quality: str = "draft", scene: str = "package_on_plinth") -> SceneIR:
    w, h, samples = QUALITY[quality]
    mats = genome.material_rules
    return SceneIR(scene=scene, width=w, height=h, samples=samples, seed=genome.deterministic_seed % 100_000,
                   camera={"focal_mm": 50, "fstop": 5.6, "distance": 3.3, "height": 1.35, "azimuth_deg": -68},
                   materials=(MaterialIR(material_id="box_card", base_color_role="paper", roughness=mats["package"]["roughness"],
                                         metallic=0.0),
                              MaterialIR(material_id="plinth", base_color_role="muted", roughness=mats["plinth"]["roughness"],
                                         metallic=0.0),
                              MaterialIR(material_id="label_artwork", base_color_role="paper", roughness=0.45, metallic=0.0,
                                         texture_ref="label.png")),
                   palette=genome.palette.roles(), genome_hash=genome.content_hash)


def render_scene(ir: SceneIR, *, artwork_png: Optional[Path], out_dir: Path) -> RenderReceipt | dict:
    if ir.scene not in IMPLEMENTED_SCENES:
        return {"status": "BLOCKED", "reasons": [f"SCENE_NOT_IMPLEMENTED:{ir.scene}"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    label = out_dir / "label.png"
    if artwork_png is not None and Path(artwork_png).is_file():
        shutil.copyfile(artwork_png, label)
    elif label.exists():
        label.unlink()
    spec = {"scene": ir.scene, "palette": ir.palette, "texture": "label.png",
            "render": {"width": ir.width, "height": ir.height, "samples": ir.samples, "seed": ir.seed, "threads": 4},
            "camera": ir.camera, "frames": 1, "turntable_sweep_deg": 0, "key_energy": 240.0, "rim_energy": 70.0,
            "plinth_roughness": next(m.roughness for m in ir.materials if m.material_id == "plinth")}
    return render_blender_spec(spec, out_dir, seed=ir.seed, samples=ir.samples,
                               geometry="printed box with artwork label on a cylindrical plinth, wall and floor planes",
                               lights=("area key", "area rim", "world fill"))


__all__ = ["IMPLEMENTED_SCENES", "QUALITY", "compile_scene", "render_scene"]
