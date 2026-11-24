"""Reviewed MCP profile for the upGrowth Growth Toolkit: admission, isolation, per-tool correctness, refusals.

The server is the vendored, byte-identical upstream (tests/fixtures/vendor/upgrowth_growth_toolkit, MIT), run
by the operator's Node under the permission model with the network-denial preload. Calls go through
``gateway.invoke``. Every allowlisted tool is checked against an oracle written from the standard formula,
not from the tool's own output. Decision record: docs/mcp-integration-audit.md.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services.langgraph.agency.council import mcp_client, mcp_profiles
from services.langgraph.agency.council.gateway import GatewayDenied, invoke, registry
from services.langgraph.agency.council.mcp_profile_upgrowth import EXCLUDED_TOOLS, UPSTREAM_TOOLS
from services.langgraph.persistence import council as store
from services.langgraph.tests.council_support import (
    as_user,
    client,
    council,  # noqa: F401 - fixture
    gated_mission,
    isolated_node,
    require_supported_mcp,
)

VENDOR = Path(__file__).parent / "fixtures" / "vendor" / "upgrowth_growth_toolkit"
SERVER = VENDOR / "src" / "stdio.mjs"
WORKER = VENDOR / "src" / "worker.mjs"


def _node(tmp_path) -> str:
    node = isolated_node(tmp_path)
    if node is None:
        pytest.skip("Node >= 20 is required for the upGrowth profile")
    return node


def _ctx(mission: dict) -> dict:
    return {"tenant_id": mission["tenant_id"], "project_id": mission["project_id"],
            "mission_id": mission["mission_id"], "user_id": "tester"}


def _denied(fn) -> GatewayDenied:
    with pytest.raises(GatewayDenied) as caught:
        fn()
    return caught.value


def _enable(monkeypatch, entry: dict) -> None:
    monkeypatch.setenv("AMC_MCP_SERVERS", json.dumps(entry))


@pytest.fixture
def upgrowth(monkeypatch, council, tmp_path):  # after ``council``, which clears AMC_MCP_SERVERS  # noqa: F811
    require_supported_mcp()
    pytest.importorskip("jsonschema")
    entry = mcp_profiles.build_server_entry("upgrowth", SERVER, _node(tmp_path))
    _enable(monkeypatch, entry)
    return entry


@pytest.fixture
def mission(upgrowth, monkeypatch, council):  # noqa: F811
    return gated_mission(monkeypatch, council["project_id"])


def _call(mission: dict, tool: str, args: dict, seat: str = "george") -> dict:
    return invoke(f"mcp.upgrowth.{tool}", args, ctx=_ctx(mission), seat=seat)["result"]


# ----------------------------------------------------------------------------------- source review


def test_vendored_server_is_the_reviewed_upstream_bytes():
    assert mcp_client.file_sha256(str(SERVER)) == mcp_profiles.UPGROWTH.entry.sha256
    assert mcp_client.file_sha256(str(WORKER)) == mcp_profiles.UPGROWTH.data_files[0].sha256


def test_reviewed_server_has_no_imports_dynamic_code_or_process_access():
    stdio, worker = SERVER.read_text(encoding="utf-8"), WORKER.read_text(encoding="utf-8")
    assert re.findall(r"^import .* from '([^']+)';$", stdio, re.M) == ["node:readline", "./worker.mjs"]
    assert not re.search(r"^\s*import\b|\bimport\(|\brequire\(", worker, re.M)
    for pattern in (r"\beval\(", r"new Function", r"\bprocess\.", r"child_process", r"node:(net|http|https|dns|tls)"):
        assert not re.search(pattern, worker), pattern
    # The only network reach is fetch: the crawler tool and a Worker route fallthrough the shim never takes.
    assert len(re.findall(r"\bfetch\(", worker)) == 3


def test_schema_module_matches_the_vendored_servers_tools_list(tmp_path):
    node = _node(tmp_path)
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    out = subprocess.run([node, str(SERVER)], input=request, capture_output=True, text=True, timeout=30, check=True)
    tools = {t["name"]: t for t in json.loads(out.stdout)["result"]["tools"]}

    def strip(node):  # annotation keywords only; property names such as "title" are kept
        if isinstance(node, list):
            return [strip(v) for v in node]
        if not isinstance(node, dict):
            return node
        return {k: ({name: strip(sub) for name, sub in v.items()} if k == "properties" else strip(v))
                for k, v in node.items() if k not in ("description", "title")}

    assert set(tools) == set(UPSTREAM_TOOLS) | set(EXCLUDED_TOOLS)
    for name, spec in UPSTREAM_TOOLS.items():
        assert strip(tools[name]["inputSchema"]) == spec["input_schema"], name
        assert tools[name]["annotations"]["readOnlyHint"] is True, name


# ----------------------------------------------------------------------------------------- config


def test_disabled_by_default(monkeypatch, council):  # noqa: F811
    monkeypatch.delenv("AMC_MCP_SERVERS", raising=False)
    assert not any(tool_id.startswith("mcp.upgrowth.") for tool_id in registry())


def _all_strings_bounded(schema: dict) -> bool:
    kind = schema.get("type")
    if kind == "string":
        return "enum" in schema or 0 < schema.get("maxLength", 0) <= 60_000
    if kind == "array":
        return 0 < schema.get("maxItems", 0) <= 50 and _all_strings_bounded(schema.get("items") or {})
    if kind == "object":
        props = schema.get("properties")
        if not props:
            return 0 < schema.get("maxProperties", 0) <= 40
        return schema.get("additionalProperties") is False and all(_all_strings_bounded(p) for p in props.values())
    return True


def test_allowlist_is_26_read_tools_with_hardened_schemas():
    tools = mcp_profiles.profile_tools("upgrowth")
    assert len(tools) == 26 and not set(tools) & set(EXCLUDED_TOOLS)
    for name, spec in tools.items():
        assert spec["sensitivity"] == "READ" and spec["scopes"] == ["mcp:read"], name
        assert spec["timeout_s"] <= 10 and 0 < spec["max_result_bytes"] <= 64_000, name
        assert _all_strings_bounded(spec["input_schema"]), name
    tools["roas_check"]["sensitivity"] = "WRITE"
    assert mcp_profiles.profile_tools("upgrowth")["roas_check"]["sensitivity"] == "READ"  # fresh copy each call


def test_entry_runs_under_the_permission_model_with_every_executed_file_pinned(tmp_path):
    entry = mcp_profiles.build_server_entry("upgrowth", SERVER, _node(tmp_path))["upgrowth"]
    preload = str(mcp_profiles.NO_NETWORK_PRELOAD)
    assert entry["args"][0] in {"--permission", "--experimental-permission"}
    assert sorted(a for a in entry["args"] if a.startswith("--allow-fs-read=")) == sorted(
        f"--allow-fs-read={p}" for p in (str(SERVER), str(WORKER), preload))
    assert not any(a.startswith(("--allow-child-process", "--allow-fs-write", "--allow-worker", "--allow-addons"))
                   for a in entry["args"])
    assert entry["args"][-4:] == ["--import", preload, str(SERVER), str(WORKER)]
    assert set(entry["pins"]) == {entry["command"], str(SERVER), str(WORKER), preload}


@pytest.mark.parametrize("version, flag", [((20, 0, 0), "--experimental-permission"),
                                           ((22, 12, 0), "--experimental-permission"),
                                           ((22, 13, 0), "--permission"), ((23, 4, 1), "--experimental-permission"),
                                           ((23, 5, 0), "--permission"), ((24, 0, 0), "--permission")])
def test_permission_flag_follows_the_node_version(version, flag):
    assert mcp_profiles.permission_flag(version) == flag


def test_old_node_and_non_node_interpreters_are_refused(monkeypatch, tmp_path):
    with pytest.raises(mcp_profiles.ProfileError, match="too old"):
        mcp_profiles.permission_flag((18, 20, 0))
    with pytest.raises(mcp_profiles.ProfileError, match="did not report a Node version"):
        mcp_profiles.build_server_entry("upgrowth", SERVER, "/bin/true")


@pytest.mark.parametrize("target", ["stdio.mjs", "worker.mjs"])
def test_profile_refuses_any_bytes_but_the_reviewed_ones(tmp_path, target):
    copy = tmp_path / "ug" / "src"
    shutil.copytree(VENDOR / "src", copy)
    (copy / target).write_text((copy / target).read_text() + "\n// drift\n")
    with pytest.raises(mcp_profiles.ProfileError, match="reviewed sha256"):
        mcp_profiles.build_server_entry("upgrowth", copy / "stdio.mjs", _node(tmp_path))


def test_cli_requires_an_explicit_node_interpreter(tmp_path, capsys):
    assert mcp_profiles.main(["upgrowth", "--server-script", str(SERVER)]) == 2
    assert "--interpreter is required" in capsys.readouterr().err
    assert mcp_profiles.main(["upgrowth", "--server-script", str(SERVER), "--interpreter", _node(tmp_path)]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {"upgrowth"}


# --------------------------------------------------------------------------------------- isolation


def _sandboxed(tmp_path, script: str) -> subprocess.CompletedProcess:
    """Run ``script`` with exactly the profile's Node flags (permission model + preload)."""
    entry = mcp_profiles.build_server_entry("upgrowth", SERVER, _node(tmp_path))["upgrowth"]
    flags = entry["args"][: entry["args"].index(str(SERVER))]
    return subprocess.run([entry["command"], *flags, "--input-type=module", "-e", script], capture_output=True,
                          text=True, timeout=30, check=False)


