"""KPI definitions and their evaluation for a plan.

A KPI has an explicit formula over named inputs, a unit, a time window, a source
and a privacy class. Inputs come only from measurement observations recorded as
N4 kernel evidence (``evidence_type = "measurement"`` with
``payload = {"metric_input", "value", "unit", "window"}``) in the plan's project,
plus the plan's own audit events for delivery rework. A missing input, a zero
denominator or an unusable observation is ``NOT_MEASURED`` with the reason; a
value computed from synthetic inputs is labelled ``SYNTHETIC`` and is never a
client result. No benchmark or target is invented.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from services.langgraph.security.auth import Principal

from .engine import NOT_MEASURED
from .refs import _origin_for_source


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    category: str
    label: str
    unit: str
    numerator: str
    denominator: str | None
    inputs: tuple[str, ...]
    window: str
    source: str
    privacy: str
    caveat: str
    compute: Callable[[dict[str, float]], float | None]


def _ratio(num: str, den: str) -> Callable[[dict[str, float]], float | None]:
    return lambda v: None if not v.get(den) else v[num] / v[den]


def _ltv(v: dict[str, float]) -> float | None:
    if not v.get("churn_rate_monthly"):
        return None
    return v["arpa_monthly"] * v["gross_margin_ratio"] / v["churn_rate_monthly"]


def _payback(v: dict[str, float]) -> float | None:
    per_month = v.get("arpa_monthly", 0) * v.get("gross_margin_ratio", 0)
    if not per_month or not v.get("new_customers"):
        return None
    return (v["acquisition_spend"] / v["new_customers"]) / per_month


def _margin(v: dict[str, float]) -> float | None:
    if not v.get("revenue"):
        return None
    return (v["revenue"] - v["variable_costs"]) / v["revenue"]


_M = MetricDefinition
DEFINITIONS: tuple[MetricDefinition, ...] = (
    _M("awareness.qualified_reach", "awareness", "Qualified reach", "people", "unique people reached in the target segment",
       None, ("qualified_reach",), "calendar month", "platform reports (de-duplicated)", "aggregate",
       "Platform reach is modelled by the platform; it is not a count of verified people.", lambda v: v.get("qualified_reach")),
    _M("acquisition.qualified_leads", "acquisition", "Qualified leads", "leads", "leads meeting the agreed qualification rule",
       None, ("qualified_leads",), "calendar month", "CRM (consented contacts)", "personal data in source; aggregate here",
       "Bot and duplicate submissions must be excluded at the source.", lambda v: v.get("qualified_leads")),
    _M("acquisition.conversion_rate", "acquisition", "Conversion rate", "ratio", "conversions", "eligible sessions",
       ("conversions", "eligible_sessions"), "calendar month", "first-party analytics", "aggregate",
       "Session definitions differ between tools; compare only within one tool.", _ratio("conversions", "eligible_sessions")),
    _M("acquisition.cost_per_lead", "acquisition", "Cost per qualified lead", "currency", "acquisition spend", "qualified leads",
       ("acquisition_spend", "qualified_leads"), "calendar month", "finance ledger + CRM", "aggregate",
       "Spend must use one currency and the same window as the leads.", _ratio("acquisition_spend", "qualified_leads")),
    _M("sales.new_customer_revenue", "sales", "New-customer revenue", "currency", "revenue from first purchases or contracts",
       None, ("new_customer_revenue",), "calendar month", "finance ledger", "aggregate",
       "Recognised revenue, not bookings, unless stated.", lambda v: v.get("new_customer_revenue")),
    _M("sales.cac", "sales", "Customer acquisition cost", "currency", "acquisition spend", "new customers",
       ("acquisition_spend", "new_customers"), "calendar month", "finance ledger + CRM", "aggregate",
       "Attribution of spend to customers is model-dependent.", _ratio("acquisition_spend", "new_customers")),
    _M("sales.payback_months", "sales", "CAC payback", "months", "CAC", "monthly gross margin per customer",
       ("acquisition_spend", "new_customers", "arpa_monthly", "gross_margin_ratio"), "trailing 3 months",
       "finance ledger", "aggregate", "Assumes stable margin and revenue per account.", _payback),
    _M("brand.awareness_rate", "brand", "Aided brand awareness", "ratio", "respondents aware of the brand", "respondents surveyed",
       ("aware_respondents", "surveyed_respondents"), "survey wave", "consented brand survey", "aggregate",
       "Survey samples have sampling error; report the sample size.", _ratio("aware_respondents", "surveyed_respondents")),
    _M("retention.cohort_survival", "retention", "Cohort survival", "ratio", "cohort members still active", "cohort size",
       ("cohort_active", "cohort_size"), "per cohort, at the stated age", "product/CRM data", "aggregate",
       "Define 'active' once and keep it fixed across cohorts.", _ratio("cohort_active", "cohort_size")),
    _M("retention.churn_rate_monthly", "retention", "Monthly churn", "ratio", "customers lost in the month", "customers at month start",
       ("churned_customers", "customers_at_start"), "calendar month", "billing/CRM", "aggregate",
       "Exclude involuntary churn only if the rule is stated.", _ratio("churned_customers", "customers_at_start")),
    _M("profitability.contribution_margin", "profitability", "Contribution margin", "ratio", "revenue minus variable costs", "revenue",
       ("revenue", "variable_costs"), "calendar month", "finance ledger", "aggregate",
       "Variable-cost allocation must be stated.", _margin),
    _M("profitability.ltv", "profitability", "Customer lifetime value", "currency", "monthly revenue per account x gross margin",
       "monthly churn rate", ("arpa_monthly", "gross_margin_ratio", "churn_rate_monthly"), "trailing 3 months",
       "finance ledger + billing", "aggregate", "A steady-state model; meaningless with very low churn samples.", _ltv),
    _M("delivery.approval_rework_rate", "delivery", "Approval rework rate", "ratio", "task approvals rejected",
       "task approvals decided", ("approvals_rejected", "approvals_decided"), "plan lifetime", "plan audit events", "none",
       "Counts approval decisions on this plan's tasks only.", _ratio("approvals_rejected", "approvals_decided")),
)


def definitions() -> list[dict[str, Any]]:
    return [{k: getattr(d, k) for k in ("metric_id", "category", "label", "unit", "numerator", "denominator", "window",
                                         "source", "privacy", "caveat")} | {"inputs": list(d.inputs)} for d in DEFINITIONS]


def evaluate(observations: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute every KPI from ``{input_name: {value, origin, window, ref}}``."""
    out = []
    for d in DEFINITIONS:
        missing = [name for name in d.inputs if name not in observations]
        base = {"metric_id": d.metric_id, "category": d.category, "label": d.label, "unit": d.unit}
        if missing:
            out.append({**base, "value": NOT_MEASURED, "reason": f"no measured input for {', '.join(missing)}",
                        "inputs": [], "origin": None})
            continue
        values = {name: float(observations[name]["value"]) for name in d.inputs}
        value = d.compute(values)
        origins = {observations[name]["origin"] for name in d.inputs}
        refs = [observations[name]["ref"] for name in d.inputs]
        if value is None:
            out.append({**base, "value": NOT_MEASURED, "reason": "denominator is zero", "inputs": refs,
                        "origin": None})
            continue
        origin = "SYNTHETIC" if "SYNTHETIC" in origins else ("MEASURED" if origins <= {"CUSTOMER_SOURCED", "INTERNAL_RECORD", "PUBLIC_SOURCE"} else "MIXED")
        windows = sorted({str(observations[name].get("window")) for name in d.inputs})
        out.append({**base, "value": round(value, 6), "reason": None, "inputs": refs, "origin": origin,
                    "windows": windows, "window_consistent": len(windows) == 1})
    return out


