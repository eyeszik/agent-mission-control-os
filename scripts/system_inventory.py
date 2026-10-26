#!/usr/bin/env python3
"""Read-only, deterministic inventory of the repository (Phase 1 audit input).

Usage:
    python scripts/system_inventory.py            # write docs/system_inventory.generated.md
    python scripts/system_inventory.py --json     # print the inventory as JSON

It imports the app to read the real route table, kernel vocabulary, action
catalogue and skill registry; it opens no network connection and writes only the
generated markdown. The output is a point-in-time snapshot stamped with the git
commit it was generated from; it is not a freshness gate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SERVICE = ROOT / "services" / "langgraph"
OUT = ROOT / "docs" / "system_inventory.generated.md"
# os.environ.get/getenv/[...] plus the repo's small env helpers (_env, _env_number, _env_flag, ...).
ENV_RE = re.compile(r"""(?:os\.(?:environ\.get|getenv)|\b_env\w*|\b_flag|\benv_\w+)\(\s*["']([A-Z][A-Z0-9_]{2,})["']"""
                    r"""|os\.environ\[\s*["']([A-Z][A-Z0-9_]+)["']\s*\]""")
TABLE_RE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_.]*)", re.I)


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _py_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts and "tests" not in p.parts)


def modules() -> list[dict]:
    """Python packages under services/langgraph (two levels), with file and line counts."""
    groups: dict[str, list[Path]] = {}
    for path in _py_files(SERVICE):
        parts = path.relative_to(SERVICE).parts
        key = "/".join(parts[:2]) if parts[0] == "agency" and len(parts) > 2 else parts[0] if len(parts) > 1 else "(root)"
        groups.setdefault(key, []).append(path)
    return [{"package": key, "files": len(files),
             "lines": sum(len(f.read_text(encoding="utf-8", errors="replace").splitlines()) for f in files)}
            for key, files in sorted(groups.items())]


def _dependency_names(dependant) -> set[str]:
    names = set()
    for dep in getattr(dependant, "dependencies", []) or []:
        call = getattr(dep, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", repr(call)))
        names |= _dependency_names(dep)
    return names


def _source(func) -> str:
    import inspect

    try:
        return inspect.getsource(func)
    except (OSError, TypeError):
        return ""


def _walk_routes(routes, prefix: str = ""):
    """APIRoutes with their full path. Newer FastAPI keeps included routers as
    wrapper objects, so recurse through ``include_context``/``original_router``."""
    from fastapi.routing import APIRoute

    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        context = getattr(route, "include_context", None)
        inner = getattr(route, "original_router", None)
        if context is not None and inner is not None:
            yield from _walk_routes(inner.routes, prefix + (context.prefix or ""))


def routes() -> list[dict]:
    from services.langgraph.app.main import app

    rows = []
    for path, route in _walk_routes(app.routes):
        deps = _dependency_names(route.dependant)
        auth = "principal" if any("principal" in d or d.startswith("require_") for d in deps) else "none"
        if auth == "none" and "get_principal(" in _source(route.endpoint):
            auth = "inline"  # resolved inside the handler (e.g. HMAC-or-principal)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            rows.append({"method": method, "path": path, "auth": auth,
                         "module": route.endpoint.__module__.removeprefix("services.langgraph.")})
    return sorted(rows, key=lambda r: (r["path"], r["method"]))


def migrations() -> list[dict]:
    rows = []
    for path in sorted((ROOT / "supabase" / "migrations").glob("*.sql")):
        tables = sorted({m.group(1) for m in TABLE_RE.finditer(path.read_text(encoding="utf-8"))})
        rows.append({"file": path.name, "tables": tables})
    return rows


def env_vars() -> dict:
    documented = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            documented.add(line.split("=", 1)[0].strip())
    read: dict[str, set[str]] = {}
    for path in _py_files(SERVICE) + sorted((ROOT / "scripts").glob("*.py")):
        for match in ENV_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
            read.setdefault(match.group(1) or match.group(2), set()).add(_rel(path))
    # A documented name counts as referenced when it appears as a quoted literal in
    # Python, web or package source (covers mapping lookups such as env.get("X")).
    sources = _py_files(SERVICE) + sorted((ROOT / "scripts").glob("*.py")) + sorted(
        p for base in (ROOT / "apps" / "web", ROOT / "packages") for p in base.rglob("*.ts*")
        if "node_modules" not in p.parts and "dist" not in p.parts and ".next" not in p.parts)
    corpus = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sources)
    referenced = {name for name in documented if f'"{name}"' in corpus or f"'{name}'" in corpus
                  or f"process.env.{name}" in corpus}
    return {
        "documented": sorted(documented),
        "read_by_code": {k: sorted(v) for k, v in sorted(read.items())},
        "read_but_undocumented": sorted(set(read) - documented),
        "documented_but_unreferenced": sorted(documented - set(read) - referenced),
    }