def test_preload_disables_fetch_and_cannot_be_undone(tmp_path):
    done = _sandboxed(tmp_path, "try { globalThis.fetch = null } catch (e) {}\n"
                                "try { await fetch('https://example.com'); console.log('FETCHED') }"
                                " catch (e) { console.log('refused:' + e.message) }")
    assert "refused:network access is disabled" in done.stdout, done.stderr
    assert "FETCHED" not in done.stdout


def test_permission_model_denies_processes_and_writes(tmp_path):
    target = tmp_path / "written.txt"
    done = _sandboxed(tmp_path, "import cp from 'node:child_process'; import fs from 'node:fs';\n"
                                "try { cp.execSync('id'); console.log('SPAWNED') } catch (e) { console.log('cp:' + e.code) }\n"
                                f"try {{ fs.writeFileSync({json.dumps(str(target))}, 'x'); console.log('WROTE') }}"
                                " catch (e) { console.log('fs:' + e.code) }")
    assert "cp:ERR_ACCESS_DENIED" in done.stdout and "fs:ERR_ACCESS_DENIED" in done.stdout, done.stdout + done.stderr
    assert not target.exists()


def test_excluded_tools_are_not_reachable(upgrowth, mission, council):  # noqa: F811
    body = client.get("/missions/tools").json()
    listed = {t["tool_id"] for t in body["tools"] if t["provider"] == "mcp"}
    assert listed == {f"mcp.upgrowth.{name}" for name in UPSTREAM_TOOLS}, body["mcp_config_errors"]
    for name in EXCLUDED_TOOLS:
        assert _denied(lambda n=name: _call(mission, n, {})).code == "TOOL_NOT_ALLOWLISTED"


