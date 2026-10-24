"""How each catalog module maps onto what the repository already owns.

The catalog names agency job titles (``owner_role``); the repository's authority
is the 13 N3 role contracts and the N1 artifact types. Every module binds to one
N3 role that is allowed to produce the module's N1 artifact type (checked by
``verify_bindings`` against N3 ``produces``), and says how close that binding is:

* ``EXACT``      - the N3 role's department is the catalog role's discipline;
* ``NEAREST``    - an N3 role produces the artifact type, but its mandate is
                   narrower or adjacent to the catalog role;
* ``NO_N3_ROLE`` - no N3 department covers the discipline; the nearest producer
                   of the artifact type is named and the gap is reported.

``capability`` is what the repository can actually do for the module's work
today. It is descriptive, never permission: ``LOCAL_AVAILABLE`` work still runs
only through the execution fabric or the named native owner, ``DRY_RUN_ONLY``
and ``PLANNING_ONLY`` never dispatch, and ``PROVIDER_GAP`` means no adapter
exists. ``external_effect`` names the live action a module's work could lead to;
every one of them stays disabled (publication dry-run, paid media planning-only,
no CRM send, no outreach).
"""

from __future__ import annotations

from dataclasses import dataclass

from services.langgraph.agency.kernel.ontology import ArtifactType
from services.langgraph.agency.kernel.roles import ROLE_REGISTRY

from .catalog import Catalog

COVERAGE = ("EXACT", "NEAREST", "NO_N3_ROLE")
CAPABILITY = ("LOCAL_AVAILABLE", "DRY_RUN_ONLY", "PLANNING_ONLY", "HUMAN_ONLY", "PROVIDER_GAP")
EXTERNAL_EFFECTS = ("none", "publish", "spend", "send", "outreach")


@dataclass(frozen=True)
class ModuleBinding:
    module_id: str
    n3_role: str
    artifact_type: str
    coverage: str
    native_owner: str
    capability: str
    external_effect: str
    note: str


