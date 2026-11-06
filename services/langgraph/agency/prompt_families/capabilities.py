"""External capability discovery record for the prompt-family integration.

This is provenance about what the integrating session could and could not
discover, not runtime truth: a runtime must rediscover capabilities before
relying on them (see ``prompt_compiler.ProviderCapability``). Nothing here
wires, calls or authorizes an external tool. An unknown name resolves to
``NOT_AVAILABLE``; no endpoint, schema or command is ever inferred from a name.
"""

from __future__ import annotations

from dataclasses import dataclass

DISCOVERED_ON = "2026-09-28"


@dataclass(frozen=True)
class ExternalCapability:
    name: str
    status: str  # EVIDENCE_INTERFACE | CONTRACT_ONLY | PATTERN_ONLY | NOT_AVAILABLE
    repository_surface: str
    note: str


EXTERNAL_CAPABILITIES: dict[str, ExternalCapability] = {
    c.name: c
    for c in (
        ExternalCapability(
            "SEARCH",
            "EVIDENCE_INTERFACE",
            "prompt_compiler.ResearchRequest -> SourceEvidence(query, freshness_class)",
            "Search is evidence acquisition; results enter as SourceEvidence and never mutate guidance or BrandCore.",
        ),
        ExternalCapability(
            "WOLFRAM",
            "CONTRACT_ONLY",
            "prompt_compiler.ComputationEvidence",
            "No computation tool was discoverable in the integrating session; only the provenance contract exists.",
        ),
        ExternalCapability(
            "ADS_MANAGER",
            "PATTERN_ONLY",
            "prompt_families.PaidMediaCreativeSpec + PAID_MEDIA_MUTATION_PRECONDITIONS",
            "Specification only; integrations/paid_media.py remains the fail-closed spend boundary.",
        ),
        ExternalCapability(
            "PRINTIFY",
            "PATTERN_ONLY",
            "ProductionTarget(medium=MERCH) + pg.production_design_system.v1 pds.merch_artwork_vs_product",
            "Artwork is compiled separately from product mockups; no product creation or ordering path exists.",
        ),
        ExternalCapability(
            "OGENIC GOD TOOLKIT",
            "NOT_AVAILABLE",
            "none",
            "No tool, plugin, server or repository by this name was exposed in the integrating session; no capability is assumed.",
        ),
    )
}


def external_capability_status(name: str) -> ExternalCapability:
    key = " ".join(name.upper().split())
    return EXTERNAL_CAPABILITIES.get(
        key,
        ExternalCapability(key, "NOT_AVAILABLE", "none", "Unknown capability name; nothing is inferred from it."),
    )
