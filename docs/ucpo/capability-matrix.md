# UCPO capability matrix

Discovered on the development host on 2026-10-25 by `ucpo.capabilities.capability_matrix()` (also `GET /ucpo/capabilities`). Every row comes from a probe (an import, a binary, an installed package, or the sandbox demonstration), never from configuration. On another host, run the route; this table is a snapshot, not a promise.

## Capabilities

| Capability | Status | Blockers |
| --- | --- | --- |
| `web.ucpo_site` (sandboxed build + browser QA) | AVAILABLE | |
| `web.html_css`, `web.design_tokens`, `vector.svg` | AVAILABLE | |
| `raster.chromium`, `raster.pillow`, `raster.imagemagick` | AVAILABLE | |
| `spatial.blender` | AVAILABLE | |
| `motion.ffmpeg`, `motion.freevideoforge` | AVAILABLE | |
| `spatial.threejs`, `spatial.r3f` | MISSING | not installed in `apps/web` |
| `vector.paperjs`, `vector.svgjs`, `vector.roughjs`, `procedural.p5`, `procedural.pixi`, `motion.remotion`, `motion.motioncanvas` | MISSING | not installed; not required by shipped routes |
| `provider.t2i`, `provider.t2v` | MISSING | no verified provider adapter is installed |
| `provider.xr_runtime` | MISSING | no WebXR/OpenXR runtime or device adapter |
| `provider.print` | MISSING | no print or fabrication vendor adapter |

## Disciplines

"ROUTED" means an available capability exists for the discipline's route; execution stays with that capability's owner.

| Discipline | Route | Capabilities, or what is missing |
| --- | --- | --- |
| 01 Art Direction | ROUTED | vector.svg |
| 02 Brand Identity | ROUTED | vector.svg, web.design_tokens |
| 03 Typography | ROUTED | web.design_tokens, web.html_css |
| 04 Editorial Design | ROUTED | web.ucpo_site |
| 05 Conceptual Photography | CAPABILITY_GAP | provider.t2i: ImageSpec prompt package only |
| 06 UI/UX | ROUTED | web.ucpo_site |
| 07 Interactive 3D | CAPABILITY_GAP | spatial.threejs, spatial.r3f: SceneIR spec (Blender stills where available) |
| 08 AR/VR/XR | CAPABILITY_GAP | provider.xr_runtime: scene and interaction spec only |
| 09 Narrative Web | ROUTED | web.ucpo_site |
| 10 Campaigns/Posters | ROUTED | vector.svg, raster.chromium |
| 11 Motion Design | ROUTED | vector.svg, raster.chromium, motion.ffmpeg |
| 12 Technical/Information Design | ROUTED | web.ucpo_site |
| 13 Environmental/Physical Graphics | ROUTED (stills only) | spatial.blender; provider.print missing, so fabrication is never ordered |
| 14 Spatial Branding | ROUTED | spatial.blender |
| 15 Cross-Media Identity | ROUTED | vector.svg, web.design_tokens, web.ucpo_site, motion.ffmpeg |

## Presentation systems and prompt modules

- Presentation systems: Visual Identity Board, Editorial Design System, Conceptual Photography Board, Experimental Graphics Collection, and Digital Experience/UI Board.
  - Each compiles through the website line. All five examples were built and browser-verified on this host with `website --board <id>`: build PASSED, browser QA PASSED, coverage 1.0 and eligible for approval for each.
  - The conceptual photography board uses procedural plates labelled as such. It is never photography.
- Prompt modules: all 16 compile in both variants to `PROMPT_PACKAGE_READY`, with 100% rule, acceptance and failure preservation in the compact variant (`test_ucpo_registry.py`).
- Generation: image and video are `CAPABILITY_GAP`.
