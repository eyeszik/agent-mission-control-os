#!/usr/bin/env python3
"""Seed a deterministic Mission Council demo into the configured database.

    python scripts/seed_council_demo.py --tenant tenant_1 --project proj_1 [--user local-demo] [--engine langgraph]

Idempotent and additive: the demo idea is keyed by a fixed ``seed_key``, so a
second run finds the same idea instead of creating another one, and it never
updates or deletes an existing record. A mission is dispatched only when the
demo idea has none; it runs on the deterministic mock model (no network, no
key) and stops at the Sentinel gate. No approval is decided here: approving is
a reviewer's action in the UI or via POST /approvals/{id}/decide.

The idea is FICTIONAL demonstration content.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEED_KEY = "council-demo-v1"
TITLE = "Agent activity dashboard (demo)"
DESCRIPTION = ("Fictional demo idea: show each agent's live status on a dashboard timeline, with an approval "
               "step before anything is written.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--user", default="council-demo-seed")
    parser.add_argument("--engine", default="langgraph", choices=("langgraph", "crewai", "autogen"))
    args = parser.parse_args(argv)

    if (os.environ.get("ENABLE_REAL_MODELS") or "").strip().lower() in {"1", "true", "yes", "on"}:
        print("Refusing to seed with ENABLE_REAL_MODELS on: the demo must stay deterministic and offline.", file=sys.stderr)
        return 2
    os.environ["COUNCIL_EXECUTION"] = "inline"

    from services.langgraph.agency.council import service
    from services.langgraph.agency.council.contracts import DispatchRequest, IdeaCreate
    from services.langgraph.persistence import council as store
    from services.langgraph.security.auth import Principal

    principal = Principal(user_id=args.user, tenant_id=args.tenant, role="operator",
                          allowed_project_ids=frozenset({args.project}))
    idea = service.create_idea(principal, IdeaCreate(project_id=args.project, title=TITLE, description=DESCRIPTION),
                               seed_key=SEED_KEY)
    missions = store.missions_for_idea(idea["idea_id"])
    if missions:
        mission = missions[0]
        created = False
    else:
        mission = service.dispatch(principal, DispatchRequest(idea_id=idea["idea_id"], engine=args.engine))
        created = True
    print(json.dumps({"idea_id": idea["idea_id"], "mission_id": mission["mission_id"],
                      "status": mission.get("status"), "mission_created": created}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
