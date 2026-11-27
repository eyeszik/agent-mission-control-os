# Design — treatment, style rules, references, signature moment, shot plan

## Production route (chosen)

**FreeVideoForge `ffmpeg_motion` tier** — the repository's own local renderer
(`services/freevideoforge/`, v1.0.0), driven by:

- `script` = **template** (deterministic narrative-structure compiler; no LLM on this host),
- `storyboard` = **deterministic** seeded shot planner,
- `speech` = **piper** (offline neural TTS; `en_US-joe-medium`, CC0),
- `captions` = **script_derived** (timed from measured narration),
- `render` = **ffmpeg_motion** (procedural motion graphics; no AI inference, no network),
- QC = **structural** (ffprobe + full decode), tier-letter **C**.

Rejected routes: ComfyUI/diffusion (no backend, no GPU, would break the zero-cost and
truthfulness constraints); Ollama-written script (absent; the template engine keeps every
fact traceable to the supplied brief). espeak-ng formant synthesis was the first build's
narration and is retained as a documented fallback, not used in this delivery.

## Treatment

One continuous camera language: slow, heavy, machined moves (push/pull ≤ 1.10× zoom,
sub-5% pans) over a dark, cool field. The slate system reads as an operations console, not
a marketing page. Type does the talking; motion underlines it. Captions always sit in a
darkened plate — legible at 320×568 before any legibility tuning.

## Style rules

**Do**
- One accent (`#5FD3A6`) per frame; everything else is field/ink/muted.
- Kicker in small caps above a max-6-word headline (renderer-derived; s04 is the known
  exception the QC report shows verbatim).
- Hold each beat ≥ 4.4 s; let captions breathe; never cut on a syllable.
- Preserve explicit continuity strings scene-to-scene (zoom settles before the next cut).

**Don't**
- No gradients beyond the two background stops, no glow bloom, no particle confetti.
- No photoreal humans, no product screenshots invented for the spot, no logos, no watermark.
- No claim that is not in the supplied brief or the repository README.
- No re-labelling `NOT_VERIFIED` creative checks as passed.

## "Character" references

The film has **no human or anthropomorphised characters**. Its protagonist is the
*governed pipeline*: brief in → durable project → gated approval → dry-run delivery.
Identity is carried by the motif system only — grid/contour/strata for "system", orbit
for "cycle", beam for "decision/accent hit". Wardrobe, performance and immutables are
therefore **not applicable** (recorded, not silently skipped).

## Signature moment

**Scene 6 — "THE INSIGHT / End To End" (t ≈ 24.9–30.2 s), the `beam` motif with a
1.06→1.08 rightward drift and the accent at full saturation behind
"That is the whole idea, end to end, without the noise."**
Everything before it is restraint; this is the one held accent across the payoff, the
visual rhyme of the approval gate the film is about. It is procedural, seeded
(`20261109005`), and reproduced byte-for-byte on re-render.

## Shot plan (from `storyboard.json`, seed 20261109)

| # | id | role | dur (s) | motif | camera | transition | headline |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | s01 | hook | 5.66 | orbit | drift R→L, zoom 1.06→1.08 | fade (0.45s) | Agent Mission Control, Explained |
| 2 | s02 | context | 4.67 | contour | rise, zoom 1.05→1.09 | dip_to_ink (0.45s) | Why It Matters |
| 3 | s03 | body | 4.92 | contour | settle down, 1.09→1.04 | soft_cut | Agent Mission Control OS |
| 4 | s04 | body | 4.92 | strata | slow push in, 1.00→1.10 | fade (0.45s) | Human Approval is Required Before Anything* |
| 5 | s05 | turn | 4.63 | orbit | pull back, 1.10→1.00 | dip_to_ink (0.45s) | One Assumption, Reordered |
| 6 | s06 | payoff | 5.41 | beam | drift L→R, zoom 1.06→1.08 | soft_cut | End To End |

\* Renderer-derived overlay, 8 words; legible and factual, but flagged in REVIEW as the
weakest typographic frame. Kept because it is exactly what the narration says.
The mint `strata` line crosses behind the "Approval is" glyph row (D-1, LOW — see
`qa/qa-report.md`); glyphs are drawn on top and uninterrupted.

## Cue map (burned captions = sidecar `captions.srt`)

| Cue | In → Out (s) | Line | Scene |
| --- | --- | --- | --- |
| 1 | 0.080 → 2.740 | Agent Mission Control, explained properly. | s01 |
| 2 | 5.736 → 7.223 | It matters more than it looks. | s02 |
| 3 | 10.408 → 14.299 | Agent Mission Control OS is the execution and governance layer. | s03 |
| 4 | 15.326 → 18.346 | Human approval is required before anything is delivered. | s04 |
| 5 | 20.244 → 23.496 | Change that one assumption and the whole picture reorders itself. | s05 |
| 6 | 24.876 → 26.324 | That is the whole idea, | s06 |
| 7 | 26.324 → 28.186 | end to end, without the noise. | s06 |

One timing authority: FreeVideoForge's per-scene measured speech durations → scene lengths
→ caption cues → burn-in → AAC track. Nothing is hand-timed.

## Timing resolution (from the low-cost animatic)

The 404×720 draft (`--quality draft`) is the animatic. Findings and resolutions:

1. **Comprehension** — beats 1, 3, 4 carry the product facts; 2, 5, 6 are narrative
   scaffolding (the template engine's framing pools). Accepted, because changing them
   would mean editing copy by hand and breaking `content_source = "brief"` provenance.
   Documented rather than disguised.
2. **Pacing** — planned 30.21 s vs 30.0 s target (+0.21 s); the longest beat (s01, 5.66 s)
   earns it as the cold open; no beat is under 4.4 s. No re-cut needed.
3. **Caption split** — the payoff splits across two cues at a clause boundary (24.876 /
   26.324); both lines sit inside the scene and inside the safe plate. No fix.
4. **Drift** — `manifest.json → duration.drift_seconds = +0.206`, within the 0.480 s gate.
5. **Legibility** — kickers are small caps; verified at 100% and at 320 px downscale in
   `qa/frames/`.

The animatic draft and both espeak/piper renders live under gitignored `out/` on the
build host; only the packaged delivery is committed. The scene plan (motifs, camera,
transitions, seeds) is byte-identical between the superseded espeak build and this Piper
re-render — narration-derived caption timings and audio are what changed.
