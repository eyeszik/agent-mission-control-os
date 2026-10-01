"""Portfolio command center: an aggregate over isolated projects.

Only projects the principal may access are read. The portfolio returns counts
and health signals per project; it never returns another project's private
memory, conversations or brand canon. Cross-brand reuse is limited to the
explicitly shareable classes: M0 agency memory, provider profiles and
workstream templates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from services.langgraph.agency.project_os.workstreams import WORKSTREAMS
from services.langgraph.persistence.database import normalize_record, table, transaction
from services.langgraph.persistence.project_knowledge import list_memory, list_provider_profiles
from services.langgraph.persistence.project_media import rights_expiration_radar
from services.langgraph.persistence.projects import list_project_workspaces


def _count(db: Any, sql: str, params: tuple) -> int:
    row = db.execute(sql, params).fetchone()
    return int(normalize_record(row)["n"]) if row else 0


def project_health(project_id: str, *, now: datetime) -> dict[str, Any]:
    soon = (now + timedelta(days=14)).isoformat()
    with transaction() as db:
        production = _count(db, f"SELECT COUNT(*) AS n FROM {table('content_items')} WHERE project_id = ? AND state IN ('IN_PRODUCTION','PLANNED')", (project_id,))
        review = _count(db, f"SELECT COUNT(*) AS n FROM {table('content_items')} WHERE project_id = ? AND state = 'REVIEW'", (project_id,))
        run_approvals = _count(db, f"SELECT COUNT(*) AS n FROM {table('approvals')} WHERE project_id = ? AND status = 'pending'", (project_id,))
        upcoming = _count(db, f"SELECT COUNT(*) AS n FROM {table('schedule_slots')} WHERE project_id = ? AND scheduled_for >= ? AND scheduled_for < ? AND state IN ('open','filled')", (project_id, now.isoformat(), soon))
        queue = db.execute(f"SELECT status, COUNT(*) AS n FROM {table('scheduled_jobs')} WHERE project_id = ? AND status IN ('PENDING','BLOCKED','ENQUEUED') GROUP BY status", (project_id,)).fetchall()
        stale = _count(db, f"SELECT COUNT(*) AS n FROM {table('agency_artifacts')} WHERE project_id = ? AND status IN ('invalidated','review_required')", (project_id,))
        campaigns = db.execute(f"SELECT DISTINCT campaign_id FROM {table('content_items')} WHERE project_id = ? AND campaign_id IS NOT NULL", (project_id,)).fetchall()
        spend = db.execute(f"SELECT status, currency, SUM(amount_minor) AS total FROM {table('spend_authorizations')} WHERE project_id = ? GROUP BY status, currency", (project_id,)).fetchall()
        performance = _count(db, f"SELECT COUNT(*) AS n FROM {table('memory_records')} WHERE project_id = ? AND scope = 'M5_PERFORMANCE' AND status = 'ACTIVE'", (project_id,))
        # The LIKE pattern is a bound parameter: a literal '%' in the SQL text is
        # read as a placeholder by psycopg on PostgreSQL.
        search = _count(db, f"SELECT COUNT(*) AS n FROM {table('memory_records')} WHERE project_id = ? AND scope = 'M5_PERFORMANCE' AND status = 'ACTIVE' AND subject_key LIKE ?", (project_id, "search.%"))
        gaps = db.execute(f"SELECT atom_id, MAX(version) AS v FROM {table('content_atoms')} WHERE project_id = ? GROUP BY atom_id", (project_id,)).fetchall()
        items_per_atom = _count(db, f"SELECT COUNT(DISTINCT atom_id) AS n FROM {table('content_items')} WHERE project_id = ? AND atom_id IS NOT NULL", (project_id,))
    queue_counts = {normalize_record(r)["status"]: int(normalize_record(r)["n"]) for r in queue}
    radar = rights_expiration_radar(project_id, now=now)
    risks = []
    if queue_counts.get("BLOCKED"):
        risks.append(f"{queue_counts['BLOCKED']} publication job(s) blocked")
    if radar["expired"]:
        risks.append(f"{len(radar['expired'])} rights record(s) expired")
    if stale:
        risks.append(f"{stale} stale artifact(s) need remediation")
    return {
        "production_queue": production,
        "approval_queue": {"content_review": review, "run_approvals": run_approvals},
        "upcoming_calendar_14d": upcoming,
        "publication_queue": queue_counts,
        "active_campaigns": sorted(normalize_record(r)["campaign_id"] for r in campaigns),
        "budget_status": [
            {"status": normalize_record(r)["status"], "currency": normalize_record(r)["currency"], "total_minor": int(normalize_record(r)["total"] or 0)}
            for r in spend
        ],
        "search_visibility": "UNKNOWN_NO_OBSERVED_METRICS" if not search else {"observed_records": search},
        "performance": "UNKNOWN_NO_OBSERVED_METRICS" if not performance else {"observed_records": performance},
        "content_gaps": {"atoms": len(gaps), "atoms_without_derivatives": max(len(gaps) - items_per_atom, 0)},
        "stale_assets": stale,
        "rights_expiry": {"expired": len(radar["expired"]), "expiring_30d": len(radar["expiring"]), "media_without_rights": len(radar["media_without_rights"])},
        "open_risks": risks,
        "brand_health": "AT_RISK" if risks else "OK",
    }


def portfolio_view(*, tenant_id: str, allowed_project_ids: Optional[Iterable[str]], now: Optional[datetime] = None) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    workspaces = list_project_workspaces(tenant_id, project_ids=allowed_project_ids)
    projects = []
    for workspace in workspaces:
        projects.append({
            "project_id": workspace.project_id,
            "display_name": workspace.display_name,
            "brand_name": workspace.brand_name,
            "lifecycle_state": workspace.lifecycle_state.value,
            **project_health(workspace.project_id, now=moment),
        })
    return {
        "tenant_id": tenant_id,
        "generated_at": moment.isoformat(),
        "projects": projects,
        "shared_resources": {
            "agency_memory": [
                {"memory_id": m.memory_id, "subject_key": m.subject_key, "authority": m.authority.value}
                for m in list_memory(tenant_id=tenant_id, project_id=None, scope="M0_AGENCY", status="ACTIVE")
            ],
            "provider_profiles": [p.profile_id for p in list_provider_profiles(tenant_id)],
            "workstream_templates": sorted(WORKSTREAMS),
        },
        "isolation": "per-project counts only; private memory, conversations and brand canon never cross projects",
    }
