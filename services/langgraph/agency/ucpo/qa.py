"""Browser verification of a built export, in the sandbox, with real Chromium.

``qa_runner.cjs`` does the browser work (route-fulfilled pages, axe-core, keyboard, reflow,
zoom, reduced motion, screenshots); this module turns its raw observations into typed
``CheckResult``s. Nothing is assumed: a check the runner did not produce is ``NOT_RUN``,
and a runner failure is ``BLOCKED``, never ``PASS``. Automated checks do not certify WCAG
conformance; the verification says so.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from services.langgraph.agency.foundry import psem

from .build import output_digest
from .contracts import BrowserVerification, CheckResult
from .sandbox import WEB_NODE_MODULES, Isolation, probe_isolation, wrap

RUNNER = Path(__file__).with_name("qa_runner.cjs")
VIEWPORTS = (320, 768, 1280)
RUNNER_TIMEOUT_S = 300
_HEX = {v.lower(): k for k, v in psem.PALETTE.items()}


def _browser_cache() -> Optional[str]:
    """Where Playwright's Chromium lives. The sandbox scrubs ``HOME``, so the default per-user cache
    that ``playwright install`` writes to must be passed explicitly or the runner cannot find it."""
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured:
        return configured
    if Path("/opt/pw-browsers").is_dir():
        return "/opt/pw-browsers"
    default = os.path.expanduser("~/.cache/ms-playwright")
    return default if os.path.isdir(default) else None


def _playwright_paths() -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return the module root, browser cache and exact package the runner must load."""
    for package in ("@playwright/test", "playwright"):
        for candidate in (Path("/opt/node-tools/node_modules"), WEB_NODE_MODULES):
            module = candidate / package
            if (module / "package.json").is_file():
                return str(candidate), _browser_cache(), str(module)
    return None, None, None


def axe_path() -> Optional[Path]:
    pkg = WEB_NODE_MODULES / "@axe-core" / "playwright"
    if not pkg.exists():
        return None
    candidate = pkg.resolve().parent.parent / "axe-core" / "axe.min.js"
    return candidate if candidate.is_file() else None


def _hex(css: str) -> Optional[str]:
    m = re.fullmatch(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)", css.strip())
    if not m or (m.group(4) is not None and float(m.group(4)) < 1):
        return None
    return "#" + "".join(f"{int(m.group(i)):02x}" for i in (1, 2, 3))


def colour_findings(colours: list[str]) -> list[str]:
    """Rendered colours that are not PSEM colours, or PSEM pairings PSEM forbids for their use."""
    out = []
    for row in colours:
        use, fg_css, bg_css, size, weight = row.split("|")
        fg, bg = _hex(fg_css), _hex(bg_css)
        fg_name, bg_name = _HEX.get(fg or ""), _HEX.get(bg or "")
        if not fg_name or not bg_name:
            out.append(f"non-PSEM colour {fg_css} on {bg_css}")
            continue
        if fg_name == bg_name:
            out.append(f"{fg_name} on itself")
            continue
        kind = "graphic" if use == "graphic" else (
            "large_text" if float(size) >= 24 or (float(size) >= 18.66 and int(weight) >= 700) else "text")
        try:
            psem.check_usage(fg_name, bg_name, kind)  # type: ignore[arg-type]
        except psem.PsemUsageError as exc:
            out.append(str(exc))
    return sorted(set(out))


def _check(check: str, ok: Optional[bool], detail: str, refs: tuple[str, ...], route: Optional[str] = None,
           viewport: Optional[str] = None, evidence: Optional[str] = None) -> CheckResult:
    result = "NOT_RUN" if ok is None else ("PASS" if ok else "FAIL")
    return CheckResult(check=check, route=route, viewport=viewport, result=result, detail=detail[:600], req_refs=refs,
                       evidence_ref=evidence)


