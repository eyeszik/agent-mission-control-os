---
name: browser-qa-chromium
description: Provision and run the local Chromium needed by the UCPO browser QA gate (services/langgraph/agency/ucpo/qa.py) when Playwright's own browser download is unreachable. Use when browser QA tests show NOT_RUN, when the QA runner reports "Executable doesn't exist", or after an environment reset removes ~/.cache/ms-playwright.
---

# Browser QA Chromium (local stand-in)

## When to use
- `pytest services/langgraph/tests/test_ucpo_build.py -rs` shows `NOT_RUN: Playwright Chromium not installed`.
- Playwright reports `Executable doesn't exist at ~/.cache/ms-playwright/...`.
- The environment was reset (the cache is outside the repo and is not preserved).

## Steps
1. Install the workspace dependencies, without Playwright's CDN downloads:
   `npx --yes pnpm@10.29.3 install --frozen-lockfile --ignore-scripts` (run at the repo root).
2. Provision the browser: `scripts/qa/provision-qa-chromium.sh`.
   It fetches the npm package `@sparticuz/chromium@153.0.0`, decompresses the binary and the `al2023` libraries,
   and writes wrappers at the exact paths Playwright 1.64 expects. It ends with a smoke launch under `env -i`.
3. Confirm with `pytest services/langgraph/tests/test_ucpo_build.py -q -rs`. Expect 5 passed, no skips.

## Gotchas (learned the hard way)
- Playwright 1.64 default headless uses a **separate headless-shell path**
  (`chromium_headless_shell-<rev>/chrome-headless-shell-linux64/chrome-headless-shell`).
  `chromium.executablePath("chromium-headless-shell")` returns the full-Chromium path in this version, so do not use it.
- The sandbox runs the runner under `env -i`, so `LD_LIBRARY_PATH` is lost. The wrapper sets it itself.
- The wrapper adds `--no-zygote`. Without it the zygote dies in the namespace.
- Playwright's error message names the exact missing path. Read it rather than guessing.

## Honest limits
- This is a **stand-in binary**, not an official Playwright build. It validates the QA gate in this sandbox only.
- CI must install Playwright's own Chromium (`pnpm exec playwright install chromium`). Do not describe a local pass as CI evidence.
- Never fake a pass: a missing browser must stay `NOT_RUN` or `BLOCKED`.

## Known: WebGL is unavailable in this stand-in (do not re-probe)
- The stand-in build reports `getContext("webgl")` as `NONE`, with or without `--no-zygote`, `--ignore-gpu-blocklist`,
  `--enable-webgl`, `--headless=old`, or the package's `swiftshader` libraries (extracted and on `LD_LIBRARY_PATH`).
- Effect: `services/langgraph/tests/test_abc_v6.py::test_t11_browser_executes_shaders_handles_context_loss_and_renders_svg_sizes`
  fails with `NO_WEBGL_CONTEXT`. This is an environment limit of the stand-in, not a shader defect.
- Do not skip or weaken that test to make the suite green. Report it as an open item until a Chromium with WebGL runs.
