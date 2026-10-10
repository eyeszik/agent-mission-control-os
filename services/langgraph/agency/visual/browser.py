"""R3/R4 browser verification: render in a real local Chromium, read back what it did.

``three_renderer_for`` answers the R3 architecture question without guessing:
TSL/node-material scenes need ``WebGPURenderer``; legacy ``ShaderMaterial``,
``onBeforeCompile`` and ``EffectComposer`` scenes need ``WebGLRenderer``. A
scene mixing both is BLOCKED, because the WebGPU renderer's WebGL2 backend
does not translate legacy GLSL shader hooks.

``capture_webgl`` / ``capture_svg_sizes`` drive ``browser_runner.cjs`` in a
network namespace (when ``unshare`` is available) with every non-``data:``
request aborted, and return the browser's own observations: shader compile and
link logs, pixel statistics read from the GL context, context loss/restore
events, and PNG captures. The GPU in a headless container is usually
SwiftShader (software); the result records the renderer string rather than
claiming hardware acceleration.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from .renderers import _env, _isolated

RUNNER = Path(__file__).with_name("browser_runner.cjs")
DEFAULT_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
REPO_ROOT = Path(__file__).resolve().parents[4]

WEBGPU_FEATURES = frozenset({"tsl", "node_material", "compute_shader", "webgpu_storage"})
WEBGL_ONLY_FEATURES = frozenset({"shader_material", "raw_shader_material", "on_before_compile", "effect_composer"})


def three_renderer_for(features: Iterable[str]) -> dict:
    feats = frozenset(features)
    unknown = sorted(feats - WEBGPU_FEATURES - WEBGL_ONLY_FEATURES - {"standard_material", "gltf"})
    if unknown:
        return {"status": "BLOCKED", "renderer": None, "reasons": [f"UNKNOWN_SHADER_FEATURE:{u}" for u in unknown]}
    modern, legacy = feats & WEBGPU_FEATURES, feats & WEBGL_ONLY_FEATURES
    if modern and legacy:
        return {"status": "BLOCKED", "renderer": None,
                "reasons": ["MIXED_SHADER_ARCHITECTURE: WebGPURenderer does not translate legacy GLSL hooks "
                            f"({sorted(legacy)}) and WebGLRenderer cannot run node/TSL features ({sorted(modern)})"]}
    if modern:
        return {"status": "SELECTED", "renderer": "WebGPURenderer", "reasons": [f"node/TSL features {sorted(modern)}"]}
    if legacy:
        return {"status": "SELECTED", "renderer": "WebGLRenderer", "reasons": [f"legacy GLSL features {sorted(legacy)}"]}
    return {"status": "SELECTED", "renderer": "WebGLRenderer",
            "reasons": ["standard materials only: WebGLRenderer is the widest-supported default"]}


def chromium_path() -> Optional[Path]:
    for candidate in (DEFAULT_CHROMIUM, *(Path(p) for p in (shutil.which("chromium"), shutil.which("chromium-browser")) if p)):
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def _playwright_chromium() -> Optional[str]:
    """Ask the installed Playwright where its Chromium is, and whether that file exists."""
    if shutil.which("node") is None:
        return None
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "spec.json"
        spec.write_text(json.dumps({"mode": "probe"}))
        try:
            subprocess.run(["node", str(RUNNER), str(spec), tmp], capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT))
            result = json.loads((Path(tmp) / "result.json").read_text())
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
    return result["executable"] if result.get("exists") else None


def probe_browser() -> dict:
    blockers = []
    if shutil.which("node") is None:
        blockers.append("MISSING_DEPENDENCY:node")
    if not (REPO_ROOT / "apps" / "web" / "node_modules" / "@playwright" / "test").exists():
        blockers.append("MISSING_DEPENDENCY:@playwright/test (apps/web node_modules)")
    executable = chromium_path() or (None if blockers else _playwright_chromium())
    if executable is None:
        blockers.append("MISSING_DEPENDENCY:chromium (no Playwright-managed or system Chromium found)")
    return {"available": not blockers, "blockers": blockers, "chromium": str(executable or "")}


def _run(spec: dict, out_dir: Path, timeout_s: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Empty means "Playwright's own managed Chromium".
    spec = {**spec, "executable_path": str(chromium_path() or "")}
    spec_path = out_dir / "spec.json"
    spec_path.write_text(json.dumps(spec))
    cmd, isolated = _isolated(["node", str(RUNNER), str(spec_path), str(out_dir)])
    start = time.monotonic()
    extra = {k: os.environ[k] for k in ("PLAYWRIGHT_BROWSERS_PATH",) if k in os.environ}
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=_env(extra), cwd=str(REPO_ROOT))
    result_path = out_dir / "result.json"
    result = json.loads(result_path.read_text()) if result_path.is_file() else {}
    return {"exit_code": proc.returncode, "wall_ms": int((time.monotonic() - start) * 1000), "network_isolated": isolated,
            "stderr_tail": proc.stderr[-2000:], "result": result, "command": cmd}


def capture_webgl(*, vertex: str, fragment: str, width: int, height: int, uniforms: Optional[dict] = None,
                  out_dir: Path, timeout_s: int = 120) -> dict:
    run = _run({"mode": "webgl", "vertex": vertex, "fragment": fragment, "width": width, "height": height,
                "uniforms": uniforms or {}}, out_dir, timeout_s)
    w = run["result"].get("webgl") or {}
    findings = []
    if run["exit_code"] != 0:
        findings.append(f"BROWSER_EXIT:{run['exit_code']}")
    if w.get("error"):
        findings.append(w["error"])
    compile_ok = bool(w.get("compile", {}).get("vertex", {}).get("ok")) and bool(w.get("compile", {}).get("fragment", {}).get("ok"))
    if w and not compile_ok:
        findings.append("SHADER_COMPILE_FAILED")
    if compile_ok and not w.get("link", {}).get("ok"):
        findings.append("PROGRAM_LINK_FAILED")
    px = w.get("pixels") or {}
    if compile_ok and px and (px.get("stddev", 0) < 1 or px.get("error")):
        findings.append("BLANK_OR_GL_ERROR_OUTPUT")
    if compile_ok and px and not (w.get("lost_flag") and w.get("restored_flag") and w.get("events") == ["lost", "restored"]):
        findings.append("CONTEXT_LOSS_NOT_HANDLED")
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    capture = out_dir / "webgl.png"
    return {**run, "status": "PASSED" if not findings and capture.is_file() else "FAILED", "findings": findings,
            "capture": str(capture) if capture.is_file() else None, "renderer": w.get("renderer"),
            "gl_version": w.get("version")}


def capture_svg_sizes(svg: str, *, sizes: Iterable[int] = (32, 128, 512), out_dir: Path, timeout_s: int = 120) -> dict:
    run = _run({"mode": "svg", "svg": svg, "sizes": list(sizes)}, out_dir, timeout_s)
    findings = []
    if run["exit_code"] != 0:
        findings.append(f"BROWSER_EXIT:{run['exit_code']}")
    for s in run["result"].get("sizes", []):
        if not s.get("complete") or s.get("error"):
            findings.append(f"SVG_NOT_DECODED_AT:{s['size']}")
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    captures = [str(out_dir / s["capture"]) for s in run["result"].get("sizes", []) if (out_dir / s["capture"]).is_file()]
    if len(captures) != len(list(sizes)):
        findings.append("MISSING_CAPTURE")
    return {**run, "status": "PASSED" if not findings else "FAILED", "findings": findings, "captures": captures}



def rasterize_svg(svg: str, *, width: int, height: int, out_dir: Path, timeout_s: int = 120) -> dict:
    """Exact-size PNG of an SVG, rendered by local Chromium (transparent where the SVG is)."""
    run = _run({"mode": "raster", "svg": svg, "width": width, "height": height}, out_dir, timeout_s)
    r = run["result"].get("raster") or {}
    capture = out_dir / "raster.png"
    findings = []
    if run["exit_code"] != 0:
        findings.append(f"BROWSER_EXIT:{run['exit_code']}")
    if not r.get("complete"):
        findings.append("SVG_NOT_DECODED")
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    ok = not findings and capture.is_file()
    return {**run, "status": "PASSED" if ok else "FAILED", "findings": findings, "capture": str(capture) if ok else None}


def render_svg_frames(frames: list[str], *, width: int, height: int, out_dir: Path, timeout_s: int = 600) -> dict:
    run = _run({"mode": "frames", "frames": frames, "width": width, "height": height}, out_dir, timeout_s)
    got = run["result"].get("frames") or []
    files = [str(out_dir / f["file"]) for f in got if f.get("complete") and (out_dir / f["file"]).is_file()]
    findings = [] if len(files) == len(frames) and run["exit_code"] == 0 else [f"FRAMES_RENDERED:{len(files)}/{len(frames)}"]
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    return {**run, "status": "PASSED" if not findings else "FAILED", "findings": findings, "files": files}


def run_experience(html: str, scenarios: list[dict], *, out_dir: Path, timeout_s: int = 300) -> dict:
    """Load a generated interface in local Chromium and execute scripted interaction scenarios."""
    run = _run({"mode": "experience", "html": html, "scenarios": scenarios}, out_dir, timeout_s)
    results = run["result"].get("scenarios") or []
    findings = []
    if run["exit_code"] != 0:
        findings.append(f"BROWSER_EXIT:{run['exit_code']}")
    if len(results) != len(scenarios):
        findings.append(f"SCENARIOS_RUN:{len(results)}/{len(scenarios)}")
    findings += [f"SCENARIO_FAILED:{r['id']}" for r in results if not r["passed"]]
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    return {**run, "status": "PASSED" if not findings else "FAILED", "findings": findings, "scenarios": results}

__all__ = ["capture_svg_sizes", "capture_webgl", "chromium_path", "probe_browser", "rasterize_svg", "render_svg_frames",
           "run_experience", "three_renderer_for"]
