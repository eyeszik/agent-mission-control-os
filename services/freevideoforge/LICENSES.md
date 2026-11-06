# Licence and dependency inventory

FreeVideoForge is designed so that a complete run costs nothing and requires no
account. This file records what it depends on and under what terms, so that
claim is checkable rather than asserted.

Licence identifiers below are the ones each project publishes. This is an
engineering inventory, not legal advice — if you redistribute a build, confirm
the terms that apply to your distribution.

## Required at runtime

| Component | Role | Licence | Notes |
| --- | --- | --- | --- |
| **Python ≥ 3.10** | runtime | PSF-2.0 | Standard library only, beyond the row below |
| **Pillow** | frame composition | MIT-CMU (HPND) | The only third-party Python dependency |
| **FFmpeg / ffprobe** | encoding, muxing, validation | LGPL-2.1-or-later, or GPL-2.0-or-later depending on build flags | Invoked as an external binary, never linked. Distributions built with `--enable-gpl` (including `libx264`) are GPL. **If you redistribute a bundled FFmpeg, check which build you are shipping.** |

FreeVideoForge itself invokes FFmpeg as a separate process over a pipe and does
not link against it.

## Optional, detected if already installed

| Component | Role | Licence | Download behaviour |
| --- | --- | --- | --- |
| **espeak-ng** | local TTS | GPL-3.0-or-later | Invoked as a binary if on `PATH`. Never installed automatically. |
| **Piper** | local neural TTS | MIT (voices vary — check each voice's own card) | Used only if both the binary and a voice are already present. **Never downloads a voice model.** |
| **Ollama** + models | local LLM scripting | Ollama: MIT. Model weights carry their own licences (Llama Community Licence, Apache-2.0, etc. — varies per model) | Used only if a runtime is already serving a pulled model. **Never pulls a model.** |
| **ComfyUI** + checkpoints | tier A/B generative media | ComfyUI: GPL-3.0. Checkpoints vary widely (CreativeML OpenRAIL-M, Apache-2.0, non-commercial research licences, …) | **Detected only.** No adapter is shipped, nothing is downloaded, and no service is started. |
| **imageio-ffmpeg** | static FFmpeg fallback | BSD-2-Clause (wheel); the bundled FFmpeg binary carries FFmpeg's own terms | Used only if installed. Ships `ffmpeg` but no `ffprobe`. |

## Fonts

FreeVideoForge **ships no font files**. It discovers a face already installed on
the host, preferring these libre families:

| Family | Licence |
| --- | --- |
| DejaVu | Bitstream Vera / Public-domain-derived permissive licence |
| Liberation | SIL OFL-1.1 |
| Noto | SIL OFL-1.1 |
| GNU FreeFont | GPL-3.0-or-later with font exception |

If none is found, Pillow's built-in bitmap face is used and `doctor` reports the
degraded state rather than failing.

## Generated media

All visual and audio content produced by the mandatory renderer is generated
procedurally at render time:

- Backgrounds, motifs and typography are drawn by FreeVideoForge's own code.
- The ambient music bed is synthesised by FFmpeg from sine sources.
- No stock library, sample pack, scraped asset or pretrained model contributes
  to tier C output.

There is therefore no third-party asset licence attached to a tier C render.
Output produced with an optional local model inherits whatever that model's
licence says — that is your decision to make, which is one reason
FreeVideoForge never installs one for you.

## Paid services

None. No component of FreeVideoForge contacts a paid API, and the provider
registry refuses any provider that reports `requires_payment` unless you pass
`--allow-paid` explicitly. No such provider ships with the project.
