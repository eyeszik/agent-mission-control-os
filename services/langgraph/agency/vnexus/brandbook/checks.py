"""Page checks: measured layout facts in, check results out. A check that could not run is NOT_RUN, never PASSED."""

from __future__ import annotations

import re
from typing import Any

from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

from .assets import AssetKind, MarkAsset
from .compiler import PagePackage
from .fields import UNRESOLVED_TOKEN
from .manifest import Mode

VALIDATOR_VERSION = "amc-brandbook-checks/1.0.0"


def _c(page_id: str, check: str, status: str, detail: str, *, severity: str = "ERROR") -> dict[str, Any]:
    return {"page_id": page_id, "check": check, "status": status, "detail": detail[:400], "severity": severity}


def static_checks(page: PagePackage, sections: list[tuple[str, str]], *, mode: Mode, palette: dict[str, str],
                  neutral: bool) -> list[dict[str, Any]]:
    """Checks that need no browser: unresolved tokens, text contrast of the page colours, labelled status."""
    pid = page.page_id
    out = []
    html = "".join(s for _, s in sections)
    text = re.sub(r"<[^>]+>", " ", html)
    tokens = UNRESOLVED_TOKEN.findall(text)
    if mode is Mode.PRODUCTION:
        out.append(_c(pid, "no_unresolved_tokens", "FAILED" if tokens or page.gaps else "PASSED",
                      f"unresolved: {tokens[:5]}; gaps: {[g.path for g in page.gaps][:5]}" if tokens or page.gaps else "none"))
    else:
        out.append(_c(pid, "no_unresolved_tokens", "PASSED" if not tokens else "FAILED",
                      f"labelled gaps: {len(page.gaps)}; raw tokens: {tokens[:5]}", severity="WARNING"))
    ratio = wcag_contrast_ratio(palette["ink"], palette["paper"])
    out.append(_c(pid, "text_contrast", "PASSED" if ratio >= 4.5 else "FAILED",
                  f"body text {palette['ink']} on {palette['paper']} = {ratio}:1 (WCAG 2.2 AA 4.5:1)"
                  + ("; neutral rendering colours (no approved palette)" if neutral else "")))
    return out


def measured_checks(page: PagePackage, measured: list[dict[str, Any]], *, mark: MarkAsset, total: int) -> list[dict[str, Any]]:
    """Checks from the Chromium layout measurement of every part of one page."""
    pid = page.page_id
    if not measured:
        return [_c(pid, name, "NOT_RUN", "page was not measured") for name in
                ("no_overflow", "exact_copy", "min_font", "no_overlap", "mark_continuity", "status_labelled", "footer")]
    out = []
    over = [f"{m['id']}: {m['overflow_count']} element(s) {m['overflow'][:3]}" for m in measured if m["overflow_count"]]
    clipped = [f"{m['id']}: {m['clipped'][:3]}" for m in measured if m["clipped"]]
    out.append(_c(pid, "no_overflow", "FAILED" if over or clipped else "PASSED", "; ".join(over + clipped) or
                  f"{len(measured)} part(s) inside the page body"))
    rendered = {k: v for m in measured for k, v in m["copies"].items()}
    missing = [c["copy_id"] for c in page.copy_blocks if c["copy_id"] not in rendered]
    wrong = [c["copy_id"] for c in page.copy_blocks if c["copy_id"] in rendered and rendered[c["copy_id"]] != c["text"]]
    out.append(_c(pid, "exact_copy", "FAILED" if missing or wrong else "PASSED",
                  f"missing {missing[:5]}, altered {wrong[:5]}" if missing or wrong else f"{len(page.copy_blocks)} copy element(s) verbatim"))
    small = [s for m in measured for s in m["small"]]
    out.append(_c(pid, "min_font", "FAILED" if small else "PASSED", f"below minimum: {small[:5]}" if small else "no text below the minimum"))
    overlaps = [o for m in measured for o in m["overlaps"]]
    out.append(_c(pid, "no_overlap", "FAILED" if overlaps else "PASSED", f"overlapping blocks: {overlaps[:3]}" if overlaps else "no overlapping blocks"))
    marks = [x for m in measured for x in m["marks"]]
    masters = [x for x in marks if not x["misuse"]]
    if mark.kind is AssetKind.MISSING:
        cont = ("PASSED", "no master to place; none drawn") if not marks else ("FAILED", "a mark was drawn without an approved master")
    else:
        bad = [x for x in marks if x["sha"] != mark.sha256 or not x["loaded"]]
        cont = ("FAILED", f"{len(bad)} placement(s) not the canonical master or not loaded") if bad else \
            ("PASSED", f"{len(masters)} master placement(s), {len(marks) - len(masters)} labelled misuse view(s), one source sha256 {mark.sha256[:16]}")
    out.append(_c(pid, "mark_continuity", *cont))
    out.append(_c(pid, "status_labelled", "PASSED" if all(m["status_labelled"] for m in measured) else "FAILED",
                  "every status and gap has a text label (no colour-only meaning)"))
    footers_ok = all(f"Page {page.order:02d} of {total:02d}" in m["footer"] for m in measured)
    out.append(_c(pid, "footer", "PASSED" if footers_ok else "FAILED", f"footer reads page {page.order:02d} of {total:02d}"))
    return out


def summarize(checks: list[dict[str, Any]]) -> dict[str, int]:
    out = {"PASSED": 0, "FAILED": 0, "NOT_RUN": 0, "INCONCLUSIVE": 0}
    for c in checks:
        out[c["status"]] = out.get(c["status"], 0) + 1
    return out


def blocking(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in checks if c["status"] in ("FAILED", "NOT_RUN") and c["severity"] == "ERROR"]


def measurement_for(page_keys: list[str], pages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for m in pages:
        base = m["id"].split("-")[0]
        by.setdefault(base, []).append(m)
    return {k: by.get(k, []) for k in page_keys}


__all__ = ["VALIDATOR_VERSION", "blocking", "measured_checks", "measurement_for", "static_checks", "summarize"]