def test_even_an_allowlisted_crawler_could_not_reach_the_network(upgrowth, monkeypatch, council):  # noqa: F811
    """Defence in depth: if an operator ever allowlisted the crawler, the preload still refuses the request."""
    entry = json.loads(json.dumps(upgrowth))
    entry["upgrowth"]["tools"]["ai_crawler_access_check"] = {"sensitivity": "READ", "scopes": ["mcp:read"]}
    _enable(monkeypatch, entry)
    mission = gated_mission(monkeypatch, council["project_id"])
    error = _denied(lambda: _call(mission, "ai_crawler_access_check", {"domain": "example.com"}))
    assert error.code == "MCP_TOOL_ERROR" and "Could not reach" in str(error)


# ---------------------------------------------------------------------------- per-tool correctness

# Each oracle is the textbook formula for the quantity; values are compared to 2 decimal places.
CASES = {
    "unit_economics": ({"acquisition_spend": 10000, "new_customers": 100, "monthly_revenue_per_customer": 50,
                        "gross_margin_pct": 80, "monthly_churn_pct": 5},
                       {"cac": 10000 / 100, "ltv": 50 * 0.8 / 0.05, "ltv_to_cac": (50 * 0.8 / 0.05) / 100,
                        "payback_months": 100 / (50 * 0.8), "customer_lifetime_months": 1 / 0.05}),
    "growth_rate": ({"start_value": 100, "end_value": 200, "periods": 12},
                    {"total_growth_pct": 100, "compound_growth_pct_per_period": (2 ** (1 / 12) - 1) * 100}),
    "roas_check": ({"ad_revenue": 4000, "ad_spend": 1000, "gross_margin_pct": 40},
                   {"roas": 4, "break_even_roas": 1 / 0.4, "gross_profit_after_ad_spend": 4000 * 0.4 - 1000}),
    "ad_budget_planner": ({"target_customers": 50, "cost_per_click": 2, "click_to_lead_pct": 10,
                           "lead_to_customer_pct": 20},
                          {"leads_needed": 50 / 0.2, "clicks_needed": 50 / 0.2 / 0.1, "monthly_budget": 2500 * 2,
                           "cost_per_lead": 5000 / 250, "cost_per_customer": 5000 / 50}),
    "max_affordable_cac": ({"monthly_revenue_per_customer": 50, "gross_margin_pct": 80, "monthly_churn_pct": 5,
                            "target_ltv_to_cac": 3, "lead_to_customer_pct": 20},
                           {"ltv": 800, "max_cac": 800 / 3, "max_cpl": 800 / 3 * 0.2}),
    "period_change": ({"previous_value": 80, "current_value": 100}, {"absolute_change": 20, "pct_change": 25}),
    "seo_roi": ({"monthly_organic_visits_gain": 5000, "conversion_rate_pct": 2, "value_per_conversion": 100,
                 "monthly_seo_cost": 4000, "gross_margin_pct": 50, "months": 12},
                {"conversions_per_month": 100, "revenue_per_month": 10000, "gross_profit_per_month": 5000,
                 "monthly_roi_pct": (5000 - 4000) / 4000 * 100, "total_cost": 48000, "total_return": 60000,
                 "break_even_visits_per_month": 4000 / (0.02 * 100 * 0.5)}),
    "mdr_charges": ({"sales_value": 100000, "mdr_pct": 2, "transactions": 100, "fixed_fee_per_transaction": 3,
                     "gst_pct": 18},
                    {"mdr_fee": 2000 + 300, "gst": 2300 * 0.18, "total_cost": 2300 * 1.18,
                     "net_settlement": 100000 - 2300 * 1.18}),
    "youtube_earnings": ({"monthly_views": 1_000_000, "rpm": 2}, {"monthly_earnings": 2000, "yearly_earnings": 24000}),
    "instagram_earnings": ({"followers": 100000, "posts_per_month": 10, "rate_per_post": 500},
                           {"fee_per_post": 500, "monthly_income": 5000, "yearly_income": 60000}),
    "engagement_rate": ({"likes": 900, "comments": 80, "shares": 20, "base_value": 10000},
                        {"interactions": 1000, "engagement_rate_pct": 10}),
    "website_ad_revenue": ({"monthly_pageviews": 100000, "page_rpm": 10},
                           {"monthly_revenue": 1000, "yearly_revenue": 12000}),
    "ytd_growth": ({"this_ytd_total": 1200, "last_ytd_total": 1000, "months_elapsed": 6},
                   {"ytd_growth_pct": 20, "run_rate": 1200 / 6 * 12}),
    "ppc_forecast": ({"monthly_budget": 10000, "cost_per_click": 2, "conversion_rate_pct": 5,
                      "value_per_conversion": 100, "gross_margin_pct": 50},
                     {"clicks": 5000, "conversions": 250, "cpa": 40, "revenue": 25000, "roas": 2.5,
                      "profit_after_ads": 25000 * 0.5 - 10000, "break_even_cpa": 100 * 0.5}),
    "customer_lifetime_value": ({"average_order_value": 50, "purchases_per_year": 4, "customer_lifespan_years": 3,
                                 "gross_margin_pct": 60},
                                {"annual_revenue": 200, "lifetime_revenue": 600, "clv_gross_profit": 600 * 0.6}),
    "ecommerce_metrics": ({"revenue": 100000, "orders": 1000, "sessions": 50000, "customers": 800},
                          {"aov": 100, "conversion_rate_pct": 2, "revenue_per_visitor": 2, "orders_per_customer": 1.25}),
    "growth_projection": ({"start_value": 1000, "growth_rate_pct": 10, "periods": 3},
                          {"end_value": 1000 * 1.1 ** 3, "total_growth_pct": (1.1 ** 3 - 1) * 100,
                           "doubling_periods": math.log(2) / math.log(1.1)}),
    "acos_check": ({"ad_spend": 1000, "ad_sales": 5000, "gross_margin_pct": 40, "total_sales": 20000},
                   {"acos_pct": 20, "roas": 5, "break_even_acos_pct": 40, "profit_after_ads": 5000 * 0.4 - 1000,
                    "tacos_pct": 5}),
    "share_of_voice": ({"brand_name": "Us", "brand_value": 30,
                        "competitors": [{"name": "A", "value": 50}, {"name": "B", "value": 20}]},
                       {"total": 100, "brand_share_pct": 30, "brand_rank": 2}),
    "break_even": ({"fixed_costs": 10000, "price_per_unit": 50, "variable_cost_per_unit": 30},
                   {"contribution_margin": 20, "contribution_margin_pct": 40, "break_even_units": 10000 / 20,
                    "break_even_revenue": 10000 / 20 * 50}),
    "campaign_roi": ({"cost": 1000, "attributed_revenue": 3000, "gross_margin_pct": 50},
                     {"roi_on_revenue_pct": 200, "revenue_multiple": 3, "roi_on_profit_pct": 50, "net_profit": 500}),
    "attrition_rate": ({"separations": 12, "headcount_start": 100, "headcount_end": 110, "period_months": 12},
                       {"average_headcount": 105, "attrition_pct": 12 / 105 * 100, "annualised_pct": 12 / 105 * 100}),
}
GENERATORS = {"robots_txt_generator", "schema_generator", "content_seo_check", "meta_tags_builder"}