_B = ModuleBinding
MODULE_BINDINGS: dict[str, ModuleBinding] = {b.module_id: b for b in (
    _B("AGM-01", "market_researcher", "research_brief", "NEAREST", "project_os.knowledge + agency_kernel.evidence",
       "HUMAN_ONLY", "none", "Discovery interviews and the brief are human work; sources enter the knowledge pipeline for review."),
    _B("AGM-02", "market_researcher", "market_analysis", "EXACT", "project_os.knowledge + agency_kernel.evidence",
       "HUMAN_ONLY", "none", "Market sizing is evidence with stated assumptions; no search-demand provider exists (PROVIDER_GAP for automated demand data)."),
    _B("AGM-03", "market_researcher", "research_brief", "EXACT", "project_os.knowledge + agency_kernel.evidence",
       "HUMAN_ONLY", "none", "Voice-of-customer research needs consented sources; nothing is scraped."),
    _B("AGM-04", "market_researcher", "market_analysis", "EXACT", "project_os.knowledge + agency_kernel.evidence",
       "HUMAN_ONLY", "none", "Competitor profiles are reviewed evidence, not inferred facts."),
    _B("AGM-05", "brand_strategist", "offer_definition", "EXACT", "agency_kernel.decisions",
       "HUMAN_ONLY", "none", "Offer and pricing decisions are kernel decisions with alternatives and an approver."),
    _B("AGM-06", "brand_strategist", "positioning_statement", "EXACT", "agency_kernel.decisions + vnexus.genome",
       "HUMAN_ONLY", "none", "Approved positioning feeds the VNEXUS brand genome through its own review."),
    _B("AGM-07", "brand_architect", "brand_platform", "NEAREST", "agency_kernel.decisions + vnexus.genome",
       "HUMAN_ONLY", "none", "Messaging architecture and the claim register; drafting has no text provider (PROVIDER_GAP for llm drafting)."),
    _B("AGM-08", "design_lead", "design_system_spec", "NEAREST", "foundry + design_tokens + vnexus.genome",
       "LOCAL_AVAILABLE", "none", "Deterministic SVG identity and DTCG tokens run locally; raster/video depend on Chromium/FFmpeg probes."),
    _B("AGM-09", "design_lead", "design_brief", "NEAREST", "ui_ux compiler + agency_kernel.decisions",
       "HUMAN_ONLY", "none", "Journey map and service blueprint are decisions recorded with evidence."),
    _B("AGM-10", "implementation_lead", "app_build_spec", "NEAREST", "ui_ux compiler + foundry.experience + execution_fabric",
       "LOCAL_AVAILABLE", "none", "UI/UX spec compiles locally; the experience twin and WCAG audit run on local Chromium when present."),
    _B("AGM-11", "brand_safety_reviewer", "qa_report", "NO_N3_ROLE", "execution_fabric.seo_checks",
       "LOCAL_AVAILABLE", "none", "No N3 search role exists; local SEO checks run in the fabric. Rankings and AI citations are never promised."),
    _B("AGM-12", "copywriter", "copy_variant", "NEAREST", "project_os.content + project_os.calendar",
       "LOCAL_AVAILABLE", "none", "Content atoms and the calendar are native; drafting text has no provider (PROVIDER_GAP)."),
    _B("AGM-13", "growth_lead", "campaign_package", "NEAREST", "project_os.publishing (dry run)",
       "DRY_RUN_ONLY", "publish", "Social publication is dry-run only; the live registry ships empty."),
    _B("AGM-14", "media_planner", "media_plan", "EXACT", "project_os.paid_media (planning only)",
       "PLANNING_ONLY", "spend", "Paid media is planning-only; no spend executor exists."),
    _B("AGM-15", "implementation_lead", "automation_spec", "NEAREST", "project_os CRM journeys + scheduler (dry run)",
       "DRY_RUN_ONLY", "send", "Lifecycle journeys run as dry-run receipts; no email or message is sent."),
    _B("AGM-16", "growth_lead", "campaign_package", "NO_N3_ROLE", "agency_kernel.decisions",
       "PLANNING_ONLY", "outreach", "No N3 partnerships role; outreach is never dispatched."),
    _B("AGM-17", "copywriter", "copy_variant", "NO_N3_ROLE", "project_os.publishing (dry run)",
       "DRY_RUN_ONLY", "publish", "No N3 communications role; PR and social proof need consent and substantiation records."),
    _B("AGM-18", "analytics_lead", "measurement_plan", "EXACT", "analytics events + measurement plan",
       "LOCAL_AVAILABLE", "none", "First-party events and the measurement plan are native; baselines start NOT_MEASURED."),
    _B("AGM-19", "analytics_lead", "measurement_plan", "NEAREST", "project_os growth experiments",
       "LOCAL_AVAILABLE", "none", "Experiments are registered and concluded only from observed results."),
    _B("AGM-20", "release_manager", "release_record", "NEAREST", "delivery release candidate + approvals",
       "HUMAN_ONLY", "publish", "A sealed candidate and an approval are not permission to publish, spend or send."),
    _B("AGM-21", "analytics_lead", "measurement_plan", "NEAREST", "learning ledger + experiments",
       "LOCAL_AVAILABLE", "none", "Retention cohorts need measured data; unknown baselines stay NOT_MEASURED."),
    _B("AGM-22", "brand_safety_reviewer", "qa_report", "NO_N3_ROLE", "model profiles + provider capability registry",
       "LOCAL_AVAILABLE", "none", "No N3 AI-governance role; degraded generation stays blocked from release."),
    _B("AGM-23", "implementation_lead", "implementation_plan", "NO_N3_ROLE", "agency_kernel.decisions + approvals",
       "HUMAN_ONLY", "none", "No N3 client-operations role; scope and approval matrices are human decisions."),
    _B("AGM-24", "brand_safety_reviewer", "qa_report", "NEAREST", "execution_fabric.wcag_audit + security tests",
       "LOCAL_AVAILABLE", "none", "WCAG DOM audit runs locally; legal applicability and conformance need human review."),
)}


def binding(module_id: str) -> ModuleBinding:
    return MODULE_BINDINGS[module_id]


def verify_bindings(catalog: Catalog) -> list[str]:
    """Problems with the bindings; empty means every module binds to a real producer."""
    problems: list[str] = []
    artifact_types = {a.value for a in ArtifactType}
    if set(MODULE_BINDINGS) != {m.module_id for m in catalog.modules}:
        problems.append("bindings do not cover exactly the catalog's modules")
    for b in MODULE_BINDINGS.values():
        role = ROLE_REGISTRY.get(b.n3_role)
        if role is None:
            problems.append(f"{b.module_id}: unknown N3 role {b.n3_role}")
            continue
        if b.artifact_type not in artifact_types:
            problems.append(f"{b.module_id}: unknown N1 artifact type {b.artifact_type}")
        if b.artifact_type not in {getattr(p, "value", p) for p in role.produces}:
            problems.append(f"{b.module_id}: {b.n3_role} may not produce {b.artifact_type}")
        if b.coverage not in COVERAGE or b.capability not in CAPABILITY or b.external_effect not in EXTERNAL_EFFECTS:
            problems.append(f"{b.module_id}: invalid coverage/capability/effect label")
    return problems


def coverage_report() -> dict[str, list[str]]:
    report: dict[str, list[str]] = {c: [] for c in COVERAGE}
    for b in MODULE_BINDINGS.values():
        report[b.coverage].append(b.module_id)
    return report


__all__ = ["CAPABILITY", "COVERAGE", "EXTERNAL_EFFECTS", "MODULE_BINDINGS", "ModuleBinding", "binding",
           "coverage_report", "verify_bindings"]
