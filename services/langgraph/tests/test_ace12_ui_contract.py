"""T58–T60: UI contract, browser reachability and LIVE gating as the UI sees them."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware

from services.langgraph.agency.design_tokens import _deep_merge, compile_graph
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio
from services.langgraph.app.main import app
from services.langgraph.tests._ace12_support import REQUESTER, act_as, make_world
from services.langgraph.tests._project_os_support import client

ROOT = Path(__file__).resolve().parents[3]


def test_t58_every_route_method_passes_the_cors_preflight():
    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    allowed = set(cors.kwargs["allow_methods"])
    used = {m.upper() for ops in app.openapi()["paths"].values() for m in ops}
    assert used <= allowed, sorted(used - allowed)


def test_t59_light_theme_meets_its_declared_wcag_pairs():
    doc = json.loads((ROOT / "apps/web/tokens/amc.tokens.json").read_text())
    light = doc["$extensions"]["amc"]["themes"]["light"]
    graph = compile_graph(_deep_merge(doc, light["tokens"]), tiered=True)
    thresholds = {"AAA_NORMAL": 7.0, "AA_NORMAL": 4.5, "AA_LARGE": 3.0, "NON_TEXT": 3.0}
    for pair in light["contrastPairs"]:
        ratio = wcag_contrast_ratio(graph.get(pair["foreground"]).css, graph.get(pair["background"]).css)
        assert ratio >= thresholds[pair["wcag"]], (pair, ratio)
    css = (ROOT / "apps/web/app/tokens.css").read_text()
    assert '[data-amc-theme="light"]' in css and "--amc-component-ai-trust-color-surface" in css.split('[data-amc-theme="light"]')[1]


def test_t60_authority_twin_never_offers_live_or_self_approval(monkeypatch, tmp_path):
    w = make_world(monkeypatch, tmp_path)
    act_as(w, REQUESTER)
    me = client.get("/agency-os/me").json()
    assert me["can"]["self_approve"] is False and me["can"]["decide_approvals"] is False
    assert any("LIVE" in n for n in me["never"])
    assert client.get("/actions/live").json()["status"] == "DISABLED"
