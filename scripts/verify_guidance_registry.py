"""Fail-closed verifier for repository-owned prompt guidance packs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.langgraph.agency.guidance import default_registry


def main() -> int:
    registry = default_registry()
    if not registry.packs:
        raise SystemExit("guidance registry is empty")

    required_pack_ids = {"pg.branding.core", "pg.studio_identity.v4", "pg.ui_ux.core"}
    present_pack_ids = {pack.id for pack in registry.packs}
    missing_pack_ids = sorted(required_pack_ids - present_pack_ids)
    if missing_pack_ids:
        raise SystemExit(f"required guidance packs missing: {missing_pack_ids}")

    for pack in registry.packs:
        if not pack.content_hash:
            raise SystemExit(f"{pack.id}: missing computed content hash")
        if not pack.sections:
            raise SystemExit(f"{pack.id}: no guidance sections")
        if pack.authority_class.value not in {"ADVISORY", "EVIDENCE_BOUND_ADVISORY"}:
            raise SystemExit(f"{pack.id}: invalid authority class")
        if pack.id == "pg.studio_identity.v4":
            if pack.pack_version != "4.0.0":
                raise SystemExit("pg.studio_identity.v4: unexpected pack version")
            if not any(section.directive_targets for section in pack.sections):
                raise SystemExit(
                    "pg.studio_identity.v4: typed directive targets are required"
                )
        if pack.id == "pg.ui_ux.core":
            # The UI/UX pack must stay scoped to UI work and stay advisory: it
            # shapes prompts, it cannot become a conformance authority.
            if pack.activation.asset_families != ["UI_UX"]:
                raise SystemExit("pg.ui_ux.core: must activate for the UI_UX family only")
            if not all(section.directive_targets for section in pack.sections):
                raise SystemExit("pg.ui_ux.core: every section needs typed directive targets")

    print(
        "Guidance registry verified "
        f"({len(registry.packs)} pack(s), registry_hash={registry.registry_hash[:16]})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
