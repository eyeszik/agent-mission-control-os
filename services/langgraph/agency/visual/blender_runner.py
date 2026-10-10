"""Standalone Blender (bpy) scene renderer. Run in its own process:

    python -I blender_runner.py <spec.json> <out_dir>

It imports only ``bpy`` and the standard library, so it can run isolated from
the application. It builds a procedural, physically based still life from the
spec (geometry, PBR materials, an area "window" light, a calibrated camera
with depth of field), renders it with Cycles on the CPU, and writes:

* ``<out_dir>/frame_####.png`` (one still, or N frames for a turntable);
* ``<out_dir>/scene.json``: provenance of exactly what was rendered.

Nothing is downloaded and no network is used. Every asset is procedural, so
the image carries no third-party rights.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import bpy  # noqa: E402  (only available inside a Blender-enabled interpreter)


def srgb_to_linear(hex_value: str) -> tuple[float, float, float, float]:
    h = hex_value.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return (out[0], out[1], out[2], 1.0)


def principled(name: str, color: str, *, roughness: float, metallic: float = 0.0, sheen: float = 0.0,
               bump_scale: float | None = None, bump_strength: float = 0.15, wave: bool = False,
               wave_axis: str = "X", weave: bool = False) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = srgb_to_linear(color)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if metallic == 0.0 and "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.25 if sheen else 0.4  # fibres scatter, they do not shine
    if sheen and "Sheen Weight" in bsdf.inputs:
        bsdf.inputs["Sheen Weight"].default_value = sheen
    if bump_scale is not None:
        tex = nodes.new("ShaderNodeTexWave" if wave else "ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = bump_scale
        if wave:
            tex.bands_direction = wave_axis
            tex.inputs["Distortion"].default_value = 0.6
            tex.inputs["Detail"].default_value = 2.0
        coords = nodes.new("ShaderNodeTexCoord")  # object space: bump scale is per metre, independent of mesh size
        links.new(coords.outputs["Object"], tex.inputs["Vector"])
        height = tex.outputs["Fac"]
        if weave:  # twill: two perpendicular band sets multiplied
            tex2 = nodes.new("ShaderNodeTexWave")
            tex2.bands_direction = "Y" if wave_axis == "X" else "X"
            tex2.inputs["Scale"].default_value = bump_scale
            tex2.inputs["Distortion"].default_value = 0.6
            links.new(coords.outputs["Object"], tex2.inputs["Vector"])
            mul = nodes.new("ShaderNodeMath")
            mul.operation = "MULTIPLY"
            links.new(tex.outputs["Fac"], mul.inputs[0])
            links.new(tex2.outputs["Fac"], mul.inputs[1])
            height = mul.outputs["Value"]
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = bump_strength
        links.new(height, bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def add(obj_op, *, name: str, material: bpy.types.Material, **kw) -> bpy.types.Object:
    obj_op(**kw)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(material)
    return obj


class SceneInputError(ValueError):
    """A required scene input is missing or unsafe; the run fails before rendering anything."""


def local_input(spec_dir: Path, name: str) -> Path:
    """Inputs must be plain files inside the spec's own directory: no absolute paths, no '..'."""
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts or not name:
        raise SceneInputError(f"unsafe input path {name!r}")
    path = (spec_dir / candidate).resolve()
    if spec_dir.resolve() not in path.parents or not path.is_file():
        raise SceneInputError(f"missing scene input {name!r}")
    return path