def test_every_allowlisted_tool_has_a_correctness_check():
    assert set(CASES) | GENERATORS == set(UPSTREAM_TOOLS)


@pytest.mark.parametrize("tool", sorted(CASES))
def test_calculator_matches_its_independent_oracle(mission, tool):
    # One mission per tool: the ASI10 guard allows at most 8 distinct tools in a session (TOOL_SPRAWL).
    args, expected = CASES[tool]
    got = _call(mission, tool, args)["structured"]
    failures = [f"{key}: got {got.get(key)!r}, expected {value:.4f}" for key, value in expected.items()
                if key not in got or abs(float(got[key]) - value) > 0.006 * max(1.0, abs(value))]
    assert not failures, failures


def test_the_sprawl_guard_still_applies_to_mcp_tools(mission):
    """Nine distinct calculators in one session trip ASI10's TOOL_SPRAWL; the ninth is refused and audited."""
    tools = sorted(CASES)[:9]
    for tool in tools[:8]:
        _call(mission, tool, CASES[tool][0])
    assert _denied(lambda: _call(mission, tools[8], CASES[tools[8]][0])).code == "TOOL_SPRAWL"
    assert store.list_tool_audits(mission["mission_id"])[-1]["reason_code"] == "TOOL_SPRAWL"


def test_calculators_reject_invalid_input(mission):
    assert _denied(lambda: _call(mission, "roas_check", {"ad_spend": 0, "ad_revenue": 1, "gross_margin_pct": 10})
                   ).code in {"SCHEMA_INVALID", "MCP_TOOL_ERROR"}
    assert _denied(lambda: _call(mission, "break_even", {"fixed_costs": 1, "price_per_unit": 1,
                                                         "variable_cost_per_unit": 1, "shell": "x"})).code == \
        "SCHEMA_INVALID"


