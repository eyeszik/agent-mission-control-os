"""Benchmark B1/B2: correctness of candidate outputs against independently derived oracles. Offline (netns)."""
import asyncio, json, sys, time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run(cmd, args, cases):
    out = []
    async with stdio_client(StdioServerParameters(command=cmd, args=args, env={"PATH": "/usr/bin:/bin"})) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        for name, a, check in cases:
            t = time.perf_counter(); res = await s.call_tool(name, a); ms = (time.perf_counter() - t) * 1000
            sc = res.structuredContent or {}
            try: ok, detail = check(sc, res)
            except Exception as e: ok, detail = False, f"{type(e).__name__}: {e}"
            out.append({"tool": name, "args": a, "ok": ok, "ms": round(ms, 2), "detail": detail})
    return out

near = lambda a, b, tol=0.011: abs(float(a) - float(b)) <= tol * max(1, abs(float(b)))
def find(sc, *keys):
    for k in keys:
        if k in sc: return sc[k]
    raise KeyError(f"none of {keys} in {sorted(sc)}")

which = sys.argv[1]
if which == "upgrowth":
    cmd, args = sys.argv[2], [sys.argv[3]]
    cases = []
    for spend, rev, m in [(1000, 4000, 40), (2500, 5000, 25), (800, 800, 50)]:
        roas = rev / spend; be = 100 / m
        cases.append(("roas_check", {"ad_spend": spend, "ad_revenue": rev, "gross_margin_pct": m},
                      lambda sc, r, roas=roas, be=be: (near(find(sc, "roas"), roas) and near(find(sc, "break_even_roas"), be), {k: sc.get(k) for k in ("roas", "break_even_roas")})))
    for fc, p, v in [(10000, 50, 30), (5000, 20, 15)]:
        units = fc / (p - v)
        cases.append(("break_even", {"fixed_costs": fc, "price_per_unit": p, "variable_cost_per_unit": v},
                      lambda sc, r, u=units: (near(find(sc, "break_even_units"), u, 0.02) , {"break_even_units": sc.get("break_even_units"), "oracle": u})))
    for c, ar in [(1000, 3000), (5000, 4000)]:
        roi = (ar - c) / c * 100
        cases.append(("campaign_roi", {"cost": c, "attributed_revenue": ar},
                      lambda sc, r, roi=roi: (near(find(sc, "roi_on_revenue_pct"), roi), {k: v for k, v in sc.items() if "roi" in k} | {"oracle": roi})))
    sp, nc, arpu, gm, ch = 10000, 100, 50, 80, 5
    cac = sp / nc; ltv = arpu * gm / 100 / (ch / 100); payback = cac / (arpu * gm / 100)
    cases.append(("unit_economics", {"acquisition_spend": sp, "new_customers": nc, "monthly_revenue_per_customer": arpu, "gross_margin_pct": gm, "monthly_churn_pct": ch},
                  lambda sc, r: (near(find(sc, "cac"), cac) and near(find(sc, "ltv"), ltv) and near(find(sc, "payback_months"), payback),
                                 {k: sc.get(k) for k in ("cac", "ltv", "ltv_cac_ratio", "payback_months")} | {"oracle": [cac, ltv, payback]})))
    cases.append(("roas_check", {"ad_spend": 0, "ad_revenue": 1, "gross_margin_pct": 10}, lambda sc, r: (bool(r.isError), "invalid input rejected" if r.isError else sc)))
else:
    cmd, args = sys.argv[2], ["-I", sys.argv[3]]
    import csv, pathlib
    rows = list(csv.DictReader(open(pathlib.Path(sys.argv[3]).parent / "data" / "coding-sheet.csv")))
    cases = [("lookup_connector", {"name": r["connector"]}, lambda sc, res: (sc.get("found") is True and sc.get("published_bands_match") is True, {k: sc.get(k) for k in ("name", "default_lower", "default_upper", "published_bands_match")})) for r in rows]
    # independent oracle for the band rule as documented (BAND_MEANINGS): Critical = F7 & (F1|F3|F4); High = F7 or >=2 of F1-F5; Moderate = exactly 1; else Low
    import itertools
    def band(c):
        hi = sum(c[f] == "Y" for f in ("F1", "F2", "F3", "F4", "F5")); f7 = c["F7"] == "Y"
        if f7 and (c["F1"] == "Y" or c["F3"] == "Y" or c["F4"] == "Y"): return "Critical"
        if f7 or hi >= 2: return "High"
        return "Moderate" if hi == 1 else "Low"
    for combo in itertools.product("YN", repeat=7):
        c = dict(zip(("F1","F2","F3","F4","F5","F6","F7"), combo)); exp = band(c)
        cases.append(("score_connector", c, lambda sc, r, exp=exp: (sc.get("default_lower") == exp == sc.get("default_upper"), {"got": [sc.get("default_lower"), sc.get("default_upper")], "oracle": exp})))
res = asyncio.run(run(cmd, args, cases))
fails = [r for r in res if not r["ok"]]
ms = sorted(r["ms"] for r in res)
print(json.dumps({"candidate": which, "cases": len(res), "passed": len(res) - len(fails), "p50_ms": ms[len(ms)//2], "p95_ms": ms[int(len(ms)*0.95)-1], "failures": fails[:6], "sample": res[:3]}, indent=1, default=str))
