# Credits and licences — "Agent Mission Control OS, Explained"

Nothing in the video is copied from a third-party creative work. All imagery is
procedural (generated at render time). Components and licences:

| Component | Version | Licence | Used for |
| --- | --- | --- | --- |
| FreeVideoForge (this repository, `services/freevideoforge/`) | 1.0.0 | see repository (no top-level LICENSE file present at the pinned commit) | pipeline, storyboard, QC |
| Pillow | 13.0.0 | MIT-CMU (HPND) | frame/text rasterisation |
| FFmpeg (imageio-ffmpeg wheel `imageio-ffmpeg-linux-x86_64-v9.0.2`) | n9.0.2-17-g2a571b6068 | LGPL-2.1+/GPL (build config in `qa/decode-check.log`: `--enable-gpl`) | encode/decode, filters |
| ffprobe (npm `ffprobe-static@3.1.0`, johnvansickle static build) | 4.0.2 | LGPL-2.1+ | QC probing (mismatch documented) |
| espeak-ng (via `espeakng-loader` wheel 0.2.4, bundled `libespeak-ng`) | 1.x bundle | GPLv3 (library) | narration synthesis |
| espeak-ng voices/data (bundled in `espeak-ng-data`) | bundle | GPLv3 | en-us voice |
| DejaVu fonts (host `/usr/share/fonts/truetype/dejavu/`) | bundled with OS | Bitstream Vera / Arev license (permissive) | all on-screen type |
| Node.js | v22.22.3 | MIT | installing ffprobe-static only |

**No** third-party music, footage, photography, icon sets, logos, trademarks, stock
assets or model weights are included or claimed. The on-screen accent colour, palette
and motif system are original to this render (see `DESIGN.md`).

Attribution required: none by the licences above beyond preserving their notices, which
remain in the wheels/packages as installed. This file satisfies attribution for the
delivery package itself.

Commercial use: all listed components permit it. The video depicts the repository's own
project; product names belong to their owners.