def test_robots_txt_generator_blocks_training_bots_and_refuses_injection(mission):
    got = _call(mission, "robots_txt_generator", {"ai_training": "block", "disallow_paths": ["/admin/"],
                                                  "sitemap_url": "https://example.com/sitemap.xml"})["structured"]
    text = got["robots_txt"]
    assert "Disallow: /admin/" in text and "Sitemap: https://example.com/sitemap.xml" in text
    assert re.search(r"User-agent: GPTBot\n(User-agent: .*\n)*Disallow: /\n", text)
    assert "Googlebot" not in [line.split(": ", 1)[-1] for line in text.splitlines() if line.startswith("User-agent")]
    injected = _denied(lambda: _call(mission, "robots_txt_generator",
                                     {"disallow_paths": ["/a\nUser-agent: *\nAllow: /"]}))
    assert injected.code == "MCP_TOOL_ERROR"


def test_schema_generator_emits_json_ld_that_cannot_break_out_of_its_script_tag(mission):
    hostile = '"><script>alert(1)</script></script><script>x()'
    result = _call(mission, "schema_generator",
                   {"schema_type": "faq", "data": {"questions": [{"question": hostile, "answer": "a"}]}})
    ld = result["structured"]["json_ld"]
    assert ld["@type"] == "FAQPage" and ld["mainEntity"][0]["name"] == hostile
    script = re.search(r'<script type="application/ld\+json">\n(.*?)\n</script>', result["content"][0], re.S)
    assert script and "</script" not in script.group(1) and json.loads(script.group(1)) == ld
    org = _call(mission, "schema_generator", {"schema_type": "organization",
                                              "data": {"name": "x", "url": "javascript:alert(1)"}})["structured"]
    assert "url" not in org["json_ld"]


