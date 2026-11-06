"""Renderer capability registry: discovery, never assumption.

Each entry is a ``CapabilityManifest`` built from what this host actually has:
an import that resolves, a binary on PATH, a package in ``apps/web`` node_modules,
or a module in this repository. Nothing reports AVAILABLE on configuration alone.
Engines named by the brief but not installed (Paper.js, SVG.js, Rough.js, p5.js,
PixiJS, React Three Fiber, Remotion, Motion Canvas) are listed as MISSING; this
module never installs anything.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

from services.langgraph.agency.visual.browser import probe_browser
from services.langgraph.agency.visual.capabilities import probe_blender, probe_three, probe_video

from .contracts import CapabilityManifest

REPO_ROOT = Path(__file__).resolve().parents[4]
WEB_MODULES = REPO_ROOT / "apps" / "web" / "node_modules"
OFFLINE = "local process; no network required"


def _npm(name: str) -> tuple[bool, str | None]:
    pkg = WEB_MODULES / name / "package.json"
    if not pkg.is_file():
        return False, None
    try:
        return True, json.loads(pkg.read_text()).get("version")
    except ValueError:
        return True, None


def _m(capability_id, implementation, status, version, media, inp, out, det, binaries, limits, licence, trust, validators,
       blockers=()):
    return CapabilityManifest(capability_id=capability_id, implementation=implementation, installed_version=version,
                              status=status, media_types=media, input_schema=inp, output_schema=out, deterministic=det,
                              offline_supported=True, required_binaries=binaries, resource_limits=limits,
                              license_status=licence, trust_boundary=trust, supported_validators=validators,
                              blockers=tuple(blockers))


def discover() -> list[CapabilityManifest]:
    out: list[CapabilityManifest] = []
    out.append(_m("vector.svg", "agency.foundry.compose (pure Python SVG writer)", "AVAILABLE", "amc-foundry/v1",
                  ("image/svg+xml",), "CompositionIR", "SVG text", "yes", (), {"max_bytes": 512_000},
                  "repository code", "in-process, pure", ("svg_safety", "palette_conformance", "viewbox", "geometry_present")))
    browser = probe_browser()
    out.append(_m("raster.chromium", "local Chromium via @playwright/test (agency.visual.browser)",
                  "AVAILABLE" if browser["available"] else "MISSING", browser.get("chromium") or None,
                  ("image/png",), "SVG text + width/height", "PNG bytes", "declared_nondeterministic", ("node", "chromium"),
                  {"timeout_s": 120, "network": "namespace-isolated, non-data: requests aborted"},
                  "Chromium BSD-3 / Playwright Apache-2.0", "subprocess, scrubbed env", ("png_decode", "dimensions", "nonblank"),
                  browser["blockers"]))
    out.append(_m("web.html_css", "agency.foundry.experience (HTML/CSS/vanilla JS) + local Chromium evaluation",
                  "AVAILABLE" if browser["available"] else "MISSING", None, ("text/html",), "ExperienceIR", "HTML document",
                  "yes", ("node", "chromium"), {"timeout_s": 300}, "repository code", "subprocess browser, no network",
                  ("keyboard_flow", "labels", "contrast", "reflow", "reduced_motion", "text_scaling"), browser["blockers"]))
    out.append(_m("web.design_tokens", "agency.design_tokens (the one DTCG compiler)", "AVAILABLE", "amc-dtcg-compiler/v1",
                  ("application/json", "text/css"), "DTCG document", "CSS custom properties", "yes", (), {},
                  "repository code", "in-process, pure", ("dtcg_compile",)))
    pil = importlib.util.find_spec("PIL") is not None
    out.append(_m("raster.pillow", "Pillow (decode/measure only)", "AVAILABLE" if pil else "MISSING", None, ("image/png",),
                  "PNG bytes", "pixel statistics", "yes", (), {}, "HPND", "in-process", ("png_decode",),
                  () if pil else ("MISSING_DEPENDENCY:Pillow",)))
    magick = shutil.which("magick") or shutil.which("convert")
    out.append(_m("raster.imagemagick", "ImageMagick", "AVAILABLE" if magick else "MISSING", None, ("image/png",), "SVG",
                  "PNG", "declared_nondeterministic", ("magick",), {}, "ImageMagick licence", "subprocess", (),
                  () if magick else ("MISSING_DEPENDENCY:imagemagick (not used; Chromium rasterizes)",)))
    blender = probe_blender()
    out.append(_m("spatial.blender", "Blender Cycles via bpy (agency.visual.blender_runner)",
                  "AVAILABLE" if blender.available else "MISSING", blender.version, ("image/png",), "SceneIR", "PNG + scene.json",
                  "declared_nondeterministic", ("bpy",), {"timeout_s": 1800}, "Blender GPL-2.0-or-later (tool, not linked output)",
                  "subprocess, python -I, network namespace", ("png_decode", "dimensions", "nonblank"), blender.blockers))
    three = probe_three()
    out.append(_m("spatial.threejs", "three (apps/web)", "AVAILABLE" if three.available else "MISSING", three.version,
                  ("text/html",), "SceneIR", "WebGL/WebGPU canvas", "no", ("node", "chromium"), {}, "MIT", "browser",
                  ("webgl_capture",), three.blockers))
    video = probe_video()
    out.append(_m("motion.ffmpeg", "FFmpeg via agency.visual.renderers.encode_video", "AVAILABLE" if video.available else "MISSING",
                  video.version, ("video/mp4",), "PNG frame sequence", "H.264 MP4", "declared_nondeterministic",
                  ("ffmpeg", "ffprobe"), {"timeout_s": 300}, "FFmpeg LGPL/GPL build (tool)", "subprocess, scrubbed env",
                  ("ffprobe_dims_fps_frames_codec",), video.blockers))
    from services.langgraph.agency.project_os.video import freevideoforge_capability

    fvf = freevideoforge_capability()
    out.append(_m("motion.freevideoforge", "services/freevideoforge (topic -> narrated explainer)",
                  "AVAILABLE" if fvf["can_render"] else "MISSING", None, ("video/mp4",), "GenerateRequest", "final.mp4 + manifest",
                  "declared_nondeterministic", ("ffmpeg", "ffprobe"), {}, "repository code", "subprocess",
                  ("quality-report",), fvf["blockers"]))
    for npm, cid, media in (("paper", "vector.paperjs", "image/svg+xml"), ("@svgdotjs/svg.js", "vector.svgjs", "image/svg+xml"),
                            ("roughjs", "vector.roughjs", "image/svg+xml"), ("p5", "procedural.p5", "image/png"),
                            ("pixi.js", "procedural.pixi", "image/png"), ("@react-three/fiber", "spatial.r3f", "text/html"),
                            ("remotion", "motion.remotion", "video/mp4"), ("@motion-canvas/core", "motion.motioncanvas", "video/mp4")):
        present, version = _npm(npm)
        out.append(_m(cid, npm, "AVAILABLE" if present else "MISSING", version, (media,), "n/a", "n/a", "no", ("node",), {},
                      "unverified until installed and reviewed", "browser/node", (),
                      () if present else (f"MISSING_DEPENDENCY:{npm} (not installed; not required by the shipped routes)",)))
    return out


def by_id() -> dict[str, CapabilityManifest]:
    return {c.capability_id: c for c in discover()}


__all__ = ["by_id", "discover"]
