"""Which Agency Operating Framework tasks a site's artifacts can evidence. Proposals only.

The framework's task ledger stays the only ledger: this module never writes a task. It
returns, per applicable catalog task, the current ``artifact:<id>@v<n>`` ref of the stage
that evidences it, in the framework's own ref format (``operating_framework.refs`` resolves
and reads it back). Attaching a ref is an operator action through the framework's task-refs
route, and an attached artifact does not complete a task: verification and approval stay
with the framework. Tasks the line cannot evidence are listed as not covered, with why.
"""

from __future__ import annotations

from services.langgraph.agency.project_os.storage import StorageAdapter

from .service import load_stages

# task id -> (stage that evidences it, what it shows). Task ids are from catalog.seed-v1.json.
BINDINGS: dict[str, tuple[str, str]] = {
    "AGM-08-006": ("tokens", "PSEM colour roles with computed contrast pairings"),
    "AGM-08-008": ("site_ir", "responsive grid and spacing rules of the site architecture"),
    "AGM-08-011": ("tokens", "DTCG tokens compiled through the repository's one compiler"),
    "AGM-08-013": ("browser_qa", "focus, reduced-motion and keyboard checks in real Chromium"),
    "AGM-08-014": ("requirements", "image rights requirements; procedural plates are owned"),
    "AGM-10-003": ("site_ir", "navigation, routes and content hierarchy"),
    "AGM-10-004": ("site_ir", "mobile-first page and component specifications"),
    "AGM-10-007": ("site_ir", "CTA placement and its in-site target"),
    "AGM-10-010": ("source", "generated source consuming the approved tokens"),
    "AGM-10-012": ("browser_qa", "keyboard, reflow, text zoom and reduced-motion results"),
    "AGM-10-014": ("browser_qa", "real-browser checks at 320, 768 and 1280 CSS px"),
    "AGM-10-015": ("release_proof", "the website package, test evidence and deploy-readiness record"),
    "AGM-20-003": ("requirements", "inventory of every mandatory website requirement"),
}
NOT_COVERED: dict[str, str] = {
    "AGM-10-006": "the line generates no forms",
    "AGM-10-008": "performance budgets are not measured here (NOT_MEASURED)",
    "AGM-10-009": "privacy notices and consent pages are not generated",
    "AGM-10-011": "no analytics instrumentation is generated",
    "AGM-10-013": "static pages only; loading and network-error states are not exercised",
    "AGM-24-008": "automated checks only; manual WCAG 2.2 AA testing is a person's task",
}


def framework_bindings(project_id: str, site_id: str, *, adapter: StorageAdapter) -> dict:
    entries = load_stages(project_id, site_id, adapter)["entries"]
    proposals = []
    for task_id, (stage, shows) in sorted(BINDINGS.items()):
        entry = entries.get(stage)
        proposals.append({"task_id": task_id, "stage": stage, "shows": shows,
                          "artifact_ref": f"artifact:{entry['artifact_id']}@v{entry['version']}" if entry else None,
                          "status": "PROPOSED" if entry else "STAGE_NOT_PRODUCED"})
    return {"site_id": site_id, "proposals": proposals,
            "not_covered": [{"task_id": t, "reason": r} for t, r in sorted(NOT_COVERED.items())],
            "note": "Attach refs through /agency-framework task refs; an attached artifact does not complete a task."}


__all__ = ["BINDINGS", "NOT_COVERED", "framework_bindings"]
