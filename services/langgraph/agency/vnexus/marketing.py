"""VNEXUS marketing intelligence: brand strategy -> a measurable campaign plan, and honest reporting.

What this produces is a plan: segments, a campaign brief, a messaging
matrix, channel plans with asset variants, a content calendar, experiment
hypotheses with power calculations, measurement contracts and attribution
metadata. Publishing, ad spend and sending stay disabled; a calendar entry
is PLANNED, never scheduled into a live channel.

Three kinds of number are kept apart and labelled:

* MEASURED   values recorded with a named source (``vnexus_measurements``);
* COMPUTED   arithmetic over measured values or over inputs the requester
             gave (sample sizes, rates);
* SIMULATED  forecasts from stated assumptions. Never stored as measurements,
             never reported as performance.

Nothing here invents a segment, a proof point, a conversion rate, an
impression count or revenue. Missing proof is shown as NEEDS_PROOF.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from enum import Enum
from statistics import NormalDist
from typing import Any, Optional
from urllib.parse import quote

from pydantic import Field, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash

from .bridge import GenomeProjection
from .genome import _Strict

MARKETING_VERSION = "amc-vnexus-marketing/v1"
STAGES = ("awareness", "consideration", "conversion")


class EvidenceKind(str, Enum):
    RESEARCHED = "RESEARCHED"   # backed by a cited source
    ASSUMED = "ASSUMED"         # a working assumption, to be validated


class Segment(_Strict):
    segment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,40}$")
    name: str = Field(min_length=1, max_length=120)
    needs: tuple[str, ...] = Field(default=(), max_length=8)
    evidence: EvidenceKind = EvidenceKind.ASSUMED
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _evidence(self) -> "Segment":
        if self.evidence is EvidenceKind.RESEARCHED and not self.evidence_refs:
            raise ValueError("a RESEARCHED segment cites at least one source")
        return self


class ProofPoint(_Strict):
    claim: str = Field(min_length=1, max_length=300)
    source_ref: str = Field(min_length=1, max_length=300)


class Channel(str, Enum):
    SOCIAL_FEED = "social_feed"
    SOCIAL_STORY = "social_story"
    EMAIL = "email"
    WEB_LANDING = "web_landing"
    SEARCH = "search"
    VIDEO = "video"


CHANNEL_FORMATS: dict[Channel, list[dict[str, Any]]] = {
    Channel.SOCIAL_FEED: [{"preset": "social.square", "deliverable": "social_graphics"},
                          {"preset": "social.portrait_4x5", "deliverable": "social_graphics"}],
    Channel.SOCIAL_STORY: [{"preset": "social.story_9x16", "deliverable": "social_graphics"}],
    Channel.EMAIL: [{"preset": "web.open_graph", "deliverable": "social_graphics", "note": "header image"}],
    Channel.WEB_LANDING: [{"preset": None, "deliverable": "experience:LANDING_PAGE"}],
    Channel.SEARCH: [{"preset": None, "deliverable": "copy only (headline/description)"}],
    Channel.VIDEO: [{"preset": "video.landscape_16x9", "deliverable": "video"}],
}


class Metric(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    numerator_event: str = Field(min_length=1, max_length=60)
    denominator_event: Optional[str] = Field(default=None, max_length=60)
    source_system: str = Field(min_length=1, max_length=80)
    attribution_window_days: int = Field(default=7, ge=0, le=90)


class Hypothesis(_Strict):
    hypothesis_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,40}$")
    change: str = Field(min_length=1, max_length=300)
    segment_id: str
    metric: str
    rationale: str = Field(min_length=1, max_length=500)
    baseline_rate: Optional[float] = Field(default=None, gt=0, lt=1)       # only if the requester has a measured baseline
    baseline_source: Optional[str] = None
    minimum_detectable_lift: float = Field(default=0.1, gt=0, le=5)         # relative lift
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    power: float = Field(default=0.8, gt=0.5, lt=1)

    @model_validator(mode="after")
    def _baseline(self) -> "Hypothesis":
        if self.baseline_rate is not None and not self.baseline_source:
            raise ValueError("a baseline rate needs its measurement source")
        return self


class CampaignRequest(_Strict):
    campaign_ref: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,60}$")
    objective: str = Field(min_length=1, max_length=500)
    segments: tuple[Segment, ...] = Field(default=(), max_length=8)
    proof_points: tuple[ProofPoint, ...] = Field(default=(), max_length=12)
    channels: tuple[Channel, ...] = Field(min_length=1, max_length=6)
    start: date
    weeks: int = Field(default=4, ge=1, le=26)
    cadence_per_week: dict[Channel, int] = Field(default_factory=dict)
    metrics: tuple[Metric, ...] = Field(default=(), max_length=12)
    hypotheses: tuple[Hypothesis, ...] = Field(default=(), max_length=8)
    landing_url: Optional[str] = Field(default=None, max_length=300)
    budget_minor: Optional[int] = Field(default=None, ge=0)


def sample_size_per_arm(p1: float, lift: float, *, alpha: float, power: float) -> Optional[int]:
    """Two-proportion z-test, two-sided. COMPUTED from the requester's baseline; None when undefined."""
    p2 = p1 * (1 + lift)
    if not 0 < p2 < 1:
        return None
    z_a, z_b = NormalDist().inv_cdf(1 - alpha / 2), NormalDist().inv_cdf(power)
    pbar = (p1 + p2) / 2
    n = (z_a * math.sqrt(2 * pbar * (1 - pbar)) + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p2 - p1) ** 2
    return math.ceil(n)