def tests() -> list[dict]:
    rows = []
    for path in sorted((SERVICE / "tests").glob("test_*.py")):
        count = len(re.findall(r"^(?:async\s+)?def test_", path.read_text(encoding="utf-8"), re.M))
        rows.append({"file": path.name, "tests": count})
    return rows


def web() -> dict:
    app_dir = ROOT / "apps" / "web" / "app"
    pages = sorted("/" + p.parent.relative_to(app_dir).as_posix() if p.parent != app_dir else "/"
                   for p in app_dir.rglob("page.tsx"))
    components = Counter(p.relative_to(ROOT / "apps" / "web" / "components").parts[0]
                         for p in (ROOT / "apps" / "web" / "components").rglob("*.tsx"))
    web_tests = sorted(_rel(p) for p in (ROOT / "apps" / "web").rglob("*.test.ts*") if "node_modules" not in p.parts)
    e2e = sorted(_rel(p) for p in (ROOT / "apps" / "web").rglob("*.spec.ts") if "node_modules" not in p.parts)
    return {"pages": [p.replace("/.", "/") for p in pages], "component_dirs": dict(sorted(components.items())),
            "unit_test_files": len(web_tests), "e2e_specs": e2e}


def shared() -> dict:
    schemas = sorted(p.name for p in (ROOT / "packages" / "shared" / "src" / "schemas").glob("*.ts"))
    fixtures = sorted(p.name for p in (ROOT / "packages" / "shared" / "tests" / "fixtures").glob("*.json"))
    packages = sorted(p.name for p in (ROOT / "packages").iterdir() if (p / "package.json").exists())
    return {"packages": packages, "zod_schema_files": schemas, "parity_fixtures": fixtures}


def ci() -> list[dict]:
    rows = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        jobs_block = text.split("\njobs:", 1)[1] if "\njobs:" in text else ""
        # Each job: its display name if it has one, else its id.
        jobs = []
        for job_id, body in re.findall(r"^  ([A-Za-z0-9_-]+):\s*\n((?:^(?:    .*|\s*)\n?)*)", jobs_block, re.M):
            name = re.search(r"^    name:\s*(.+)$", body, re.M)
            jobs.append(name.group(1).strip().strip("'\"") if name else job_id)
        rows.append({"workflow": path.name, "jobs": jobs})
    return rows


def kernel() -> dict:
    from services.langgraph.agency.kernel.ontology import ArtifactType, Department
    from services.langgraph.agency.kernel.roles import role_snapshot

    roles = role_snapshot()["roles"]
    return {"departments": [d.value for d in Department], "artifact_types": [a.value for a in ArtifactType],
            "roles": [{k: r[k] for k in ("role_id", "department", "produces", "requires_human_approval",
                                          "external_side_effect")} for r in roles]}


def action_catalog() -> list[dict]:
    from services.langgraph.agency.actions.catalog import catalog

    entries = catalog().all()
    return sorted(({"id": e.id, "domain": e.domain, "provider": e.provider, "status": e.status.value,
                    "live_status": e.live_status.value, "dispatch_owner": e.dispatch_owner,
                    "environments": [x.value for x in e.environments]} for e in entries), key=lambda r: r["id"])


def skills() -> list[dict]:
    import services.langgraph.agency.execution_fabric.skills  # noqa: F401  registers fabric skills
    from services.langgraph.agency.skills.dispatcher import skill_registry_snapshot

    return [{k: s[k] for k in ("skill_id", "capability", "side_effect_class", "provider_requirement",
                                "sandbox_requirement", "available")} for s in skill_registry_snapshot()["skills"]]


def providers() -> dict:
    from services.langgraph.agency.actions.governance import live_enablement
    from services.langgraph.agency.model_profiles import PROVIDERS

    return {"model_providers": list(PROVIDERS), "action_live_enablement": live_enablement()}


def inventory() -> dict:
    os.environ.setdefault("AMC_AUTH_MODE", "local")
    return {"generated_from_commit": _git_head(), "modules": modules(), "routes": routes(),
            "migrations": migrations(), "env": env_vars(), "tests": tests(), "web": web(), "shared": shared(),
            "ci": ci(), "kernel": kernel(), "action_catalog": action_catalog(), "skills": skills(),
            "providers": providers()}


def _table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    return "\n".join(out)


