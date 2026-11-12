"""R3/R4 browser verification: render in a real local Chromium, read back what it did.

``three_renderer_for`` answers the R3 architecture question without guessing:
TSL/node-material scenes need ``WebGPURenderer``; legacy ``ShaderMaterial``,
``onBeforeCompile`` and ``EffectComposer`` scenes need ``WebGLRenderer``. A
scene mixing both is BLOCKED, because the WebGPU renderer's WebGL2 backend
does not translate legacy GLSL shader hooks.

``capture_webgl`` / ``capture_svg_sizes`` drive ``browser_runner.cjs`` in
the same fail-closed minimal chroot and network namespace used by UCPO. Every
non-``data:`` request is also aborted. They return the browser's own observations:
shader compile and link logs, pixel statistics, context loss/restore events and
PNG captures. The boundary is not a substitute for seccomp/cgroup quotas or an
independent hostile-multitenant review.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

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


def _repo_playwright_chromium() -> Optional[Path]:
    """This repository's own Playwright Chromium, if it is installed.

    Preferred over a system browser on purpose. A distro package (for example
    Debian's /usr/bin/chromium) is a single binary with no chrome-headless-shell
    beside it, and printing through it fails or hangs inside the sandbox while
    Playwright's own install ships both binaries from one version. Picking the
    system browser therefore silently selected the one configuration that
    cannot print. PLAYWRIGHT_BROWSERS_PATH, when set, is honoured by asking
    Playwright rather than by guessing the cache layout.
    """
    import subprocess
    import tempfile

    if shutil.which("node") is None:
        return None
    web_app = REPO_ROOT / "apps" / "web"
    if not (web_app / "node_modules" / "@playwright" / "test").exists():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "spec.json"
        spec.write_text(json.dumps({"mode": "probe"}))
        try:
            subprocess.run(["node", str(RUNNER), str(spec), tmp], capture_output=True, text=True,
                           timeout=90, cwd=str(REPO_ROOT))
            result = json.loads((Path(tmp) / "result.json").read_text())
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
    executable = result.get("executable")
    return Path(executable) if result.get("exists") and executable else None


def _playwright_cache_chromium() -> Optional[Path]:
    """Pick a browser from PLAYWRIGHT_BROWSERS_PATH that can actually print.

    Spawning node to ask Playwright works on a developer machine but was not
    reliable inside the CI job, where the probe returned nothing and resolution
    fell through to /usr/bin/chromium -- the one binary that cannot print.
    The cache directory is authoritative and needs no interpreter, so prefer
    it. A revision is chosen only when *both* the browser and its
    chrome-headless-shell are present, because a browser without its shell is
    precisely the configuration that fails.
    """
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if not env:
        return None
    root = Path(env)
    if not root.is_dir():
        return None
    candidates: list[tuple[int, Path]] = []
    for shell_dir in sorted(root.glob("chromium_headless_shell-*")):
        revision = shell_dir.name[len("chromium_headless_shell-"):]
        if not revision.isdigit():
            continue
        browser_dir = root / f"chromium-{revision}"
        if not browser_dir.is_dir():
            continue
        if not any(shell_dir.glob("*/headless_shell")) and not any(shell_dir.glob("*/chrome-headless-shell")):
            continue
        for executable in browser_dir.glob("*/chrome"):
            if executable.is_file():
                candidates.append((int(revision), executable))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def chromium_path() -> Optional[Path]:
    for candidate in (DEFAULT_CHROMIUM, _playwright_cache_chromium(), _repo_playwright_chromium(),
                      *(Path(p) for p in (shutil.which("chromium"), shutil.which("chromium-browser")) if p)):
        if candidate is not None and Path(candidate).is_file():
            return Path(candidate)
    return None


def headless_shell_for(executable: Optional[Path]) -> Optional[Path]:
    """The chrome-headless-shell for the same Playwright revision, if installed.

    Playwright prefers it for headless work, and it is the only binary whose
    print path avoids the compositor that fails inside the sandbox. Resolved
    by revision rather than by directory: a full build is
    ``.../chromium-<rev>/chrome-linux*/chrome`` and its shell is
    ``.../chromium_headless_shell-<rev>/chrome-headless-shell-linux*/chrome-headless-shell``.
    Matching the *same* revision matters -- a shell from a different build is a
    different browser, and mixing them would reintroduce the bug this fixes.
    Never assumed to exist: a chromium-only install returns None and the caller
    keeps the full browser.
    """
    if not executable:
        return None
    executable = Path(executable)
    directory = executable.parent
    # Same directory, for layouts that ship the pair together.
    for name in ("headless_shell", "chrome-headless-shell", "headless-shell"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    # Revision-matched sibling install.
    revision = None
    for part in reversed(executable.parts):
        if part.startswith("chromium-") and part[len("chromium-"):].isdigit():
            revision = part[len("chromium-"):]
            break
    cache_roots = [directory.parent, directory.parent.parent]
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and Path(env).is_dir():
        cache_roots.insert(0, Path(env))
    for root in cache_roots:
        pattern = f"chromium_headless_shell-{revision}" if revision else "chromium_headless_shell-*"
        for shell_dir in sorted(root.glob(pattern)):
            for inner in sorted(p for p in shell_dir.iterdir() if p.is_dir()):
                for name in ("headless_shell", "chrome-headless-shell"):
                    candidate = inner / name
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
    from services.langgraph.agency.ucpo.sandbox import probe_isolation

    isolation = probe_isolation()
    if not isolation.available:
        blockers.append("BLOCKED_ISOLATION:" + "; ".join(isolation.reasons))
    return {"available": not blockers, "blockers": blockers, "chromium": str(executable or "")}


def _browser_runtime_paths(executable: Path) -> tuple[tuple[Path, ...], dict[str, str]]:
    """Mount browser runtime inputs only, never an arbitrary browser parent/home."""
    executable = executable.absolute()
    parent = executable.parent
    paths = [executable]
    for pattern in ("lib*.so", "lib*.so.*"):
        paths.extend(p for p in parent.glob(pattern) if p.is_file())
    for name in ("icudtl.dat", "resources.pak", "chrome_100_percent.pak", "chrome_200_percent.pak",
                 "v8_context_snapshot.bin", "snapshot_blob.bin", "vk_swiftshader_icd.json", "locales", "resources", "swiftshader"):
        candidate = parent / name
        if candidate.exists():
            paths.append(candidate)
    lib = parent / "lib"
    if lib.is_dir():
        for pattern in ("lib*.so", "lib*.so.*", "lib*.chk"):
            paths.extend(p for p in lib.glob(pattern) if p.is_file())
    extra = {"LD_LIBRARY_PATH": str(lib)} if lib.is_dir() else {}
    return tuple(dict.fromkeys(paths)), extra


_OUTPUT_NAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,159}\.(?:png|pdf)$")


def _expected_outputs(spec: dict, result: dict) -> set[str]:
    """Only copy declared, leaf-name outputs; browser content never selects a host path."""
    mode = spec.get("mode")
    if mode == "webgl":
        names = {"webgl.png"}
    elif mode == "raster":
        names = {"raster.png"}
    elif mode == "pdf":
        names = {"document.pdf"}
    elif mode == "svg":
        names = {f"svg-{size}.png" for size in spec.get("sizes", [])}
    elif mode == "frames":
        names = {f"frame_{i + 1:04d}.png" for i in range(len(spec.get("frames", [])))}
    elif mode == "layout":
        names = set((result.get("captures") or {}).values()) if spec.get("capture") else set()
    elif mode == "experience":
        names = {f"{s['id']}.png" for s in spec.get("scenarios", []) if s.get("capture")}
    else:
        names = set()
    return {name for name in names if isinstance(name, str) and _OUTPUT_NAME.fullmatch(name)}


def _run(spec: dict, out_dir: Path, timeout_s: int) -> dict:
    from services.langgraph.agency.ucpo.sandbox import probe_isolation, wrap

    out_dir = out_dir.absolute()
    out_dir.mkdir(parents=True, exist_ok=True)
    isolation = probe_isolation()
    executable = chromium_path() or _playwright_chromium()
    if not isolation.available or not executable:
        reasons = list(isolation.reasons) + ([] if executable else ["chromium not found"])
        return {"exit_code": None, "wall_ms": 0, "network_isolated": False, "output_files": [],
                "stderr_tail": "BLOCKED_ISOLATION_OR_BROWSER: " + "; ".join(reasons), "result": {}, "command": []}
    executable = Path(executable).absolute()
    shell = headless_shell_for(executable)
    spec = {**spec, "executable_path": str(executable)}
    if shell is not None:
        spec["headless_shell_path"] = str(shell)
    browser_paths, extra = _browser_runtime_paths(executable)
    if shell is not None:
        # The shell is a separate file outside the browser's own directory; it
        # must be bind-mounted or the print process cannot exec it.
        browser_paths = tuple(dict.fromkeys((*browser_paths, shell)))
    start = time.monotonic()
    # Never mount the caller's output directory: it can contain other client data.
    # Reopen only declared regular outputs from a fresh scratch directory.
    with tempfile.TemporaryDirectory(prefix="amc-visual-browser-") as tmp:
        work = Path(tmp)
        spec_path = work / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        cmd = wrap([isolation.node or "node", str(RUNNER), str(spec_path), str(work)], cwd=work, home=work,
                   node=isolation.node or "node", timeout_s=timeout_s, extra_env=extra,
                   readonly_paths=(RUNNER, *browser_paths))
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"exit_code": None, "wall_ms": int((time.monotonic() - start) * 1000), "network_isolated": False,
                    "stderr_tail": type(exc).__name__, "result": {}, "command": cmd, "output_files": []}
        result_path = work / "result.json"
        if proc.returncode != 0 and not result_path.is_file():
            return {"exit_code": proc.returncode, "wall_ms": int((time.monotonic() - start) * 1000),
                    "network_isolated": False, "stderr_tail": (proc.stderr or proc.stdout)[-2000:], "result": {},
                    "command": cmd, "output_files": []}
        try:
            if result_path.is_symlink() or not result_path.is_file() or result_path.stat().st_size > 8_000_000:
                raise ValueError("missing or invalid result.json")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(result, dict):
                raise ValueError("result.json must contain an object")
            copied: list[str] = []
            if proc.returncode == 0:
                for name in sorted(_expected_outputs(spec, result)):
                    src = work / name
                    if src.is_symlink() or not src.is_file() or src.stat().st_size > 256 * 1024 * 1024:
                        continue
                    # Atomic replacement does not follow a pre-existing output symlink.
                    with tempfile.NamedTemporaryFile(dir=out_dir, prefix=".amc-copy-", delete=False) as dest:
                        temporary = Path(dest.name)
                        try:
                            with src.open("rb") as stream:
                                shutil.copyfileobj(stream, dest)
                        except BaseException:
                            temporary.unlink(missing_ok=True)
                            raise
                    try:
                        os.replace(temporary, out_dir / name)
                    finally:
                        temporary.unlink(missing_ok=True)
                    copied.append(name)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return {"exit_code": None, "wall_ms": int((time.monotonic() - start) * 1000), "network_isolated": False,
                    "stderr_tail": f"BROWSER_RESULT_INVALID: {type(exc).__name__}: {exc}", "result": {},
                    "command": cmd, "output_files": []}
        return {"exit_code": proc.returncode, "wall_ms": int((time.monotonic() - start) * 1000),
                "network_isolated": proc.returncode == 0, "stderr_tail": proc.stderr[-2000:], "result": result,
                "command": cmd, "output_files": copied}


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
    if not compile_ok:
        findings.append("SHADER_COMPILE_FAILED")
    if compile_ok and not w.get("link", {}).get("ok"):
        findings.append("PROGRAM_LINK_FAILED")
    px = w.get("pixels") or {}
    if compile_ok and (not px or px.get("stddev", 0) < 1 or px.get("error")):
        findings.append("BLANK_OR_GL_ERROR_OUTPUT")
    if compile_ok and not (w.get("lost_flag") and w.get("restored_flag") and w.get("events") == ["lost", "restored"]):
        findings.append("CONTEXT_LOSS_NOT_HANDLED")
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    capture = out_dir / "webgl.png"
    if "webgl.png" not in run["output_files"]:
        findings.append("MISSING_CAPTURE")
    return {**run, "status": "PASSED" if not findings else "FAILED", "findings": findings,
            "capture": str(capture) if not findings else None, "renderer": w.get("renderer"),
            "gl_version": w.get("version")}


def capture_svg_sizes(svg: str, *, sizes: Iterable[int] = (32, 128, 512), out_dir: Path, timeout_s: int = 120) -> dict:
    requested = list(sizes)
    run = _run({"mode": "svg", "svg": svg, "sizes": requested}, out_dir, timeout_s)
    findings = []
    if run["exit_code"] != 0:
        findings.append(f"BROWSER_EXIT:{run['exit_code']}")
    observations = run["result"].get("sizes", [])
    for s in observations:
        if not s.get("complete") or s.get("error"):
            findings.append(f"SVG_NOT_DECODED_AT:{s.get('size')}")
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    if not requested or [s.get("size") for s in observations] != requested:
        findings.append("MISSING_SIZE_OBSERVATION")
    captures = [str(out_dir / s["capture"]) for s in observations
                if s.get("capture") == f"svg-{s.get('size')}.png" and s["capture"] in run["output_files"]]
    if len(captures) != len(requested):
        findings.append("MISSING_CAPTURE")
    return {**run, "status": "PASSED" if not findings else "FAILED", "findings": findings, "captures": captures}



def measure_svg_text(elements: list[dict], *, width: int, height: int, margin: float, out_dir: Path, timeout_s: int = 120) -> dict:
    """Measure text node bounding boxes in isolated Chromium, without parsing markup."""
    if not (1 <= width <= 4096 and 1 <= height <= 4096 and 0 <= margin < 0.5 and len(elements) <= 100):
        return {"status": "NOT_RUN", "reason": "invalid text layout bounds"}
    if any(not isinstance(e.get("text"), str) or len(e["text"]) > 200 for e in elements):
        return {"status": "NOT_RUN", "reason": "invalid text layout content"}
    run = _run({"mode": "text_layout", "width": width, "height": height, "margin": margin, "elements": elements},
               out_dir, timeout_s)
    measured = run["result"].get("text_layout") or {}
    boxes, outside, overlaps = measured.get("boxes"), measured.get("outside"), measured.get("overlaps")
    if (run["exit_code"] != 0 or run["result"].get("blocked_requests") or not isinstance(boxes, list)
            or len(boxes) != len(elements) or not isinstance(outside, list) or not isinstance(overlaps, list)):
        return {"status": "NOT_RUN", "reason": "isolated browser text measurement unavailable or invalid"}
    return {"status": "MEASURED", "boxes": boxes, "outside": outside, "overlaps": overlaps,
            "browser_version": run["result"].get("browser_version")}


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
    if "raster.png" not in run["output_files"]:
        findings.append("MISSING_CAPTURE")
    ok = not findings
    return {**run, "status": "PASSED" if ok else "FAILED", "findings": findings, "capture": str(capture) if ok else None}


def render_svg_frames(frames: list[str], *, width: int, height: int, out_dir: Path, timeout_s: int = 600) -> dict:
    run = _run({"mode": "frames", "frames": frames, "width": width, "height": height}, out_dir, timeout_s)
    got = run["result"].get("frames") or []
    expected = [f"frame_{i + 1:04d}.png" for i in range(len(frames))]
    files = [str(out_dir / f["file"]) for f, name in zip(got, expected)
             if f.get("complete") and f.get("file") == name and name in run["output_files"]]
    findings = [] if frames and len(got) == len(expected) and len(files) == len(expected) and run["exit_code"] == 0 \
        else [f"FRAMES_RENDERED:{len(files)}/{len(frames)}"]
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    return {**run, "status": "PASSED" if not findings else "FAILED", "findings": findings, "files": files}


def render_pdf(html: str, *, width_px: int, height_px: int, out_dir: Path, timeout_s: int = 120) -> dict:
    """A vector PDF printed by local Chromium from self-contained HTML (remote requests are blocked)."""
    run = _run({"mode": "pdf", "html": html, "width_px": width_px, "height_px": height_px}, out_dir, timeout_s)
    capture = out_dir / "document.pdf"
    findings = []
    if run["exit_code"] != 0:
        findings.append(f"BROWSER_EXIT:{run['exit_code']}")
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    if "document.pdf" not in run["output_files"] or not capture.read_bytes().startswith(b"%PDF-"):
        findings.append("PDF_NOT_WRITTEN")
    # The runner reports its own print fault. Surfacing it here is the
    # difference between "the PDF is missing" and why it is missing, and the
    # caller's reason string is what an operator actually reads.
    if run["result"].get("pdf_err"):
        findings.append(f"PRINT_FAILED:{run['result']['pdf_err']}"[:300])
    ok = not findings
    return {**run, "status": "PASSED" if ok else "FAILED", "findings": findings, "capture": str(capture) if ok else None}


def measure_layout(html: str, *, width: int, height: int, out_dir: Path, capture: bool = False, min_font_px: int = 10,
                   timeout_s: int = 180) -> dict:
    """Measure every ``[data-page]`` section of self-contained HTML in local Chromium (remote requests are blocked):
    overflow beyond the page body, clipped and too-small text, overlapping blocks, rendered copy and placed marks.
    With ``capture`` each section is also screenshotted (a raster preview, never the editable source)."""
    run = _run({"mode": "layout", "html": html, "width": width, "height": height, "capture": capture, "min_font_px": min_font_px},
               out_dir, timeout_s)
    findings = []
    if run["exit_code"] != 0:
        findings.append(f"BROWSER_EXIT:{run['exit_code']}")
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    pages = run["result"].get("layout")
    if pages is None:
        findings.append("LAYOUT_NOT_MEASURED")
    captures = run["result"].get("captures") or {}
    if capture and (len(captures) != len(pages or []) or any(name not in run["output_files"] for name in captures.values())):
        findings.append("MISSING_CAPTURE")
    return {**run, "status": "PASSED" if not findings else "FAILED", "findings": findings, "pages": pages or [],
            "captures": captures}


def run_experience(html: str, scenarios: list[dict], *, out_dir: Path, timeout_s: int = 300) -> dict:
    """Load a generated interface in local Chromium and execute scripted interaction scenarios."""
    run = _run({"mode": "experience", "html": html, "scenarios": scenarios}, out_dir, timeout_s)
    results = run["result"].get("scenarios") or []
    findings = []
    if run["exit_code"] != 0:
        findings.append(f"BROWSER_EXIT:{run['exit_code']}")
    if len(results) != len(scenarios) or [r.get("id") for r in results] != [s.get("id") for s in scenarios]:
        findings.append(f"SCENARIOS_RUN:{len(results)}/{len(scenarios)}")
    findings += [f"SCENARIO_FAILED:{r['id']}" for r in results if not r["passed"]]
    if any(f"{s['id']}.png" not in run["output_files"] for s in scenarios if s.get("capture")):
        findings.append("MISSING_CAPTURE")
    if run["result"].get("blocked_requests"):
        findings.append("REMOTE_REQUEST_ATTEMPTED")
    return {**run, "status": "PASSED" if not findings else "FAILED", "findings": findings, "scenarios": results}

__all__ = ["capture_svg_sizes", "capture_webgl", "chromium_path", "measure_layout", "probe_browser", "render_pdf", "rasterize_svg", "render_svg_frames",
           "run_experience", "three_renderer_for"]
