"""The Phase 1 inventory reads the real app, and every route resolves a principal."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PUBLIC_ROUTES = {"/health", "/ready", "/version"}  # liveness and public metadata only


def _inventory_module():
    spec = importlib.util.spec_from_file_location("system_inventory", ROOT / "scripts" / "system_inventory.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_route_outside_liveness_resolves_a_principal():
    routes = _inventory_module().routes()
    assert len(routes) > 100  # the full table, including routers included into the app
    unauthenticated = {r["path"] for r in routes if r["auth"] == "none"}
    assert unauthenticated == PUBLIC_ROUTES, f"new route without auth: {sorted(unauthenticated - PUBLIC_ROUTES)}"
    # Signed ingress authenticates inside the handler (HMAC or principal).
    assert {r["auth"] for r in routes if r["path"] == "/runtime/ingest"} == {"inline"}


def test_inventory_renders_from_code_and_names_its_commit():
    module = _inventory_module()
    inv = module.inventory()
    text = module.render(inv)
    assert inv["generated_from_commit"] in text
    assert len(inv["kernel"]["artifact_types"]) == 28 and len(inv["kernel"]["roles"]) == 13
    assert inv["providers"]["action_live_enablement"]["status"] == "DISABLED"
    assert all(entry["live_status"] != "VERIFIED" for entry in inv["action_catalog"])
    # Undocumented environment variables are reported, never hidden (G-03 tracks emptying the list).
    assert isinstance(inv["env"]["read_but_undocumented"], list)
