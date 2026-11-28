# Credits and licences — "Agent Mission Control OS, Explained"

Nothing in the video is copied from a third-party creative work. All imagery is
procedural (generated at render time). Components and licences:

| Component | Version | Licence | Used for |
| --- | --- | --- | --- |
| FreeVideoForge (this repository, `services/freevideoforge/`) | 1.0.0 | see repository (no top-level LICENSE file present at the pinned commit) | pipeline, storyboard, QC |
| Pillow | 13.0.0 | MIT-CMU (HPND) | frame/text rasterisation |
| FFmpeg (imageio-ffmpeg wheel `imageio-ffmpeg` 9.0.2, binary `ffmpeg-linux-x86_64-v9.0.2`) | n9.0.2-17-g2a571b6068 | LGPL-2.1+/GPL (build config in `qa/decode-check.log`: `--enable-gpl`) | encode/decode, filters |
| ffprobe (npm `ffprobe-static@3.1.0`, johnvansickle static build) | 4.0.2 | LGPL-2.1+ | QC probing (mismatch documented) |
| piper-tts (PyPI `piper-tts`; OHF-voice/piper1-gpl distribution) | 1.8.0 | GPL-3.0-or-later | narration synthesis (this build) |
| `en_US-joe-medium` voice (PyPI `joe-us-piper-voice` 1.0.0, third-party repackaging of rhasspy `piper-voices` v1.0.0; upstream voice is CC0) | 1.0.0 | CC0 (voice) · MIT (packaging) | en-US neural voice |
| espeak-ng (via `espeakng-loader` wheel 0.2.4, bundled `libespeak-ng`) | 1.x bundle | GPLv3 (library) | narration synthesis — **fallback only, not used in this build** |
| espeak-ng voices/data (bundled in `espeak-ng-data`) | bundle | GPLv3 | en-us voice — fallback only |
| DejaVu fonts (host `/usr/share/fonts/truetype/dejavu/`) | bundled with OS | Bitstream Vera / Arev license (permissive) | all on-screen type |
| Node.js | v22.22.3 | MIT | installing ffprobe-static only |

**Engine license.** `piper-tts` 1.8.0 (OHF-voice/piper1-gpl distribution) is GPL-3.0-or-later per its installed package metadata — not MIT. The engine is a build-time tool; the delivered film embeds only synthesized speech, not the engine or its code. License identifiers in this file come from installed package metadata; this table is a summary, not legal advice.

**Voice packaging disclosure.** `joe-us-piper-voice` is a third-party repackaging, not an
official rhasspy artifact; the bundled `en_US-joe-medium.onnx` is bit-identical to the
upstream CC0 voice file (SHA-256 `58afce0321b8d9c46d7cdf9c16500cc55a793b4220212dba6b70fb788b3baf06`;
config `3d6d5410b3795cb1950595247ef8f06190719e6fdbfa3a2356d8ec368e1aad33` — see
`environment-record.json → voice_models`). FreeVideoForge downloaded **nothing**; the
voice was installed by the operator via `pip install`.

**No** third-party music, footage, photography, icon sets, logos, trademarks or stock
assets are included or claimed, and no model weights are committed to this repository
(the Piper voice is installed locally via `pip install`; only its SHA-256s are recorded).
The on-screen accent colour, palette and motif system are original to this render
(see `DESIGN.md`).

Attribution required: none by the licences above beyond preserving their notices, which
remain in the wheels/packages as installed. This file satisfies attribution for the
delivery package itself.

Commercial use: all listed components permit it. The video depicts the repository's own
project; product names belong to their owners.
