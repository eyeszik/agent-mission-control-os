"""Route registry for the direction pipeline: what may generate, critique or research, and on what terms.

Every hosted route named in the proposal (Cloudflare Workers AI text-to-image, an image-capable Gemini critique,
Exa or Tavily research, optional Groq text) is declared here with ``adapter_implemented=False``. There is no client
code for any of them: their capabilities, quotas, prices, terms and data handling have not been rechecked against
official sources for this account, and research is discovery evidence, not entitlement. A disabled route is never
quoted, never called and never silently replaced by another model.

Spend is governed by ``AMC_VNEXUS_SPEND_MODE`` (``zero`` by default). In zero mode a route whose price is unknown or
non-zero is refused and the caller is offered the manual handoff route; nothing switches over on its own. The only
approved fallback for any generation route is ``manual.handoff`` and it is offered, never executed automatically.

Credential references are environment variable NAMES. Only their presence is ever reported; values are never read
into a record, a response or telemetry.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Optional


from ..genome import _Strict

REGISTRY_VERSION = "amc-vnexus-direction-routes/v1"


class Task(str, Enum):
    TEXT_TO_IMAGE = "TEXT_TO_IMAGE"
    CONCEPT_COMPOSE = "CONCEPT_COMPOSE"        # deterministic local vector concepts from the genome
    MANUAL_HANDOFF = "MANUAL_HANDOFF"          # export the prompt package, import results with labelled provenance
    IMAGE_CRITIQUE = "IMAGE_CRITIQUE"
    LOCAL_MEASURE = "LOCAL_MEASURE"
    VECTOR_RECONSTRUCT = "VECTOR_RECONSTRUCT"
    RESEARCH = "RESEARCH"
    TEXT = "TEXT"
    SIMULATED = "SIMULATED"


class Health(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"


class RouteSpec(_Strict):
    route_id: str
    provider: str
    model: Optional[str] = None
    model_pin: Optional[str] = None
    tasks: tuple[Task, ...]
    formats_in: tuple[str, ...] = ()
    formats_out: tuple[str, ...] = ()
    credential_ref: Optional[str] = None          # env var name; presence only
    quota_scope: str = "UNVERIFIED"
    quota_reset: Optional[str] = None
    price_per_job_minor: Optional[int] = None     # None = UNKNOWN; never assumed free
    currency: str = "USD"
    pricing_source: Optional[str] = None
    pricing_checked_at: Optional[str] = None
    data_policy: str = "UNVERIFIED"               # ELIGIBLE | NOT_ELIGIBLE | UNVERIFIED
    max_requests_per_minute: int = 0
    max_payload_bytes: int = 0
    timeout_s: int = 0
    reconciliation: str = "none"
    fallback_routes: tuple[str, ...] = ()
    adapter_implemented: bool
    note: str = ""


_UNVERIFIED_HOSTED = ("ADAPTER_NOT_IMPLEMENTED", "ENTITLEMENT_UNVERIFIED: capabilities, quota, price, terms and data "
                      "handling not rechecked against official sources for this account")

ROUTES: tuple[RouteSpec, ...] = (
    RouteSpec(route_id="local.foundry_compose", provider="local", model="foundry.compose", model_pin="amc-foundry-compose",
              tasks=(Task.CONCEPT_COMPOSE,), formats_out=("image/svg+xml",), quota_scope="local compute", price_per_job_minor=0,
              pricing_source="local renderer: no charge", data_policy="ELIGIBLE", max_requests_per_minute=30,
              max_payload_bytes=2_000_000, timeout_s=10, reconciliation="media job idempotency key per slot",
              fallback_routes=("manual.handoff",), adapter_implemented=True,
              note="deterministic vector mark concepts composed from the approved genome; logo and icon roles only"),
    RouteSpec(route_id="manual.handoff", provider="operator", tasks=(Task.MANUAL_HANDOFF,),
              formats_in=("image/png", "image/svg+xml"), formats_out=("application/json",), quota_scope="none",
              price_per_job_minor=0, pricing_source="no provider call is made by this server", data_policy="ELIGIBLE",
              max_payload_bytes=12_000_000, reconciliation="import idempotency key", adapter_implemented=True,
              note="prompt package export and result import; imported provenance stays USER_REPORTED (unverified)"),
    RouteSpec(route_id="local.measure", provider="local", model="vnexus.directions.review", model_pin="amc-vnexus-review-rubric/1.0.0",
              tasks=(Task.LOCAL_MEASURE,), formats_in=("image/png", "image/svg+xml"), price_per_job_minor=0,
              pricing_source="local compute", data_policy="ELIGIBLE", adapter_implemented=True,
              note="deterministic measurements on stored bytes (palette, contrast, small-size, geometry); never creative scores"),
    RouteSpec(route_id="local.trace", provider="local", model="avic.optimize", model_pin="avic-h1-region-split",
              tasks=(Task.VECTOR_RECONSTRUCT,), formats_in=("image/png",), formats_out=("image/svg+xml",), price_per_job_minor=0,
              pricing_source="local compute", data_policy="ELIGIBLE", adapter_implemented=True,
              note="controlled region-split trace snapped to the approved palette; fidelity is measured in local Chromium"),
    RouteSpec(route_id="cloudflare.workers_ai.text_to_image", provider="cloudflare", tasks=(Task.TEXT_TO_IMAGE,),
              formats_out=("image/png",), credential_ref="CLOUDFLARE_API_TOKEN", fallback_routes=("manual.handoff",),
              adapter_implemented=False, note="proposed concept route; DISABLED until a verified adapter and entitlement exist"),
    RouteSpec(route_id="gemini.image_critique", provider="google", tasks=(Task.IMAGE_CRITIQUE,), formats_in=("image/png",),
              credential_ref="GEMINI_API_KEY", adapter_implemented=False,
              note="the model router has no image-input path; rendered-image critique needs a verified adapter"),
    RouteSpec(route_id="exa.research", provider="exa", tasks=(Task.RESEARCH,), credential_ref="EXA_API_KEY", adapter_implemented=False,
              note="one of Exa or Tavily, not both, once workload justifies it"),
    RouteSpec(route_id="tavily.research", provider="tavily", tasks=(Task.RESEARCH,), credential_ref="TAVILY_API_KEY",
              adapter_implemented=False, note="one of Exa or Tavily, not both, once workload justifies it"),
    RouteSpec(route_id="groq.text", provider="groq", tasks=(Task.TEXT,), credential_ref="GROQ_API_KEY", adapter_implemented=False,
              note="optional text/transcription route; only if measured workload justifies it"),
    RouteSpec(route_id="mock.simulated", provider="test", tasks=(Task.SIMULATED,), formats_out=("image/svg+xml",), price_per_job_minor=0,
              pricing_source="test stand-in", data_policy="ELIGIBLE", adapter_implemented=True,
              note="AMC_VNEXUS_MOCK_PROVIDERS=1 outside production only; output is SIMULATED and never selectable"),
)

_BY_ID = {r.route_id: r for r in ROUTES}


def spend_mode() -> str:
    mode = (os.environ.get("AMC_VNEXUS_SPEND_MODE") or "zero").strip().lower()
    return mode if mode in ("zero", "approval_required") else "zero"


def get_route(route_id: str) -> RouteSpec:
    if route_id not in _BY_ID:
        raise LookupError(f"unknown route {route_id}")
    return _BY_ID[route_id]


def health(route: RouteSpec) -> tuple[Health, tuple[str, ...]]:
    blockers: list[str] = []
    if not route.adapter_implemented:
        blockers += list(_UNVERIFIED_HOSTED)
        if route.credential_ref and not os.environ.get(route.credential_ref):
            blockers.append(f"CREDENTIAL_NOT_CONFIGURED: {route.credential_ref}")
        return Health.DISABLED, tuple(blockers)
    if route.route_id == "mock.simulated":
        from ..media_fabric import mock_enabled

        return (Health.AVAILABLE, ()) if mock_enabled() else (Health.DISABLED, ("MOCK_PROVIDERS_DISABLED",))
    if route.route_id == "local.trace":
        from services.langgraph.agency.visual.browser import probe_browser

        probe = probe_browser()
        if not probe.get("available"):
            # Tracing still runs; fidelity cannot be measured, so reconstructions stay NOT_VERIFIED.
            return Health.AVAILABLE, tuple(["FIDELITY_NOT_MEASURABLE: " + ", ".join(probe.get("blockers", []))])
    return Health.AVAILABLE, ()


class RouteDecision(_Strict):
    route_id: str
    allowed: bool
    health: Health
    blockers: tuple[str, ...] = ()
    estimate_minor: Optional[int] = None
    spend_mode: str
    offer: Optional[str] = None
    note: str = ""


def decide(route_id: str, task: Task, *, budget_minor: int) -> RouteDecision:
    """May this pinned route run this task now? Never picks a different route; offers manual handoff instead."""
    route = get_route(route_id)
    mode = spend_mode()
    state, blockers = health(route)
    reasons = [b for b in blockers if not b.startswith("FIDELITY_NOT_MEASURABLE")]
    if task not in route.tasks:
        reasons.append(f"TASK_UNSUPPORTED: {route_id} does not perform {task.value}")
    price = route.price_per_job_minor
    if price is None:
        reasons.append("PRICE_UNKNOWN: a route without a verified price is never run" + (" in zero-spend mode" if mode == "zero" else ""))
    elif price > 0 and mode == "zero":
        reasons.append(f"ZERO_SPEND: {route_id} costs {price} minor units per job")
    elif price > budget_minor and price > 0:
        reasons.append(f"BUDGET_EXCEEDED: {price} > {budget_minor}")
    allowed = state is Health.AVAILABLE and not reasons
    offer = None
    if not allowed and "manual.handoff" in route.fallback_routes:
        offer = "manual.handoff"
    return RouteDecision(route_id=route_id, allowed=allowed, health=state, blockers=tuple(reasons), estimate_minor=price,
                         spend_mode=mode, offer=offer,
                         note="" if allowed else "nothing was called; no other model was substituted")


def describe() -> dict[str, Any]:
    rows = []
    for r in ROUTES:
        state, blockers = health(r)
        row = r.model_dump(mode="json")
        row.update({"health": state.value, "blockers": list(blockers),
                    "credential_present": bool(r.credential_ref and os.environ.get(r.credential_ref))})
        rows.append(row)
    return {"registry_version": REGISTRY_VERSION, "spend_mode": spend_mode(), "routes": rows,
            "notes": ["Connection managers (e.g. Nango) manage connections, not generation rights.",
                      "A chat subscription does not include arbitrary API usage.",
                      "Free-credit directories are discovery catalogs, not pooled balances.",
                      "No browser automation or quota circumvention is implemented."]}


__all__ = ["Health", "REGISTRY_VERSION", "ROUTES", "RouteDecision", "RouteSpec", "Task", "decide", "describe", "get_route", "health",
           "spend_mode"]
