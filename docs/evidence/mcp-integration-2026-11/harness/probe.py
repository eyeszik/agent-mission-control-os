"""Runtime probe: handshake, tools/list, calls, latency over N runs, using the official mcp SDK stdio client."""
import asyncio, json, sys, time, statistics
from datetime import timedelta
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def once(cmd, args, calls):
    t0 = time.perf_counter()
    p = StdioServerParameters(command=cmd, args=args, env={"PATH": "/usr/bin:/bin"})
    out = {}
    async with stdio_client(p) as (r, w), ClientSession(r, w) as s:
        init = await s.initialize()
        t_init = time.perf_counter() - t0
        tools = (await s.list_tools()).tools
        res = []
        for name, a in calls:
            t1 = time.perf_counter()
            cr = await s.call_tool(name, a, read_timeout_seconds=timedelta(seconds=10))
            txt = " ".join(c.text for c in cr.content if getattr(c, "type", "") == "text")
            res.append({"tool": name, "isError": cr.isError, "ms": round((time.perf_counter()-t1)*1000, 2),
                        "bytes": len(txt), "structured": cr.structuredContent is not None, "head": txt[:160]})
        out = {"server": init.serverInfo.name, "version": init.serverInfo.version, "protocol": init.protocolVersion,
               "init_ms": round(t_init*1000, 1), "tool_count": len(tools), "tools": sorted(t.name for t in tools),
               "annotations_readonly": sum(1 for t in tools if t.annotations and t.annotations.readOnlyHint),
               "calls": res}
    out["total_ms"] = round((time.perf_counter()-t0)*1000, 1)
    return out

def main():
    spec = json.loads(sys.argv[1]); n = int(sys.argv[2])
    runs = [asyncio.run(once(spec["cmd"], spec["args"], spec["calls"])) for _ in range(n)]
    first = runs[0]
    first["n"] = n
    first["init_ms_median"] = statistics.median(r["init_ms"] for r in runs)
    first["total_ms_median"] = statistics.median(r["total_ms"] for r in runs)
    first["call_ms_median"] = {c["tool"]+f"#{i}": statistics.median(r["calls"][i]["ms"] for r in runs) for i, c in enumerate(first["calls"])}
    first["deterministic"] = all(json.dumps(r["calls"] and [c["head"] for c in r["calls"]]) == json.dumps([c["head"] for c in first["calls"]]) for r in runs)
    print(json.dumps(first, indent=1))
main()