def _measurement_observations(tenant_id: str, project_id: str) -> dict[str, dict[str, Any]]:
    from services.langgraph.persistence.database import decode_json, table, transaction

    with transaction() as db:
        rows = db.execute(
            f"""SELECT * FROM {table('agency_evidence')} WHERE tenant_id = ? AND project_id = ? AND evidence_type = 'measurement'
                ORDER BY collected_at""",
            (tenant_id, project_id),
        ).fetchall()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = decode_json(row["payload"], {}) or {}
        name, value = payload.get("metric_input"), payload.get("value")
        if not isinstance(name, str) or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if str(row["epistemic_status"]) in {"stale", "conflict", "blocked"}:
            continue
        latest[name] = {"value": value, "origin": _origin_for_source(row["source_ref"], "first_party"),
                        "window": payload.get("window"), "ref": f"evidence:{row['evidence_id']}"}
    return latest


def _delivery_observations(project_id: str, plan_id: str) -> dict[str, dict[str, Any]]:
    from services.langgraph.persistence.operating_framework import framework_events

    events = framework_events(project_id, plan_id, limit=1000)
    approved = sum(1 for e in events if (e.get("payload") or {}).get("kind") == "agency_framework.approved")
    rejected = sum(1 for e in events if (e.get("payload") or {}).get("kind") == "agency_framework.approval_rejected")
    ref = f"agency-plan:{plan_id}:audit"
    return {"approvals_rejected": {"value": rejected, "origin": "INTERNAL_RECORD", "window": "plan", "ref": ref},
            "approvals_decided": {"value": approved + rejected, "origin": "INTERNAL_RECORD", "window": "plan", "ref": ref}}


def plan_metrics(principal: Principal, plan_id: str) -> dict[str, Any]:
    from .service import _plan_for

    plan = _plan_for(principal, plan_id)
    observations = _measurement_observations(plan["tenant_id"], plan["project_id"]) | _delivery_observations(plan["project_id"], plan_id)
    results = evaluate(observations)
    return {"plan_id": plan_id, "metrics": results,
            "measured": sum(1 for r in results if r["value"] != NOT_MEASURED),
            "not_measured": sum(1 for r in results if r["value"] == NOT_MEASURED)}


__all__ = ["DEFINITIONS", "MetricDefinition", "definitions", "evaluate", "plan_metrics"]