def render(inv: dict) -> str:
    tests_total = sum(t["tests"] for t in inv["tests"])
    unauth = [r for r in inv["routes"] if r["auth"] == "none"]
    lines = [
        "# System inventory (generated)",
        "",
        f"Generated by `python scripts/system_inventory.py` from the working tree at commit "
        f"`{inv['generated_from_commit']}`.",
        "Point-in-time snapshot: regenerate it; do not edit by hand. It counts what the code declares,",
        "not what is deployed or observed in production.",
        "",
        "## Totals",
        "",
        _table(["Item", "Count"], [
            ["Python packages (services/langgraph)", len(inv["modules"])],
            ["Python source lines (excluding tests)", sum(m["lines"] for m in inv["modules"])],
            ["HTTP operations", len(inv["routes"])],
            ["HTTP operations with no detected auth", len(unauth)],
            ["SQL migration files", len(inv["migrations"])],
            ["Backend test files / test functions", f"{len(inv['tests'])} / {tests_total}"],
            ["Web pages", len(inv["web"]["pages"])],
            ["Zod schema files", len(inv["shared"]["zod_schema_files"])],
            ["Kernel artifact types / roles", f"{len(inv['kernel']['artifact_types'])} / {len(inv['kernel']['roles'])}"],
            ["Action catalogue entries", len(inv["action_catalog"])],
            ["Registered skills", len(inv["skills"])],
            ["Env vars read by code / documented", f"{len(inv['env']['read_by_code'])} / {len(inv['env']['documented'])}"],
        ]),
        "",
        "## Python packages",
        "",
        _table(["Package", "Files", "Lines"], [[m["package"], m["files"], m["lines"]] for m in inv["modules"]]),
        "",
        "## HTTP operations",
        "",
        "`auth` is `principal` when the route depends (directly or transitively) on a principal resolver,",
        "`inline` when the handler resolves the principal itself, otherwise `none`. `none` is expected",
        "only for liveness and public metadata routes.",
        "",
        _table(["Method", "Path", "Auth", "Module"],
               [[r["method"], f"`{r['path']}`", r["auth"], r["module"]] for r in inv["routes"]]),
        "",
        "## Migrations and tables",
        "",
        _table(["Migration", "Tables created"],
               [[m["file"], ", ".join(m["tables"]) or "(alters only)"] for m in inv["migrations"]]),
        "",
        "## Environment variables",
        "",
        f"Read by code but not in `.env.example` ({len(inv['env']['read_but_undocumented'])}): "
        + (", ".join(f"`{v}`" for v in inv["env"]["read_but_undocumented"]) or "none"),
        "",
        f"In `.env.example` but never referenced as a literal in Python, web or package source "
        f"({len(inv['env']['documented_but_unreferenced'])}; may still be read by the platform or a tool): "
        + (", ".join(f"`{v}`" for v in inv["env"]["documented_but_unreferenced"]) or "none"),
        "",
        "## Kernel vocabulary",
        "",
        "Departments: " + ", ".join(f"`{d}`" for d in inv["kernel"]["departments"]),
        "",
        "Artifact types: " + ", ".join(f"`{a}`" for a in inv["kernel"]["artifact_types"]),
        "",
        _table(["Role", "Department", "Produces", "Human approval", "External side effect"],
               [[r["role_id"], r["department"], ", ".join(r["produces"]), r["requires_human_approval"],
                 r["external_side_effect"]] for r in inv["kernel"]["roles"]]),
        "",
        "## Action catalogue",
        "",
        _table(["Id", "Domain", "Provider", "Status", "Live", "Dispatch owner", "Environments"],
               [[a["id"], a["domain"], a["provider"], a["status"], a["live_status"], a["dispatch_owner"],
                 ", ".join(a["environments"])] for a in inv["action_catalog"]]),
        "",
        f"`live_enablement()`: `{inv['providers']['action_live_enablement'].get('status')}`. "
        "Model providers in `model_profiles`: " + ", ".join(f"`{p}`" for p in inv["providers"]["model_providers"]),
        "",
        "## Registered skills",
        "",
        _table(["Skill", "Capability", "Side effect", "Provider requirement", "Sandbox", "Available here"],
               [[s["skill_id"], s["capability"], s["side_effect_class"], s["provider_requirement"],
                 s["sandbox_requirement"], s["available"]] for s in inv["skills"]]),
        "",
        "## Frontend",
        "",
        "Pages: " + ", ".join(f"`{p}`" for p in inv["web"]["pages"]),
        "",
        _table(["Component directory", ".tsx files"], [[k, v] for k, v in inv["web"]["component_dirs"].items()]),
        "",
        f"Web unit-test files: {inv['web']['unit_test_files']}. E2E specs: "
        + ", ".join(f"`{e}`" for e in inv["web"]["e2e_specs"]),
        "",
        "## Shared contracts",
        "",
        "Workspace packages: " + ", ".join(f"`{p}`" for p in inv["shared"]["packages"]),
        "",
        "Zod schema files: " + ", ".join(f"`{s}`" for s in inv["shared"]["zod_schema_files"]),
        "",
        "Parity fixtures: " + ", ".join(f"`{s}`" for s in inv["shared"]["parity_fixtures"]),
        "",
        "## CI workflows",
        "",
        _table(["Workflow", "Jobs"], [[c["workflow"], "; ".join(c["jobs"]) or "(none parsed)"] for c in inv["ci"]]),
        "",
        "## Backend tests by file",
        "",
        _table(["File", "Tests"], [[t["file"], t["tests"]] for t in inv["tests"]]),
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="print JSON instead of writing markdown")
    args = ap.parse_args(argv)
    inv = inventory()
    if args.json:
        print(json.dumps(inv, indent=2, sort_keys=True, default=str))
    else:
        OUT.write_text(render(inv), encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