def test_meta_tags_builder_escapes_html_and_validates_urls(mission):
    tags = _call(mission, "meta_tags_builder", {"title": 'A"><script>alert(1)</script>', "description": "d & <b>",
                                                "url": "https://example.com/p"})["structured"]["tags"]
    assert "<script>" not in tags and "&lt;script&gt;" in tags and "&amp;" in tags and "&quot;" in tags
    assert '<link rel="canonical" href="https://example.com/p">' in tags
    assert _denied(lambda: _call(mission, "meta_tags_builder", {"title": "t", "description": "d",
                                                                "url": 'https://e.com/"onload=x'})).code == \
        "MCP_TOOL_ERROR"


def test_content_seo_check_counts_keywords(mission):
    text = "# ROAS guide\nROAS measures revenue per ad dollar. ROAS matters for every campaign. Track ROAS weekly."
    got = _call(mission, "content_seo_check", {"text": text, "keyword": "ROAS",
                                               "secondary_keywords": ["campaign"]})["structured"]
    words = len(re.findall(r"[A-Za-z]+", text.replace("#", "")))
    assert got["words"] == words and got["headings"] == 1
    counts = {k["keyword"]: k["count"] for k in got["keywords"]}
    assert counts == {"ROAS": text.count("ROAS"), "campaign": 1}


# ---------------------------------------------------------------------------- security / reliability


def test_another_tenant_cannot_read_the_audit_trail(mission, monkeypatch):
    _call(mission, "roas_check", CASES["roas_check"][0])
    own = client.get(f"/missions/{mission['mission_id']}/tool-audits")
    assert own.status_code == 200 and [i["decision"] for i in own.json()["items"]] == ["ALLOWED"]
    assert {(a["tenant_id"], a["project_id"]) for a in store.list_tool_audits(mission["mission_id"])} == \
        {(mission["tenant_id"], mission["project_id"])}
    as_user(monkeypatch, "outsider", tenant="tenant-other")
    assert client.get(f"/missions/{mission['mission_id']}/tool-audits").status_code in {403, 404}


def test_secrets_in_arguments_are_redacted_in_audit_and_result(mission):
    secret = "sk-live-ABCDEFGHIJKLMNOP1234"
    result = invoke("mcp.upgrowth.campaign_roi", {"cost": 1, "attributed_revenue": 2, "campaign_name": f"x {secret}"},
                    ctx=_ctx(mission), seat="george")
    assert secret not in json.dumps(result)
    assert secret not in json.dumps(store.list_tool_audits(mission["mission_id"]), default=str)


def test_unbounded_input_and_oversized_results_are_refused(upgrowth, monkeypatch, council):  # noqa: F811
    mission = gated_mission(monkeypatch, council["project_id"])
    assert _denied(lambda: _call(mission, "content_seo_check", {"text": "x" * 60_001})).code == "SCHEMA_INVALID"
    entry = json.loads(json.dumps(upgrowth))
    entry["upgrowth"]["tools"]["robots_txt_generator"]["max_result_bytes"] = 100
    _enable(monkeypatch, entry)
    assert _denied(lambda: _call(mission, "robots_txt_generator", {})).code == "MCP_RESULT_TOO_LARGE"


def test_files_changed_after_admission_are_refused_at_spawn(monkeypatch, tmp_path, council):  # noqa: F811
    require_supported_mcp()
    copy = tmp_path / "ug" / "src"
    shutil.copytree(VENDOR / "src", copy)
    _enable(monkeypatch, mcp_profiles.build_server_entry("upgrowth", copy / "stdio.mjs", _node(tmp_path)))
    spec = mcp_client.mcp_tools()["mcp.upgrowth.roas_check"]
    (copy / "worker.mjs").write_text((copy / "worker.mjs").read_text() + "\n")
    with pytest.raises(GatewayDenied) as exc:
        mcp_client.call_mcp_tool(spec, CASES["roas_check"][0])
    assert exc.value.code in {"MCP_PIN_MISMATCH", "MCP_SERVER_NOT_CONFIGURED"}
