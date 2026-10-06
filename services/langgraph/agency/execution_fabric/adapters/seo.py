"""SEO adapter: deterministic on-page checks over a supplied page set.

It "crawls" only the pages it is given (no network fetch): titles, meta
descriptions, a single h1, canonical links, image alternatives, language and
viewport, and whether internal links resolve within the set. Length ranges are
common editorial heuristics, configurable per call, not search-engine rules.

Search demand (volume, difficulty, SERP features) needs a search-data provider.
None is installed, so the report carries ``GAP_NO_SEARCH_PROVIDER`` and never
an estimated number.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from ..verifiers import Verdict, parse_dom

DEFAULT_RANGES = {"title": (10, 60), "description": (50, 160)}
SEARCH_GAP = "GAP_NO_SEARCH_PROVIDER"


def _page_findings(path: str, html: str, known: set[str], ranges: dict[str, tuple[int, int]]) -> list[dict[str, str]]:
    dom = parse_dom(html)
    out: list[dict[str, str]] = []

    def add(rule: str, severity: str, detail: str) -> None:
        out.append({"page": path, "rule": rule, "severity": severity, "detail": detail})

    titles = [text for tag, _, text in dom.text_by_tag if tag == "title"]
    lo, hi = ranges["title"]
    if not titles or not titles[0]:
        add("title", "error", "missing <title>")
    elif not lo <= len(titles[0]) <= hi:
        add("title", "warning", f"title length {len(titles[0])} outside {lo}-{hi}")
    desc = [a.get("content", "") for t, a in dom.elements if t == "meta" and a.get("name", "").lower() == "description"]
    lo, hi = ranges["description"]
    if not desc or not desc[0].strip():
        add("meta-description", "error", "missing meta description")
    elif not lo <= len(desc[0]) <= hi:
        add("meta-description", "warning", f"description length {len(desc[0])} outside {lo}-{hi}")
    h1 = [t for t in dom.tags if t == "h1"]
    if len(h1) != 1:
        add("h1", "error", f"expected exactly one <h1>, found {len(h1)}")
    if not any(t == "link" and "canonical" in a.get("rel", "").lower().split() for t, a in dom.elements):
        add("canonical", "warning", "no rel=canonical link")
    if not any(t == "html" and a.get("lang") for t, a in dom.elements):
        add("lang", "error", "<html> lacks lang")
    if not any(t == "meta" and a.get("name", "").lower() == "viewport" for t, a in dom.elements):
        add("viewport", "error", "no viewport meta")
    for tag, attrs in dom.elements:
        if tag == "img" and not attrs.get("alt", "").strip():
            add("img-alt", "error", f"image {attrs.get('src', '?')} has no alt text")
        if tag == "a" and attrs.get("href"):
            href = attrs["href"]
            parts = urlsplit(href)
            if parts.scheme or parts.netloc or href.startswith(("#", "mailto:", "tel:")):
                continue
            target = parts.path if parts.path.startswith("/") else "/" + parts.path
            if target not in known:
                add("broken-internal-link", "error", f"{href} does not resolve within the supplied page set")
    return out


def seo_audit(payload: dict[str, Any]) -> dict[str, Any]:
    pages = payload.get("inputs", {}).get("pages")
    if not isinstance(pages, dict) or not pages:
        raise ValueError("inputs.pages must map paths to HTML")
    ranges = {**DEFAULT_RANGES, **{k: tuple(v) for k, v in (payload.get("inputs", {}).get("ranges") or {}).items()}}
    known = {p if p.startswith("/") else "/" + p for p in pages}
    findings = [f for path in sorted(pages) for f in _page_findings(path, pages[path], known, ranges)]
    report = {
        "kind": "seo_audit",
        "pages": sorted(pages),
        "findings": findings,
        "passed": not any(f["severity"] == "error" for f in findings),
        "search_demand": {"status": SEARCH_GAP, "detail": "no search-data provider is installed; no volumes are estimated"},
        "heuristic_ranges": {k: list(v) for k, v in sorted(ranges.items())},
    }
    return {"content": json.dumps(report, sort_keys=True, indent=2), "mime_type": "application/json", "subtype": "seo_audit"}


def search_volume(payload: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - never dispatched
    raise RuntimeError(SEARCH_GAP)


def validate_no_fabricated_demand(output: dict[str, Any], payload: dict[str, Any]) -> Verdict:
    report = json.loads(output["content"])
    demand = report.get("search_demand", {})
    ok = demand.get("status") == SEARCH_GAP and set(demand) <= {"status", "detail"}
    return Verdict("seo_no_fabricated_demand", ok,
                   "search demand reported as a provider gap" if ok else "search demand carries values without a provider")