def interpret(raw: dict, routes: list[str], shot_hashes: dict[str, str]) -> tuple[list[CheckResult], dict, tuple[str, ...]]:
    checks: list[CheckResult] = []
    evidence: dict[str, dict[str, list[str]]] = {}
    aborted: list[str] = []
    for route in routes:
        r = raw.get("routes", {}).get(route)
        if r is None:
            checks.append(_check("route_rendered", None, "runner produced no observation", (), route))
            continue
        dom = r.get("dom") or {}
        evidence[route] = {**dom.get("evidence", {}), "__title__": [dom.get("title", "")], "__lang__": [dom.get("lang", "")],
                           "__text__": [dom.get("text", "")]}
        checks.append(_check("http_status", r.get("status") == 200, f"status {r.get('status')}", (), route))
        violations = (r.get("axe") or {}).get("violations")
        checks.append(_check("axe", None if violations is None else not violations,
                             json.dumps(violations or [])[:600] or "no violations", ("req.a11y.automated",), route,
                             evidence=f"axe-core {(r.get('axe') or {}).get('version', '?')}"))
        heads = dom.get("headings") or []
        skips = [b for a, b in zip(heads, heads[1:]) if b > a + 1]
        checks.append(_check("headings", heads.count(1) == 1 and not skips and bool(heads) and heads[0] == 1,
                             f"levels {heads}", ("req.a11y.automated",), route))
        lm = dom.get("landmarks") or {}
        checks.append(_check("landmarks", all(lm.get(k, 0) >= 1 for k in ("banner", "navigation", "main", "contentinfo"))
                             and dom.get("unnamedNav", 1) == 0, json.dumps(lm), ("req.a11y.automated",), route))
        for vp in VIEWPORTS:
            o = (r.get("viewports") or {}).get(str(vp))
            checks.append(_check("reflow", None if o is None else not o["overflow"], json.dumps(o), ("req.responsive.reflow",),
                                 route, f"{vp}x900", shot_hashes.get(f"{route}@{vp}")))
        for name, key in (("text_zoom_200", "zoom_text_200"), ("page_zoom_200", "zoom_page_200")):
            o = r.get(key)
            checks.append(_check(name, None if o is None else not o["overflow"], json.dumps(o), ("req.text.zoom",), route))
        rm, dm = r.get("reduced_motion"), r.get("default_motion")
        checks.append(_check("reduced_motion", None if rm is None else (rm["animations"] == 0 and rm["slowCount"] == 0
                                                                          and rm["scrollBehavior"] == "auto"),
                             f"reduce={json.dumps(rm)}; default={json.dumps(dm)}", ("req.motion.reduced",), route))
        stops = r.get("keyboard")
        ok = None if stops is None else bool(stops) and "skip" in stops[0]["cls"] and all(s["outline"] or s["shadow"] for s in stops)
        checks.append(_check("keyboard_focus", ok, f"{len(stops or [])} stops; first={stops[0] if stops else None}",
                             ("req.keyboard.focus",), route))
        checks.append(_check("console_clean", not r.get("console"), json.dumps(r.get("console", []))[:600],
                             ("req.console.clean",), route))
        checks.append(_check("no_external_requests", not r.get("aborted"), json.dumps(r.get("aborted", [])),
                             ("req.network.none",), route))
        aborted += r.get("aborted", [])
        found = colour_findings(dom.get("colours") or [])
        checks.append(_check("psem_colours", None if not dom.get("colours") else not found,
                             "; ".join(found) or f"{len(dom.get('colours') or [])} pairings, all legal",
                             ("req.psem.colour",), route))
    return checks, evidence, tuple(sorted(set(aborted)))


def verify_build(out_dir: Path, *, routes: list[str], expected_output_hash: str,
                 isolation: Optional[Isolation] = None, evidence_dir: Optional[Path] = None) -> BrowserVerification:
    actual = output_digest(out_dir)[0] if out_dir.is_dir() else None
    base = {"build_output_hash": actual, "browser": {}}
    if actual != expected_output_hash:
        return BrowserVerification(status="BLOCKED", checks=(CheckResult(
            check="build_identity", result="BLOCKED", detail="export bytes differ from the build being verified"),), dom_evidence={},
            **base)
    iso = isolation or probe_isolation()
    node_path, browsers, playwright_module = _playwright_paths()
    axe = axe_path()
    missing = [n for n, v in (("isolation", iso.available), ("playwright", node_path), ("axe-core", axe)) if not v]
    if missing:
        return BrowserVerification(status="BLOCKED", checks=(CheckResult(
            check="qa_prerequisites", result="BLOCKED", detail=f"unavailable: {missing}; {list(iso.reasons)}"),), dom_evidence={},
            **base)
    with tempfile.TemporaryDirectory(prefix="amc-ucpo-qa-") as tmp:
        work = Path(tmp)
        ev = evidence_dir or (work / "evidence")
        ev.mkdir(parents=True, exist_ok=True)
        cfg = {"out_dir": str(out_dir), "routes": routes, "viewports": list(VIEWPORTS), "axe_path": str(axe),
               "playwright_module": playwright_module,
               "evidence_dir": str(ev), "result_path": str(work / "result.json")}
        (work / "config.json").write_text(json.dumps(cfg))
        env = {"NODE_PATH": node_path}
        if browsers:
            env["PLAYWRIGHT_BROWSERS_PATH"] = browsers
        argv = wrap([iso.node or "node", str(RUNNER), str(work / "config.json")], cwd=work, home=work, node=iso.node or "node",
                    timeout_s=RUNNER_TIMEOUT_S, extra_env=env)
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=RUNNER_TIMEOUT_S + 30)
            code, log = proc.returncode, proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as exc:
            code, log = 124, str(exc)
        if code != 0 or not (work / "result.json").exists():
            return BrowserVerification(status="BLOCKED", checks=(CheckResult(
                check="qa_runner", result="BLOCKED", detail=f"exit {code}: {log[-500:]}"),), dom_evidence={}, **base)
        raw = json.loads((work / "result.json").read_text())
        shots = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest() for k, v in raw.get("screenshots", {}).items()
                 if Path(v).is_file()}
    checks, evidence, aborted = interpret(raw, routes, shots)
    results = {c.result for c in checks}
    status = "FAILED" if "FAIL" in results else ("PASSED" if results == {"PASS"} else "BLOCKED")
    return BrowserVerification(status=status, build_output_hash=actual,
                               browser={**raw.get("browser", {}), "isolation": "unshare -rmn; repo read-only; env -i",
                                        "origin": "http://amc-preview.invalid (route-fulfilled from the export)"},
                               checks=tuple(checks), dom_evidence=evidence, screenshots=shots, blocked_requests=aborted)


__all__ = ["RUNNER", "VIEWPORTS", "axe_path", "colour_findings", "interpret", "verify_build"]
