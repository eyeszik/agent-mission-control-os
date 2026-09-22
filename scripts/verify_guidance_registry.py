"""Fail-closed verifier for repository-owned prompt guidance packs."""

from __future__ import annotations

from services.langgraph.agency.guidance import default_registry


def main() -> int:
    registry = default_registry()
    if not registry.packs:
        raise SystemExit("guidance registry is empty")

    for pack in registry.packs:
        if not pack.content_hash:
            raise SystemExit(f"{pack.id}: missing computed content hash")
        if not pack.sections:
            raise SystemExit(f"{pack.id}: no guidance sections")
        if pack.authority_class.value not in {"ADVISORY", "EVIDENCE_BOUND_ADVISORY"}:
            raise SystemExit(f"{pack.id}: invalid authority class")

    print(
        "Guidance registry verified "
        f"({len(registry.packs)} pack(s), registry_hash={registry.registry_hash[:16]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
