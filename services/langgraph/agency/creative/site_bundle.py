"""Deterministic website bundle for a sealed landing-page artifact.

``build_site_bundle`` derives publishable files from one ``ArtifactIR`` that already
carries a ``landing_page``:

* ``index.html``: the existing ``render_landing_html`` output, with a JSON-LD block
  (WebPage and Organization) inserted before ``</head>``.
* ``robots.txt``: allows crawling and, when a site URL is given, points at the sitemap.
* ``sitemap.xml``: a single-URL sitemap, only when the site URL is an absolute https URL.
* ``bundle.json``: a manifest with the artifact hash, a SHA-256 per file, and every
  omission with its reason.

Nothing here invents content. Structured data uses only the brand name, headline,
subheadline, locale, and the site URL. FAQPage is omitted because the verified FAQ copy
has no question/answer structure. Search volumes are never emitted: keyword data needs
a reviewed provider and is reported as ``NOT_MEASURED``.

The bundle is local output. It does not publish, and publication stays governed by the
existing publishing adapters and their approval gates.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from typing import Any, Iterable
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as _xml_escape

from .ir import ArtifactIR
from .landing import render_landing_html

BUNDLE_VERSION = "amc-site-bundle/v1"
KEYWORD_STATUS = "NOT_MEASURED"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HEAD_CLOSE = "</head>"


class SiteBundleError(ValueError):
    """The artifact cannot produce a truthful website bundle."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _valid_site_url(site_url: str | None) -> str | None:
    """Return a normalised https origin+path, or None. Credentials, queries and fragments are refused."""
    if not site_url:
        return None
    parts = urlsplit(site_url.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    if parts.query or parts.fragment:
        return None
    return f"https://{parts.netloc}{parts.path.rstrip('/')}"


def _json_ld_text(nodes: list[dict[str, Any]]) -> str:
    """Serialise JSON-LD so no sequence can close the surrounding script element or open markup."""
    payload = json.dumps(nodes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _json_ld_nodes(artifact: ArtifactIR, site_url: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    page = artifact.landing_page
    brand = str(artifact.brand_bindings.get("brand_name", "")).strip()
    if not brand:
        raise SiteBundleError("brand_name is required for Organization structured data")
    omitted: list[str] = []
    web_page: dict[str, Any] = {"@context": "https://schema.org", "@type": "WebPage",
                                "name": page.headline, "inLanguage": page.locale}
    if page.subheadline:
        web_page["description"] = page.subheadline
    if site_url:
        web_page["url"] = site_url + "/"
    organization: dict[str, Any] = {"@context": "https://schema.org", "@type": "Organization", "name": brand}
    if site_url:
        organization["url"] = site_url + "/"
    else:
        omitted.append("Organization.url: no valid https site URL supplied")
    if any(s.kind.value == "faq" for s in page.sections):
        omitted.append("FAQPage: verified FAQ copy has no question/answer structure")
    return [web_page, organization], omitted


def _insert_json_ld(markup: str, nodes: list[dict[str, Any]]) -> str:
    if markup.count(_HEAD_CLOSE) != 1:
        raise SiteBundleError("rendered page must contain exactly one </head>")
    block = f'<script type="application/ld+json">{_json_ld_text(nodes)}</script>'
    return markup.replace(_HEAD_CLOSE, block + _HEAD_CLOSE)


def _robots(site_url: str | None) -> str:
    lines = ["User-agent: *", "Allow: /"]
    if site_url:
        lines.append(f"Sitemap: {site_url}/sitemap.xml")
    return "\n".join(lines) + "\n"


def _sitemap(site_url: str, lastmod: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>{_xml_escape(site_url + '/')}</loc><lastmod>{lastmod}</lastmod></url>\n"
            "</urlset>\n")


def build_site_bundle(artifact: ArtifactIR, *, requirements: Iterable[str] = (), site_url: str | None = None,
                      lastmod: str | None = None) -> dict[str, Any]:
    """Build the website files for one landing artifact. Pure and deterministic for equal inputs."""
    if artifact.landing_page is None:
        raise SiteBundleError("site bundles need a landing_page artifact")
    if lastmod is not None and not (_DATE.match(lastmod) and _is_real_date(lastmod)):
        raise SiteBundleError("lastmod must be a real YYYY-MM-DD date")
    origin = _valid_site_url(site_url)
    nodes, omitted = _json_ld_nodes(artifact, origin)
    index_html = _insert_json_ld(render_landing_html(artifact, requirements), nodes)
    files: dict[str, str] = {"index.html": index_html, "robots.txt": _robots(origin)}
    if origin and lastmod:
        files["sitemap.xml"] = _sitemap(origin, lastmod)
    else:
        omitted.append("sitemap.xml: needs a valid https site URL and a lastmod date")
    manifest = {
        "bundle_version": BUNDLE_VERSION,
        "artifact_id": artifact.artifact_id,
        "artifact_hash": artifact.hash,
        "files": {name: {"sha256": _sha256(body), "bytes": len(body.encode("utf-8"))}
                  for name, body in sorted(files.items())},
        "omitted": sorted(omitted),
        "keywords": {"status": KEYWORD_STATUS, "reason": "no reviewed keyword provider is configured"},
    }
    files["bundle.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    return {"files": dict(sorted(files.items())), "manifest": manifest}


def _is_real_date(value: str) -> bool:
    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def verify_site_bundle(bundle: dict[str, Any]) -> list[str]:
    """Re-read every file and return a list of problems (empty means the bundle checks out)."""
    problems: list[str] = []
    files, manifest = bundle["files"], bundle["manifest"]
    for name, meta in manifest["files"].items():
        body = files.get(name)
        if body is None:
            problems.append(f"missing file: {name}")
        elif _sha256(body) != meta["sha256"]:
            problems.append(f"hash mismatch: {name}")
    html_text = files.get("index.html", "")
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_text, flags=re.S):
        try:
            nodes = json.loads(block)
        except json.JSONDecodeError:
            problems.append("JSON-LD does not parse")
            continue
        for node in nodes:
            if node.get("@context") != "https://schema.org" or "@type" not in node:
                problems.append("JSON-LD node lacks @context or @type")
    if "sitemap.xml" in files:
        import xml.etree.ElementTree as ET

        try:
            ET.fromstring(files["sitemap.xml"].split("?>", 1)[1])
        except ET.ParseError:
            problems.append("sitemap.xml does not parse")
    return problems