def utm(campaign_ref: str, channel: Channel, content: str, base: Optional[str]) -> dict[str, Any]:
    params = {"utm_source": channel.value, "utm_medium": "owned" if channel in (Channel.EMAIL, Channel.WEB_LANDING) else "social"
              if channel in (Channel.SOCIAL_FEED, Channel.SOCIAL_STORY) else channel.value, "utm_campaign": campaign_ref,
              "utm_content": content}
    url = None
    if base:
        sep = "&" if "?" in base else "?"
        url = base + sep + "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())
    return {"params": params, "url": url}


def compile_campaign(p: GenomeProjection, req: CampaignRequest) -> dict[str, Any]:
    p = p.fresh()
    segments = list(req.segments)
    assumptions = []
    if not segments:
        audience = p.text("strategy.audience.primary")
        segments = [Segment(segment_id="primary", name=audience or "UNSTATED AUDIENCE", evidence=EvidenceKind.ASSUMED)]
        assumptions.append("no segments supplied; a single ASSUMED segment from the genome's primary audience")
    promise = p.text("strategy.positioning.promise")
    voice = p.get("verbal.voice.tone") or p.get("verbal.voice.register")
    brief = {"objective": req.objective, "segments": [s.segment_id for s in segments], "key_message": promise or "NEEDS_MESSAGE",
             "voice": voice, "mandatories": [f"genome:{k}" for k in sorted(p.used) if k.startswith(("visual.logo", "visual.color"))],
             "channels": [c.value for c in req.channels], "window": {"start": req.start.isoformat(), "weeks": req.weeks},
             "budget": {"amount_minor": req.budget_minor, "status": "PLANNING ONLY: spend is disabled"} if req.budget_minor is not None else None}
    matrix = []
    for s in segments:
        for stage in STAGES:
            proof = req.proof_points[(len(matrix)) % len(req.proof_points)] if req.proof_points and stage != "awareness" else None
            matrix.append({"segment_id": s.segment_id, "stage": stage, "message": promise or "NEEDS_MESSAGE",
                           "need_addressed": s.needs[0] if s.needs else "UNSTATED",
                           "proof": proof.model_dump() if proof else ("not required at awareness" if stage == "awareness" else "NEEDS_PROOF"),
                           "segment_evidence": s.evidence.value})
    channel_plans = []
    for ch in req.channels:
        variants = []
        for f in CHANNEL_FORMATS[ch]:
            for s in segments:
                content = f"{s.segment_id}-{(f['preset'] or 'copy').replace('.', '-')}"
                variants.append({"segment_id": s.segment_id, "format": f["preset"], "deliverable": f["deliverable"],
                                 "attribution": utm(req.campaign_ref, ch, content, req.landing_url)})
        channel_plans.append({"channel": ch.value, "variants": variants})
    calendar = []
    for ch in req.channels:
        per_week = req.cadence_per_week.get(ch, 1)
        for w in range(req.weeks):
            for k in range(per_week):
                day = req.start + timedelta(days=w * 7 + round(k * 7 / per_week))
                calendar.append({"date": day.isoformat(), "channel": ch.value, "status": "PLANNED", "publishing": "DISABLED"})
    calendar.sort(key=lambda e: (e["date"], e["channel"]))
    experiments = []
    seg_ids = {s.segment_id for s in segments}
    for h in req.hypotheses:
        if h.segment_id not in seg_ids:
            raise ValueError(f"hypothesis {h.hypothesis_id} names an unknown segment")
        n = sample_size_per_arm(h.baseline_rate, h.minimum_detectable_lift, alpha=h.alpha, power=h.power) if h.baseline_rate else None
        experiments.append({**h.model_dump(mode="json"), "statement": f"If {h.change}, {h.metric} for {h.segment_id} rises by at least "
                            f"{h.minimum_detectable_lift:.0%} because {h.rationale}",
                            "sample_size_per_arm": n, "sample_size_kind": "COMPUTED" if n else "NOT_COMPUTABLE: no measured baseline"})
    contracts = [{**m.model_dump(mode="json"), "definition": f"{m.numerator_event} / {m.denominator_event}" if m.denominator_event
                  else f"count({m.numerator_event})", "value_kind": "MEASURED only; no target is assumed"} for m in req.metrics]
    plan = {"version": MARKETING_VERSION, "campaign_ref": req.campaign_ref, "genome_ref": p.genome_ref, "brief": brief,
            "segments": [s.model_dump(mode="json") for s in segments], "messaging_matrix": matrix, "channel_plans": channel_plans,
            "content_calendar": calendar, "experiments": experiments, "measurement_contracts": contracts, "assumptions": assumptions,
            "external_effects": "none: publishing, sending and ad spend are disabled",
            "gaps": sorted({c["proof"] for c in matrix if c["proof"] == "NEEDS_PROOF"} | ({"NEEDS_MESSAGE"} if not promise else set()))}
    plan["plan_hash"] = canonical_hash(plan)
    return plan


