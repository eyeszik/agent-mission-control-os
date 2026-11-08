"""Website bundle for a sealed landing artifact: JSON-LD, sitemap, robots, hashes, truthfulness."""

from __future__ import annotations

import copy
import json
import re
import xml.etree.ElementTree as ET

import pytest

from services.langgraph.agency.creative import site_bundle as sb
from services.langgraph.agency.creative.ir import ArtifactIR, seal_artifact
from services.langgraph.agency.creative.landing import generate_landing
from services.langgraph.agency.creative.mission import compile_mission
from services.langgraph.agency.creative.runtime import DEFAULT_CONCEPT
from services.langgraph.tests.test_creative_runtime import SAMPLE

SITE = "https://example.com/studio"
LASTMOD = "2026-11-08"


@pytest.fixture(scope="module")
def artifact() -> ArtifactIR:
    mission = compile_mission({k: v for k, v in SAMPLE.items() if k != "brief_text"}, run_id="site").mission
    return generate_landing(mission, DEFAULT_CONCEPT, candidate_id="site-1")


def _ld_nodes(html: str) -> list[dict]:
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, flags=re.S)
    assert len(blocks) == 1
    return json.loads(blocks[0])


def test_bundle_contains_the_expected_files_and_manifest(artifact):
    bundle = sb.build_site_bundle(artifact, site_url=SITE, lastmod=LASTMOD)
    assert set(bundle["files"]) == {"bundle.json", "index.html", "robots.txt", "sitemap.xml"}
    assert bundle["manifest"]["artifact_hash"] == artifact.hash
    assert sb.verify_site_bundle(bundle) == []


def test_json_ld_carries_only_sourced_facts(artifact):
    bundle = sb.build_site_bundle(artifact, site_url=SITE, lastmod=LASTMOD)
    web_page, organization = _ld_nodes(bundle["files"]["index.html"])
    assert web_page["@type"] == "WebPage" and web_page["name"] == artifact.landing_page.headline
    assert web_page["url"] == SITE + "/"
    assert organization == {"@context": "https://schema.org", "@type": "Organization",
                            "name": artifact.brand_bindings["brand_name"], "url": SITE + "/"}


def test_faq_page_is_omitted_and_the_reason_is_recorded(artifact):
    bundle = sb.build_site_bundle(artifact, site_url=SITE, lastmod=LASTMOD)
    assert all(n["@type"] != "FAQPage" for n in _ld_nodes(bundle["files"]["index.html"]))
    if any(s.kind.value == "faq" for s in artifact.landing_page.sections):
        assert any(o.startswith("FAQPage:") for o in bundle["manifest"]["omitted"])


def test_script_breaking_text_cannot_escape_the_json_block(artifact):
    hostile = artifact.model_copy(deep=True)
    page = hostile.landing_page.model_copy(update={"headline": "</script><img src=x onerror=alert(1)>"})
    tampered = seal_artifact(**{**hostile.model_dump(exclude={"hash"}), "landing_page": page})
    bundle = sb.build_site_bundle(tampered, site_url=SITE, lastmod=LASTMOD)
    html = bundle["files"]["index.html"]
    assert "<img src=x" not in html
    assert _ld_nodes(html)[0]["name"] == "</script><img src=x onerror=alert(1)>"


@pytest.mark.parametrize("url", [
    "http://example.com", "https://user:pw@example.com", "https://example.com/?q=1",
    "https://example.com/#frag", "javascript:alert(1)", "", None,
])
def test_unsafe_or_missing_site_urls_drop_sitemap_and_absolute_urls(artifact, url):
    bundle = sb.build_site_bundle(artifact, site_url=url, lastmod=LASTMOD)
    assert "sitemap.xml" not in bundle["files"]
    assert "Sitemap:" not in bundle["files"]["robots.txt"]
    assert "url" not in _ld_nodes(bundle["files"]["index.html"])[1]
    assert any(o.startswith("sitemap.xml:") for o in bundle["manifest"]["omitted"])


def test_sitemap_is_valid_xml_with_one_absolute_https_url(artifact):
    bundle = sb.build_site_bundle(artifact, site_url=SITE, lastmod=LASTMOD)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(bundle["files"]["sitemap.xml"].split("?>", 1)[1])
    locs = [e.text for e in root.findall("s:url/s:loc", ns)]
    assert locs == [SITE + "/"]
    assert root.find("s:url/s:lastmod", ns).text == LASTMOD
    assert "Sitemap: https://example.com/studio/sitemap.xml" in bundle["files"]["robots.txt"]


@pytest.mark.parametrize("bad", ["2026-13-01", "2026-11-8", "yesterday", "2026-02-30"])
def test_invalid_lastmod_is_refused(artifact, bad):
    with pytest.raises(sb.SiteBundleError):
        sb.build_site_bundle(artifact, site_url=SITE, lastmod=bad)


def test_missing_brand_name_is_refused(artifact):
    nameless = copy.deepcopy(artifact.model_dump(exclude={"hash"}))
    nameless["brand_bindings"]["brand_name"] = "  "
    with pytest.raises(sb.SiteBundleError, match="brand_name"):
        sb.build_site_bundle(seal_artifact(**nameless), site_url=SITE, lastmod=LASTMOD)


def test_non_landing_artifact_is_refused(artifact):
    no_page = seal_artifact(**artifact.model_dump(exclude={"hash", "landing_page"}))
    with pytest.raises(sb.SiteBundleError, match="landing_page"):
        sb.build_site_bundle(no_page, site_url=SITE, lastmod=LASTMOD)


def test_keywords_are_never_invented(artifact):
    bundle = sb.build_site_bundle(artifact, site_url=SITE, lastmod=LASTMOD)
    assert bundle["manifest"]["keywords"]["status"] == "NOT_MEASURED"
    assert "search_volume" not in json.dumps(bundle["files"])


def test_bundle_is_deterministic(artifact):
    first = sb.build_site_bundle(artifact, site_url=SITE, lastmod=LASTMOD)
    second = sb.build_site_bundle(artifact, site_url=SITE, lastmod=LASTMOD)
    assert first == second


def test_tampering_with_a_file_is_detected(artifact):
    bundle = sb.build_site_bundle(artifact, site_url=SITE, lastmod=LASTMOD)
    bundle["files"]["robots.txt"] += "Disallow: /\n"
    assert any("hash mismatch: robots.txt" in p for p in sb.verify_site_bundle(bundle))
