# agency/visual

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Local visual engine and durable runtime — real local renders, bounded ticks

`services/langgraph/agency/visual/` renders on the host only (no hosted image/video API):

- **R1 Blender Cycles.** `blender_runner.py`, run under `python -I` and, where possible, `unshare -rn`.
- **R5 FFmpeg turntables.** Encoded only from frames that R1 rendered.
- **R4 vector mark.** The unchanged `agency.assets` SVG.
- **R2 offline diffusion.** Needs local weights plus an `amc-model.json` licence record.
- **R3 Three.js.** `three_renderer_for` picks WebGPU vs WebGL by shader architecture.

R2 and R3 are probed and **blocked** when absent; never substitute another route. Outputs become `media_asset`
artifacts. `verify.verify_media` reopens the stored bytes for Q0–Q4. Q5–Q7 are always `human_required`, and a
check that could not run is `INCONCLUSIVE`, never `PASSED`. `browser.py`/`browser_runner.cjs` drive local Chromium
for WebGL/SVG evidence.

`agency/intake/release.py` is the shared approval binding + release verdict, used by intake, visual and durable jobs.