def forecast(*, audience_size: int, assumed_rate: float, assumption_source: str) -> dict[str, Any]:
    """A SIMULATED projection from stated assumptions. It is not a prediction of performance and is never stored as data."""
    if not assumption_source.strip():
        raise ValueError("a forecast states where its assumed rate comes from")
    if not 0 < assumed_rate < 1 or audience_size <= 0:
        raise ValueError("audience_size > 0 and 0 < assumed_rate < 1")
    expected = audience_size * assumed_rate
    sd = math.sqrt(audience_size * assumed_rate * (1 - assumed_rate))
    return {"kind": "SIMULATED", "expected_conversions": round(expected, 1), "interval_95": [max(0.0, round(expected - 1.96 * sd, 1)),
            round(expected + 1.96 * sd, 1)], "assumptions": {"audience_size": audience_size, "assumed_rate": assumed_rate,
                                                              "source": assumption_source},
            "label": "SIMULATION from stated assumptions; not measured performance"}


def report(plan: dict[str, Any], measurements: list[dict[str, Any]]) -> dict[str, Any]:
    """Measured values per metric with sources; rates only where both events were measured."""
    by_metric: dict[str, list[dict[str, Any]]] = {}
    for m in measurements:
        by_metric.setdefault(m["metric"], []).append(m)
    rows = []
    for c in plan["measurement_contracts"]:
        num = by_metric.get(c["numerator_event"], [])
        den = by_metric.get(c["denominator_event"], []) if c.get("denominator_event") else []
        n_total = sum(float(x["value"]) for x in num)
        row = {"metric": c["name"], "numerator": {"event": c["numerator_event"], "value": n_total if num else None,
                                                 "sources": sorted({x["source"] for x in num})}}
        if c.get("denominator_event"):
            d_total = sum(float(x["value"]) for x in den)
            row["denominator"] = {"event": c["denominator_event"], "value": d_total if den else None, "sources": sorted({x["source"] for x in den})}
            row["rate"] = round(n_total / d_total, 6) if num and den and d_total > 0 else None
            row["rate_kind"] = "COMPUTED from MEASURED values" if row["rate"] is not None else "NOT_MEASURED"
        else:
            row["value_kind"] = "MEASURED" if num else "NOT_MEASURED"
        rows.append(row)
    return {"campaign_ref": plan["campaign_ref"], "metrics": rows, "measurement_count": len(measurements),
            "note": "only recorded measurements with a named source appear here; forecasts are excluded"}


__all__ = ["CHANNEL_FORMATS", "CampaignRequest", "Channel", "EvidenceKind", "Hypothesis", "MARKETING_VERSION", "Metric", "ProofPoint",
           "Segment", "compile_campaign", "forecast", "report", "sample_size_per_arm", "utm"]