def build_package_scene(spec: dict, spec_dir: Path) -> dict:
    """A printed box on a plinth. The box's front label is the supplied artwork (e.g. a generated poster)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    pal = spec["palette"]
    art = local_input(spec_dir, spec["texture"])
    card = principled("box_card", pal["paper"], roughness=0.5, bump_scale=60.0, bump_strength=0.02)
    plinth_m = principled("plinth", pal["muted"], roughness=float(spec.get("plinth_roughness", 0.65)))
    floor_m = principled("floor", pal["paper"], roughness=0.9)
    wall_m = principled("wall", pal["paper"], roughness=0.95, bump_scale=8.0, bump_strength=0.04)
    label = bpy.data.materials.new("label_artwork")
    label.use_nodes = True
    nodes, links = label.node_tree.nodes, label.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = float(spec.get("label_roughness", 0.45))
    img = nodes.new("ShaderNodeTexImage")
    img.image = bpy.data.images.load(str(art))
    links.new(img.outputs["Color"], bsdf.inputs["Base Color"])

    add(bpy.ops.mesh.primitive_plane_add, name="floor", material=floor_m, size=14)
    add(bpy.ops.mesh.primitive_plane_add, name="wall", material=wall_m, size=14, location=(0, 3.0, 3.0), rotation=(math.radians(90), 0, 0))
    plinth = add(bpy.ops.mesh.primitive_cylinder_add, name="plinth", material=plinth_m, vertices=128, radius=0.62, depth=0.5,
                 location=(0, 0.2, 0.25))
    plinth.modifiers.new("bevel", "BEVEL").width = 0.01
    w, d, h = 0.6, 0.24, 0.8
    box = add(bpy.ops.mesh.primitive_cube_add, name="box", material=card, size=1, location=(0, 0.2, 0.5 + h / 2))
    box.scale = (w, d, h)
    box.modifiers.new("bevel", "BEVEL").width = 0.004
    front = add(bpy.ops.mesh.primitive_plane_add, name="label", material=label, size=1,
                location=(0, 0.2 - d / 2 - 0.0015, 0.5 + h / 2), rotation=(math.radians(90), 0, 0))
    front.scale = (w * 0.985, h * 0.985, 1)
    for o in (plinth, box):
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.shade_smooth()

    bpy.ops.object.light_add(type="AREA", location=(-2.2, -2.0, 2.6))
    key = bpy.context.active_object
    key.data.size, key.data.energy = 2.0, float(spec.get("key_energy", 650.0))
    key.rotation_euler = (math.radians(48), 0, math.radians(-42))
    bpy.ops.object.light_add(type="AREA", location=(2.4, 1.6, 2.2))
    rim = bpy.context.active_object
    rim.data.size, rim.data.energy = 1.2, float(spec.get("rim_energy", 220.0))
    rim.rotation_euler = (math.radians(-40), math.radians(30), math.radians(140))
    world = bpy.data.worlds.new("world")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.3

    cam_spec = spec.get("camera", {})
    bpy.ops.object.camera_add()
    cam = bpy.context.active_object
    cam.data.lens = float(cam_spec.get("focal_mm", 50))
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = float(cam_spec.get("fstop", 5.6))
    target = bpy.data.objects.new("focus", None)
    target.location = (0.0, 0.2 - d / 2, 0.5 + h / 2)
    bpy.context.collection.objects.link(target)
    cam.data.dof.focus_object = target
    track = cam.constraints.new("TRACK_TO")
    track.target, track.track_axis, track.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    scene.camera = cam
    art_sha = hashlib.sha256(art.read_bytes()).hexdigest()
    return {"camera": cam, "target": target, "materials": [m.name for m in bpy.data.materials],
            "inputs": [{"name": spec["texture"], "sha256": art_sha}]}


def build_scene(spec: dict) -> dict:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    pal = spec["palette"]

    cloth = principled("bone_wool", pal["surface"], roughness=0.97, sheen=0.25, bump_scale=180.0, bump_strength=0.18,
                       wave=True, weave=True)
    under = principled("charcoal_wool", pal["text"], roughness=0.95, sheen=0.3, bump_scale=260.0, bump_strength=0.12,
                       wave=True, weave=True)
    plaster = principled("bone_plaster", pal["surface"], roughness=0.97, bump_scale=6.0, bump_strength=0.08)
    thread = principled("oxblood_thread", pal["primary"], roughness=0.8, sheen=0.0, bump_scale=95.0, bump_strength=0.7,
                        wave=True, wave_axis="Z")
    wood = principled("spool_wood", "#a9825a", roughness=0.55, bump_scale=40.0, bump_strength=0.04, wave=True, wave_axis="X")
    steel = principled("needle_steel", "#c9ccd1", roughness=0.16, metallic=1.0)

    # table: charcoal wool, a bone plaster wall behind (no visible horizon)
    add(bpy.ops.mesh.primitive_plane_add, name="table", material=under, size=14)
    wall = add(bpy.ops.mesh.primitive_plane_add, name="wall", material=plaster, size=14, location=(0, 4.2, 3.0),
               rotation=(math.radians(90), 0, 0))
    wall.name = "wall"
    # folded bone wool: a soft, subdivided slab with gentle displacement wrinkles
    fold = add(bpy.ops.mesh.primitive_cube_add, name="folded_cloth", material=cloth, size=1, location=(0.05, 0.2, 0.045))
    fold.scale = (1.7, 1.15, 0.045)
    fold.rotation_euler = (0, 0, math.radians(-6))
    bev = fold.modifiers.new("bevel", "BEVEL")
    bev.width, bev.segments = 0.04, 8
    fold.modifiers.new("subsurf", "SUBSURF").levels = 3
    wrinkle = bpy.data.textures.new("wrinkle", type="CLOUDS")
    wrinkle.noise_scale = 0.45
    disp = fold.modifiers.new("wrinkles", "DISPLACE")
    disp.texture, disp.strength = wrinkle, 0.018

    # spool: wooden core and flanges, oxblood thread wound between them
    for z, nm in ((0.105, "flange_low"), (0.455, "flange_high")):
        f = add(bpy.ops.mesh.primitive_cylinder_add, name=nm, material=wood, vertices=128, radius=0.2, depth=0.03, location=(0, 0.1, z))
        f.modifiers.new("bevel", "BEVEL").width = 0.008
    add(bpy.ops.mesh.primitive_cylinder_add, name="thread", material=thread, vertices=160, radius=0.168, depth=0.32, location=(0, 0.1, 0.28))
    add(bpy.ops.mesh.primitive_cylinder_add, name="core", material=wood, vertices=64, radius=0.06, depth=0.36, location=(0, 0.1, 0.28))
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name not in {"table", "wall"}:
            bpy.context.view_layer.objects.active = o
            bpy.ops.object.shade_smooth()

    # needle resting on the folded cloth, diagonal
    needle = add(bpy.ops.mesh.primitive_cylinder_add, name="needle", material=steel, vertices=32, radius=0.006, depth=0.62,
                 location=(0.42, -0.12, 0.098), rotation=(0, math.radians(90), math.radians(-34)))
    bpy.context.view_layer.objects.active = needle
    bpy.ops.object.shade_smooth()

    # light: one large soft "north window" area light, plus a faint warm world fill
    bpy.ops.object.light_add(type="AREA", location=(-2.6, -1.4, 2.4))
    key = bpy.context.active_object
    key.data.shape, key.data.size, key.data.size_y = "RECTANGLE", 2.4, 3.2
    key.data.energy = float(spec.get("key_energy", 900.0))
    key.data.color = (1.0, 0.985, 0.96)
    key.rotation_euler = (math.radians(50), math.radians(-38), math.radians(-28))
    world = bpy.data.worlds.new("world")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.32, 0.30, 0.28, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.35

    # camera: 85mm, f/2.8, focused on the spool
    cam_spec = spec.get("camera", {})
    bpy.ops.object.camera_add()
    cam = bpy.context.active_object
    cam.data.lens = float(cam_spec.get("focal_mm", 85))
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = float(cam_spec.get("fstop", 2.8))
    target = bpy.data.objects.new("focus", None)
    target.location = (0.0, 0.1, 0.26)
    bpy.context.collection.objects.link(target)
    cam.data.dof.focus_object = target
    track = cam.constraints.new("TRACK_TO")
    track.target, track.track_axis, track.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    scene.camera = cam
    return {"camera": cam, "target": target, "materials": [m.name for m in bpy.data.materials]}


def configure_render(spec: dict) -> dict:
    scene = bpy.context.scene
    r = spec["render"]
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = int(r["samples"])
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.seed = int(r["seed"])
    scene.render.resolution_x, scene.render.resolution_y = int(r["width"]), int(r["height"])
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.threads_mode = "FIXED"
    scene.render.threads = int(r.get("threads", 4))
    denoiser = None
    try:
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
        denoiser = "OPENIMAGEDENOISE"
    except (TypeError, AttributeError):
        scene.cycles.use_denoising = False
    view = "AgX" if "AgX" in [i.identifier for i in scene.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
    scene.view_settings.view_transform = view
    scene.view_settings.look = "AgX - Medium High Contrast" if view == "AgX" else "Medium High Contrast"
    return {"denoiser": denoiser, "view_transform": view, "look": scene.view_settings.look}


def main(spec_path: str, out_dir: str) -> int:
    started = time.time()
    spec = json.loads(Path(spec_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        built = build_package_scene(spec, Path(spec_path).parent) if spec.get("scene") == "package_on_plinth" else build_scene(spec)
    except SceneInputError as exc:
        (out / "error.json").write_text(json.dumps({"error": "SCENE_INPUT", "detail": str(exc)}))
        print(f"SCENE_INPUT: {exc}", file=sys.stderr)
        return 3
    render_info = configure_render(spec)
    cam_spec = spec.get("camera", {})
    frames = int(spec.get("frames", 1))
    distance, height = float(cam_spec.get("distance", 3.4)), float(cam_spec.get("height", 1.15))
    azimuth0 = math.radians(float(cam_spec.get("azimuth_deg", -62)))
    sweep = math.radians(float(spec.get("turntable_sweep_deg", 0)))
    files = []
    for i in range(frames):
        a = azimuth0 + (sweep * i / max(frames - 1, 1) if frames > 1 else 0.0)
        built["camera"].location = (distance * math.cos(a), 0.1 + distance * math.sin(a), height)
        bpy.context.scene.render.filepath = str(out / f"frame_{i + 1:04d}.png")
        bpy.ops.render.render(write_still=True)
        files.append(f"frame_{i + 1:04d}.png")
    provenance = {
        "renderer": "blender_cycles",
        "blender_version": bpy.app.version_string,
        "device": "CPU",
        "frames": files,
        "scene_spec_sha256": hashlib.sha256(Path(spec_path).read_bytes()).hexdigest(),
        "materials": sorted(built["materials"]),
        "assets": built.get("inputs") or "procedural only (no external textures, HDRIs or models)",
        "render": {**spec["render"], **render_info},
        "wall_seconds": round(time.time() - started, 2),
    }
    (out / "scene.json").write_text(json.dumps(provenance, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
