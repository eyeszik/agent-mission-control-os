"""Read-only asset discovery adapters: declared, governed, and DISABLED by default.

Each adapter states its auth, usage restrictions, licence rules, attribution,
provenance, download and caching policy. None performs a network request in
this change: enabling one (``AMC_DISCOVERY_<ID>=enabled``) without a reviewed
implementation yields ``NOT_IMPLEMENTED``, never a scrape or a workaround.
Provider terms change; the declarations here are a checklist for the reviewer
who implements an adapter, not a statement of current provider policy.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict


class DiscoveryAdapter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter_id: str
    provider: str
    auth: str
    usage_restrictions: str
    rate_limits: str
    license_rules: str
    attribution: str
    provenance: str
    download_policy: str
    caching_policy: str
    error_mapping: str


ADAPTERS = {a.adapter_id: a for a in (
    DiscoveryAdapter(adapter_id="openverse", provider="Openverse", auth="optional OAuth client (verify current docs)",
                     usage_restrictions="per-item licence governs use", rate_limits="provider-defined; honour 429 Retry-After",
                     license_rules="accept only licences on an allowlist recorded per project (e.g. CC0, CC BY)",
                     attribution="store creator, title, licence and source URL with the asset",
                     provenance="record query, result id and fetched-bytes sha256",
                     download_policy="only after a human selects an item", caching_policy="project storage only, with licence",
                     error_mapping="4xx -> REJECTED, 429/5xx -> RETRY_LATER (bounded)"),
    DiscoveryAdapter(adapter_id="wikimedia_commons", provider="Wikimedia Commons", auth="none for read; user agent required",
                     usage_restrictions="per-file licence and any personality/trademark notes", rate_limits="provider-defined",
                     license_rules="per-file licence from file metadata; unknown -> excluded",
                     attribution="author and licence as listed on the file page", provenance="file page id + sha256",
                     download_policy="human-selected only", caching_policy="project storage with metadata",
                     error_mapping="4xx -> REJECTED, 5xx -> RETRY_LATER"),
    DiscoveryAdapter(adapter_id="pexels", provider="Pexels", auth="API key", usage_restrictions="Pexels licence terms",
                     rate_limits="per key; honour headers", license_rules="Pexels licence; no resale of unaltered photos",
                     attribution="photographer credit recommended", provenance="photo id + sha256",
                     download_policy="human-selected only", caching_policy="project storage", error_mapping="401 -> NOT_CONFIGURED"),
    DiscoveryAdapter(adapter_id="unsplash", provider="Unsplash", auth="API access key", usage_restrictions="Unsplash API guidelines",
                     rate_limits="per application", license_rules="Unsplash licence", attribution="photographer + Unsplash per guidelines",
                     provenance="photo id + sha256", download_policy="human-selected only; trigger download endpoint as required",
                     caching_policy="per API guidelines", error_mapping="401 -> NOT_CONFIGURED"),
    DiscoveryAdapter(adapter_id="google_fonts", provider="Google Fonts", auth="API key for the metadata API",
                     usage_restrictions="per-family licence (mostly OFL)", rate_limits="per key",
                     license_rules="record the family licence (OFL/Apache) before use", attribution="per licence",
                     provenance="family, version, file sha256", download_policy="human-selected families only",
                     caching_policy="project storage; self-hosted fonts", error_mapping="4xx -> REJECTED"),
)}


class AdapterDisabled(RuntimeError):
    pass


def status(adapter_id: str) -> str:
    if adapter_id not in ADAPTERS:
        raise KeyError(adapter_id)
    flag = (os.environ.get(f"AMC_DISCOVERY_{adapter_id.upper()}") or "disabled").strip().lower()
    return "NOT_IMPLEMENTED" if flag == "enabled" else "DISABLED"


def search(adapter_id: str, query: str) -> list[dict]:
    state = status(adapter_id)
    raise AdapterDisabled(f"{adapter_id}: {state}. No request was sent; discovery requires a reviewed adapter.")


def inventory() -> list[dict]:
    return [{**a.model_dump(), "status": status(a.adapter_id)} for a in ADAPTERS.values()]


__all__ = ["ADAPTERS", "AdapterDisabled", "DiscoveryAdapter", "inventory", "search", "status"]
