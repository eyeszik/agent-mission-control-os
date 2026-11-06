"""Creative Search Runtime: bounded, receipted, human-gated.

    brief -> MissionIR -> ExecutionPlan -> context portfolio -> candidate(s)
          -> hard gate -> blind critics -> Pareto front -> HUMAN action
          -> <=1 correction -> TriDiff -> existing approval (subject_hash)
          -> delivery gate

What it deliberately does not do:

- change the LangGraph agency topology or add persistence: HITL reuses the
  existing ``approvals`` table (``create_approval_request`` with
  ``subject_hash`` = the final ArtifactIR hash) and an ordinary ``runs`` row
  (pipeline ``creative-runtime/v1``); no migration;
- call a model or any provider. Generation is deterministic composition of
  supplied, verified content; model-backed capabilities are PROVIDER_GAP and
  their plans are BLOCKED rather than simulated;
- publish, deploy, send or spend. "Delivery" here is an internal gate verdict;
  the gate can only say whether a human approval binds this exact artifact.

State machine (``CreativeRun.state``):

    HITL_REQUIRED | CONTRADICTORY_CONSTRAINTS | BLOCKED | BUDGET_EXHAUSTED  (stop)
    AWAITING_SELECTION --SELECT--> AWAITING_APPROVAL --approval+gate--> APPROVED_FOR_DELIVERY
                       --REQUEST_VARIATION--> AWAITING_SELECTION (within budget)
                       --REJECT_ALL--> REJECTED
                       --RETURN_TO_BRIEF--> RETURNED_TO_BRIEF
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, Iterable, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.langgraph.agency.execution.canonical import canonical_hash

from .capabilities import RegistryLoad, default_registry
from .context import ContextPortfolio, derive_requirements, select_context
from .critics import (
    EVALUATOR_VERSIONS,
    ConstraintValidator,
    Evaluation,
    Feasibility,
    aggregate,
    blind_view,
    run_critics,
)
from .generators import generate_design_system, generate_logo
from .ir import (
    MANDATORY_PROVENANCE,
    ArtifactIR,
    ConceptSpec,
    EvidenceEnvelope,
    MissionIR,
    seal_artifact,
)
from . import landing as landing_mod
from .ir import ConstraintKind
from .mission import INTERFACE_TYPES, MissionCompilation, compile_mission, mission_constraint
from .organization import ExecutionPlan, compile_plan
from .recorder import FlightEvent, FlightRecorder
from .search import (
    DEFAULT_CONCEPT,
    AxisName,
    MutationSpec,
    NoveltyReservoir,
    ObjectiveEstimate,
    concept_candidates,
    detect_collapse,
    fingerprint,
    mutate,
    pareto_front,
)
from .tridiff import TriDiff, tri_diff

RUNTIME_VERSION = "amc-creative-runtime/v1"
PIPELINE = "creative-runtime/v1"
APPROVAL_POLICY_VERSION = "amc-creative-approval/v1"
PROVIDER_CONFIG_REF = "deterministic:amc-creative/v1 (no model provider)"
LANDING_TYPES = frozenset({"landing_page", "marketing_site"})
# Finding code -> renderer requirement that repairs it (scope "style").
_STYLE_REPAIRS = {
    "MOTION_WITHOUT_REDUCED_MOTION_GUARD": "reduced_motion",
    "FOCUS_STYLE_NOT_DECLARED": "visible_focus",
    "TARGET_SIZE_UNVERIFIED": "target_size_24",
}

RunState = Literal[
    "HITL_REQUIRED", "CONTRADICTORY_CONSTRAINTS", "BLOCKED", "BUDGET_EXHAUSTED", "AWAITING_SELECTION",
    "AWAITING_APPROVAL", "APPROVED_FOR_DELIVERY", "REJECTED", "RETURNED_TO_BRIEF",
]
TERMINAL_STATUS = {
    "AWAITING_SELECTION": "READY_FOR_HUMAN_REVIEW", "AWAITING_APPROVAL": "READY_FOR_HUMAN_REVIEW",
    "APPROVED_FOR_DELIVERY": "READY_FOR_HUMAN_REVIEW", "BUDGET_EXHAUSTED": "PARTIAL", "HITL_REQUIRED": "BLOCKED",
    "CONTRADICTORY_CONSTRAINTS": "BLOCKED", "BLOCKED": "BLOCKED", "REJECTED": "BLOCKED", "RETURNED_TO_BRIEF": "BLOCKED",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActionNotAllowed(ValueError):
    code = "ACTION_NOT_ALLOWED"


class Candidate(_Strict):
    candidate_id: str
    generation: int = Field(ge=1, le=2)
    concept: Optional[ConceptSpec] = None
    parent_id: Optional[str] = None
    mutation: Optional[MutationSpec] = None
    artifact: ArtifactIR
    rendering: str
    rendering_hash: str
    requirements: tuple[str, ...] = ()


class CandidateResult(_Strict):
    candidate_id: str
    feasibility: Feasibility
    evaluations: tuple[Evaluation, ...] = ()
    scores: dict[str, ObjectiveEstimate] = Field(default_factory=dict)
    disagreement: dict[str, float] = Field(default_factory=dict)


class ImmuneAction(_Strict):
    action: Literal["QUARANTINE_SOURCE", "DEGRADE_CAPABILITY", "BLOCK_STAGE", "RETRIEVE_AGAIN", "HITL_REQUIRED"]
    target: str
    reason: str


class HumanAction(_Strict):
    action_id: str = Field(min_length=1, max_length=120)
    kind: Literal["SELECT", "REQUEST_VARIATION", "REJECT_ALL", "RETURN_TO_BRIEF"]
    actor: str = Field(min_length=1, max_length=120)
    candidate_id: Optional[str] = None
    axis: Optional[AxisName] = None
    note: str = Field(default="", max_length=1000)


class Usage(_Strict):
    candidates_generated: int = 0
    regenerations: int = 0
    generations_used: int = 0
    corrections: int = 0
    model_calls: int = 0
    context_tokens: int = 0
    wall_clock_seconds: float = 0.0


class CreativeRun(_Strict):
    runtime_version: str = RUNTIME_VERSION
    run_id: str
    state: RunState
    brief_hash: str
    brief_text_hash: str
    compilation: MissionCompilation
    mission: Optional[MissionIR] = None
    plan: Optional[ExecutionPlan] = None
    context: Optional[ContextPortfolio] = None
    requirements: tuple[str, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    results: dict[str, CandidateResult] = Field(default_factory=dict)
    front: tuple[str, ...] = ()
    dominated_by: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    selected_id: Optional[str] = None
    final: Optional[Candidate] = None
    correction: Optional[dict] = None
    tri_diff: Optional[TriDiff] = None
    evidence: Optional[EvidenceEnvelope] = None
    approval: Optional[dict] = None
    immune: tuple[ImmuneAction, ...] = ()
    reasons: tuple[str, ...] = ()
    applied_actions: tuple[str, ...] = ()
    usage: Usage = Usage()
    events: tuple[FlightEvent, ...] = ()

    def candidate(self, candidate_id: str) -> Candidate:
        for c in self.candidates:
            if c.candidate_id == candidate_id:
                return c
        raise KeyError(candidate_id)

    @property
    def terminal_status(self) -> str:
        return TERMINAL_STATUS[self.state]


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Budget:
    def __init__(self, mission: MissionIR, clock: Callable[[], float]) -> None:
        self.mission, self.clock, self.start = mission, clock, clock()

    def elapsed(self) -> float:
        return round(self.clock() - self.start, 4)

    def exhausted(self) -> bool:
        return self.elapsed() > self.mission.resource_budget.max_wall_clock_seconds


# --------------------------------------------------------------------------- generation


def _generate(mission: MissionIR, candidate_id: str, *, generation: int, concept: Optional[ConceptSpec],
              requirements: Iterable[str], parent_id: Optional[str] = None, mutation: Optional[MutationSpec] = None,
              omit_sections: Iterable[str] = ()) -> Candidate:
    req = tuple(sorted(requirements))
    prov = {"generation": generation, "parent_candidate_id": parent_id,
            "mutation_id": mutation.mutation_id if mutation else None}
    t = mission.artifact_type
    if t in LANDING_TYPES:
        artifact = landing_mod.generate_landing(mission, concept or DEFAULT_CONCEPT, candidate_id=candidate_id,
                                                provenance=prov, omit_sections=omit_sections)
        rendering = landing_mod.render_landing_html(artifact, req)
    elif t == "logo":
        artifact, rendering = generate_logo(mission, candidate_id=candidate_id, provenance=prov)
    elif t == "design_system":
        artifact, rendering = generate_design_system(mission, candidate_id=candidate_id, provenance=prov)
    elif t in {"dashboard", "mobile_ui"}:
        artifact, rendering = _interface_spec(mission, candidate_id, prov)
    else:  # plans for every other type are BLOCKED before generation
        raise LookupError(f"PROVIDER_UNAVAILABLE: no in-repo generator for {t}")
    return Candidate(candidate_id=candidate_id, generation=generation, concept=concept if t in LANDING_TYPES else None,
                     parent_id=parent_id, mutation=mutation, artifact=artifact, rendering=rendering,
                     rendering_hash=_h(rendering), requirements=req)


def _interface_spec(mission: MissionIR, candidate_id: str, prov: dict) -> tuple[ArtifactIR, str]:
    from services.langgraph.agency.ui_ux.compiler import compile_uiux
    from services.langgraph.agency.ui_ux.models import BrandContext, UIUXRequest

    palette = mission_constraint(mission, ConstraintKind.BRAND_PALETTE)[0].params["palette"]
    ir = compile_uiux(UIUXRequest(project_ref=mission.mission_id, surface_hint=mission.artifact_type.replace("_", " "),
                                  purpose=mission.business_goal, primary_user=mission.audience,
                                  primary_task=mission.desired_action, business_goal=mission.business_goal,
                                  brand=BrandContext(brand_name=mission.brand_name, palette_hex=sorted(palette.values()))))
    dump = ir.model_dump(mode="json")
    summary = {"brand_name": mission.brand_name, "uiux_terminal": str(dump.get("terminal")), "uiux_ir_hash": canonical_hash(dump),
               "palette": dict(palette), "owner": "agency.ui_ux.compiler.compile_uiux"}
    rendering = json.dumps(summary, sort_keys=True, indent=2)
    artifact = seal_artifact(
        artifact_id=candidate_id, mission_id=mission.mission_id, artifact_type=mission.artifact_type,
        semantic_intent=f"{mission.desired_action} — {mission.business_goal}"[:500], hierarchy=("uiux_design_ir",),
        content_structure={"uiux_ir_hash": summary["uiux_ir_hash"], "uiux_terminal": summary["uiux_terminal"]},
        brand_bindings={"brand_name": mission.brand_name, "palette": dict(palette)},
        provenance={"generator": "agency.ui_ux.compiler.compile_uiux", **prov},
    )
    return artifact, rendering


def _critic_ids(plan: ExecutionPlan) -> list[str]:
    return [c for c in plan.validators if c != "cap.validate.constraints"]


def _evaluate(mission: MissionIR, plan: ExecutionPlan, cand: Candidate) -> CandidateResult:
    view = blind_view(mission, cand.artifact, cand.rendering, cand.requirements)
    feas = ConstraintValidator().check(view)
    if feas.verdict == "INFEASIBLE":
        return CandidateResult(candidate_id=cand.candidate_id, feasibility=feas)
    evs = run_critics(view, _critic_ids(plan))
    scores, disagreement = aggregate(evs)
    return CandidateResult(candidate_id=cand.candidate_id, feasibility=feas, evaluations=tuple(evs), scores=scores,
                           disagreement=disagreement)


def _with_novelty(results: dict[str, CandidateResult], candidates: list[Candidate]) -> dict[str, CandidateResult]:
    """Distinctiveness = structural distance to the nearest other feasible candidate."""
    live = [c for c in candidates if c.candidate_id in results and results[c.candidate_id].feasibility.verdict != "INFEASIBLE"
            and c.concept is not None]
    if len(live) < 2:
        return results
    fps = {c.candidate_id: fingerprint(c.candidate_id, c.concept, c.artifact.hierarchy, c.rendering) for c in live}
    reservoir = NoveltyReservoir()
    for fp in fps.values():
        reservoir.add(fp)
    out = dict(results)
    for cid, fp in fps.items():
        r = out[cid]
        scores = {**r.scores, "distinctiveness": ObjectiveEstimate(value=round(min(1.0, reservoir.novelty(fp) / 0.6), 4), uncertainty=0.1)}
        out[cid] = r.model_copy(update={"scores": dict(sorted(scores.items()))})
    return out


def _front(results: Mapping[str, CandidateResult]) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    feasible = {cid: r.scores for cid, r in results.items() if r.feasibility.verdict != "INFEASIBLE"}
    if not feasible:
        return (), {}
    res = pareto_front(feasible)
    return res.front, res.dominated_by


# --------------------------------------------------------------------------- run


def run_creative_mission(
    brief: Mapping[str, Any],
    *,
    run_id: str,
    registry: Optional[RegistryLoad] = None,
    corpus_root=None,
    unavailable: Iterable[str] = (),
    use_context: bool = True,
    clock: Callable[[], float] = time.monotonic,
) -> CreativeRun:
    rec = FlightRecorder()
    brief_text = str(brief.get("brief_text") or "")
    brief_body = {k: v for k, v in brief.items() if k != "brief_text"}
    base = dict(run_id=run_id, brief_hash=canonical_hash(dict(brief)), brief_text_hash=_h(brief_text))

    compilation = compile_mission(brief_body, run_id=run_id)
    if compilation.status != "READY" or compilation.mission is None:
        rec.record("MISSION_COMPILED", "intake", compilation.status)
        state = "HITL_REQUIRED" if compilation.status == "HITL_REQUIRED" else "CONTRADICTORY_CONSTRAINTS"
        rec.record("TERMINAL", "intake", state)
        return CreativeRun(state=state, compilation=compilation, immune=(ImmuneAction(action="HITL_REQUIRED", target="mission",
                           reason=compilation.status),), reasons=compilation.unresolved_questions + compilation.contradictions,
                           events=rec.events, **base)
    mission = compilation.mission
    rec.record("MISSION_COMPILED", "intake", "READY", mission_hash=mission.mission_hash)
    budget = _Budget(mission, clock)

    reg = registry or default_registry()
    immune: list[ImmuneAction] = [ImmuneAction(action="QUARANTINE_SOURCE", target=k, reason=v[:200]) for k, v in reg.quarantined.items()]
    immune += [ImmuneAction(action="DEGRADE_CAPABILITY", target=k, reason=v[:200]) for k, v in reg.degraded.items()]
    lost = sorted(set(unavailable))
    if lost:
        reg = reg.model_copy(update={"degraded": {**reg.degraded, **{c: "PROVIDER_UNAVAILABLE: provider reported unavailable" for c in lost}},
                                     "status": "DEGRADED"})
        immune += [ImmuneAction(action="DEGRADE_CAPABILITY", target=c, reason="PROVIDER_UNAVAILABLE") for c in lost]

    plan = compile_plan(mission, reg, brief_text=brief_text)
    rec.record("PLAN_COMPILED", "organization", plan.status, plan_hash=plan.plan_hash, topology=plan.topology_class)
    if plan.status == "BLOCKED":
        immune.append(ImmuneAction(action="BLOCK_STAGE", target="generate", reason=";".join(plan.blocked_reasons)[:200]))
        immune.append(ImmuneAction(action="HITL_REQUIRED", target="plan", reason="plan blocked"))
        rec.record("TERMINAL", "organization", "BLOCKED")
        return CreativeRun(state="BLOCKED", compilation=compilation, mission=mission, plan=plan, immune=tuple(immune),
                           reasons=plan.blocked_reasons, events=rec.events, **base)

    active = sorted({c for n in plan.nodes for c in n.capability_ids})
    if use_context:
        portfolio = select_context(mission, reg, active, corpus_root=corpus_root)
        requirements = derive_requirements(portfolio, corpus_root) if mission.artifact_type in INTERFACE_TYPES else ()
    else:
        portfolio = ContextPortfolio(status="OK", corpus_version=None, token_budget=0, total_tokens=0, selected=(), excluded=(),
                                     reasons=("CONTEXT_DISABLED: champion baseline",),
                                     context_hash=canonical_hash({"mission_hash": mission.mission_hash, "context": None}))
        requirements = ()
    quarantined_units = [e for e in portfolio.excluded if e.reason.startswith("QUARANTINE_SOURCE")]
    for e in quarantined_units:
        immune.append(ImmuneAction(action="QUARANTINE_SOURCE", target=e.id, reason=e.reason[:200]))
    if quarantined_units:
        immune.append(ImmuneAction(action="RETRIEVE_AGAIN", target="context", reason="selection refilled from remaining units"))
    rec.record("CONTEXT_SELECTED", "context", portfolio.status, context_hash=portfolio.context_hash,
               selected=len(portfolio.selected), excluded=len(portfolio.excluded))
    usage = Usage(context_tokens=portfolio.total_tokens)
    common = dict(compilation=compilation, mission=mission, plan=plan, context=portfolio, requirements=requirements, **base)
    if portfolio.status == "BUDGET_EXHAUSTED":
        immune.append(ImmuneAction(action="HITL_REQUIRED", target="context", reason="mandatory context exceeds the token budget"))
        rec.record("BUDGET_EXHAUSTED", "context", "BUDGET_EXHAUSTED")
        return CreativeRun(state="BUDGET_EXHAUSTED", immune=tuple(immune), reasons=portfolio.reasons, usage=usage,
                           events=rec.events, **common)
    if portfolio.status == "DEGRADED":
        rec.record("DEGRADED", "context", "DEGRADED")

    # Generation 1.
    population = plan.search_policy.population_size
    concepts: list[Optional[ConceptSpec]]
    if mission.artifact_type in LANDING_TYPES:
        concepts = list(concept_candidates(mission, population)) if plan.search_policy.enabled else [DEFAULT_CONCEPT]
    else:
        concepts = [None]
    candidates: list[Candidate] = []
    reasons: list[str] = []
    for i, concept in enumerate(concepts):
        if budget.exhausted():
            reasons.append("BUDGET_EXHAUSTED: wall clock during generation")
            break
        cid = f"{run_id}-g1-c{i}"
        try:
            cand = _generate(mission, cid, generation=1, concept=concept, requirements=requirements)
        except Exception as exc:  # provider/generator loss: never simulate output
            immune.append(ImmuneAction(action="DEGRADE_CAPABILITY", target="generate", reason=f"PROVIDER_UNAVAILABLE: {type(exc).__name__}"))
            rec.record("CANDIDATE_FAILED", "generate", "PROVIDER_UNAVAILABLE", candidate_id=cid)
            continue
        candidates.append(cand)
        rec.record("CANDIDATE_GENERATED", "generate", "ok", candidate_id=cid, artifact_hash=cand.artifact.hash,
                   rendering_hash=cand.rendering_hash)

    # Collapse detection: replace the later candidate of a collapsed pair once.
    regenerations = 0
    if plan.search_policy.enabled and len(candidates) > 1:
        fps = [fingerprint(c.candidate_id, c.concept, c.artifact.hierarchy, c.rendering) for c in candidates]
        replaced: set[str] = set()
        for _, b_id, dist in detect_collapse(fps, plan.search_policy.diversity_floor):
            if b_id in replaced or mission.resource_budget.max_regenerations_per_candidate < 1:
                continue
            idx = next(i for i, c in enumerate(candidates) if c.candidate_id == b_id)
            old = candidates[idx]
            child, spec = mutate(b_id, old.concept, reason=f"SEARCH_COLLAPSE: distance {dist} < floor",
                                 avoid=[c.concept for c in candidates])
            candidates[idx] = _generate(mission, f"{b_id}-r1", generation=1, concept=child, requirements=requirements,
                                        parent_id=b_id, mutation=spec)
            replaced.add(b_id)
            regenerations += 1
            rec.record("CANDIDATE_REGENERATED", "concepts", "ok", candidate_id=candidates[idx].candidate_id,
                       parent_candidate_id=b_id, mutation_id=spec.mutation_id)

    usage = usage.model_copy(update={"candidates_generated": len(candidates) + regenerations, "regenerations": regenerations,
                                     "generations_used": 1, "wall_clock_seconds": budget.elapsed()})
    if not candidates:
        immune.append(ImmuneAction(action="HITL_REQUIRED", target="generate", reason="no candidate could be generated"))
        rec.record("TERMINAL", "generate", "BLOCKED")
        return CreativeRun(state="BLOCKED", immune=tuple(immune), reasons=tuple(reasons + ["PROVIDER_UNAVAILABLE: no candidates"]),
                           usage=usage, events=rec.events, **common)

    results: dict[str, CandidateResult] = {}
    for cand in candidates:
        results[cand.candidate_id] = _evaluate(mission, plan, cand)
        r = results[cand.candidate_id]
        rec.record("FEASIBILITY_CHECKED", "feasibility", r.feasibility.verdict, candidate_id=cand.candidate_id,
                   violations=len(r.feasibility.violations))
        if r.evaluations:
            rec.record("EVALUATED", "critique", "ok", candidate_id=cand.candidate_id,
                       evaluators=[e.evaluator_id for e in r.evaluations])
    results = _with_novelty(results, candidates)
    front, dominated = _front(results)
    rec.record("PARETO_COMPUTED", "pareto", "ok", front=list(front))

    state: RunState = "AWAITING_SELECTION"
    if not front:
        state = "BLOCKED"
        reasons.append("NO_FEASIBLE_CANDIDATE: every candidate failed a hard constraint")
        immune.append(ImmuneAction(action="HITL_REQUIRED", target="feasibility", reason="no feasible candidate"))
    elif any(r.startswith("BUDGET_EXHAUSTED") for r in reasons):
        state = "BUDGET_EXHAUSTED"
        rec.record("BUDGET_EXHAUSTED", "generate", "BUDGET_EXHAUSTED")
    run = CreativeRun(state=state, candidates=tuple(candidates), results=results, front=front, dominated_by=dominated,
                      immune=tuple(immune), reasons=tuple(reasons), usage=usage, events=rec.events, **common)
    if not any(n.node_id == "human_select" for n in plan.nodes) and state == "AWAITING_SELECTION":
        # T0/T1 without critics: the single candidate goes straight to the approval gate.
        return _finalise(run, front[0], rec, correction=None, diff=None)
    rec.record("TERMINAL", "pareto", state)
    return run.model_copy(update={"events": rec.events})


# --------------------------------------------------------------------------- human actions


def _correct(run: CreativeRun, cand: Candidate) -> tuple[Candidate, Optional[dict]]:
    """<=1 smallest-scope correction from the selected candidate's own findings."""
    result = run.results[cand.candidate_id]
    findings = [f for e in result.evaluations for f in e.findings]
    add_req = sorted({_STYLE_REPAIRS[f.code] for f in findings if f.code in _STYLE_REPAIRS})
    omit: list[str] = []
    if any(f.code == "HIERARCHY_DILUTED" for f in findings) and cand.artifact.landing_page is not None:
        required = {str(c.params["section"]) for c in run.mission.all_constraints() if c.kind.value == "required_section"}
        body = [s.kind.value for s in cand.artifact.landing_page.sections if s.kind.value not in {"hero", "cta", "footer"}]
        optional = [k for k in body if k not in required]
        if optional:
            omit.append(optional[-1])
    if not add_req and not omit:
        return cand, None
    scopes = sorted(({"style"} if add_req else set()) | ({"structure"} if omit else set()))
    prev_omit = [o.split(":")[0] for o in (cand.artifact.content_structure.get("omitted") or []) if o.endswith("excluded")]
    corrected = _generate(run.mission, f"{cand.candidate_id}-x1", generation=cand.generation, concept=cand.concept,
                          requirements=set(cand.requirements) | set(add_req), parent_id=cand.candidate_id,
                          mutation=cand.mutation, omit_sections=[*prev_omit, *omit])
    corrected = corrected.model_copy(update={"artifact": seal_artifact(**{
        **corrected.artifact.model_dump(exclude={"hash"}), "version": cand.artifact.version + 1,
        "artifact_id": cand.artifact.artifact_id})})
    return corrected, {"scopes": scopes, "added_requirements": add_req, "omitted_sections": omit,
                       "from_findings": sorted({f.code for f in findings if f.repair_scope in {"style", "structure"}})}


def _evidence(run: CreativeRun, final: Candidate, approval_state: str = "not_requested") -> EvidenceEnvelope:
    sections = final.artifact.landing_page.sections if final.artifact.landing_page else ()
    sources = sorted({u.id for u in (run.context.selected if run.context else ())} | {r for s in sections for r in s.source_refs})
    result = run.results.get(final.candidate_id)
    validation_refs = (canonical_hash(result.feasibility.model_dump(mode="json")),) if result else ()
    caps = sorted({c for n in run.plan.nodes for c in n.capability_ids})
    return EvidenceEnvelope(
        mission_hash=run.mission.mission_hash, plan_hash=run.plan.plan_hash, context_hash=run.context.context_hash,
        corpus_version=run.context.corpus_version, capability_versions=default_registry().versions(caps) if caps else (),
        source_refs=tuple(sources), provider_config_ref=PROVIDER_CONFIG_REF, seed=None, parent_candidate_id=final.parent_id,
        mutation_spec=final.mutation.model_dump() if final.mutation else None, evaluator_versions=EVALUATOR_VERSIONS,
        validation_refs=validation_refs, approval_state=approval_state, artifact_hash=final.artifact.hash,
    )


def _finalise(run: CreativeRun, selected_id: str, rec: FlightRecorder, *, correction: Optional[dict],
              diff: Optional[TriDiff], final: Optional[Candidate] = None) -> CreativeRun:
    final = final or run.candidate(selected_id)
    results = dict(run.results)
    if final.candidate_id not in results:
        results[final.candidate_id] = _evaluate(run.mission, run.plan, final)
    staged = run.model_copy(update={"results": results})
    evidence = _evidence(staged, final)
    rec.record("TERMINAL", "approval", "AWAITING_APPROVAL", artifact_hash=final.artifact.hash)
    return staged.model_copy(update={"state": "AWAITING_APPROVAL", "selected_id": selected_id, "final": final,
                                     "correction": correction, "tri_diff": diff, "evidence": evidence, "events": rec.events})


def decide(run: CreativeRun, action: HumanAction) -> CreativeRun:
    if action.action_id in run.applied_actions:
        return run  # replay of an applied action: no duplicate effect
    if run.state != "AWAITING_SELECTION":
        raise ActionNotAllowed(f"{action.kind} is not allowed in state {run.state}")
    rec = FlightRecorder(run.events)
    rec.record("HUMAN_ACTION", "human_select", action.kind, action_id=action.action_id,
               candidate_id=action.candidate_id, axis=action.axis, note_hash=_h(action.note) if action.note else None)
    applied = run.applied_actions + (action.action_id,)

    if action.kind == "REJECT_ALL":
        return run.model_copy(update={"state": "REJECTED", "applied_actions": applied, "events": rec.events})
    if action.kind == "RETURN_TO_BRIEF":
        return run.model_copy(update={"state": "RETURNED_TO_BRIEF", "applied_actions": applied, "events": rec.events,
                                      "reasons": run.reasons + ("RETURN_TO_BRIEF: human requested a revised brief",)})
    if action.kind == "REQUEST_VARIATION":
        return _variation(run, action, rec, applied)

    if action.candidate_id not in run.front:
        raise ActionNotAllowed("SELECT must name a candidate on the current Pareto front")
    chosen = run.candidate(action.candidate_id)
    base = run.model_copy(update={"applied_actions": applied})
    if run.mission.resource_budget.max_corrections < 1:
        return _finalise(base, chosen.candidate_id, rec, correction=None, diff=None)
    corrected, info = _correct(base, chosen)
    if info is None:
        return _finalise(base, chosen.candidate_id, rec, correction={"applied": False, "reason": "no repairable finding"}, diff=None)
    before_r = base.results[chosen.candidate_id]
    after_r = _evaluate(base.mission, base.plan, corrected)
    diff = tri_diff(base.mission, (chosen.artifact, chosen.rendering, before_r.feasibility),
                    (corrected.artifact, corrected.rendering, after_r.feasibility), set(info["scopes"]))
    regressed = [k for k, est in after_r.scores.items()
                 if k in before_r.scores and est.value + est.uncertainty < before_r.scores[k].value]
    usage = base.usage.model_copy(update={"corrections": 1})
    if not diff.passed or regressed or after_r.feasibility.verdict == "INFEASIBLE":
        rec.record("CORRECTION_REJECTED", "correct", "rejected", candidate_id=corrected.candidate_id)
        rec.record("TRIDIFF", "tridiff", "failed" if not diff.passed else "ok")
        info = {**info, "applied": False, "reason": "correction failed revalidation", "regressed": regressed}
        return _finalise(base.model_copy(update={"usage": usage}), chosen.candidate_id, rec, correction=info, diff=diff)
    rec.record("CORRECTION_APPLIED", "correct", "ok", candidate_id=corrected.candidate_id, artifact_hash=corrected.artifact.hash)
    rec.record("TRIDIFF", "tridiff", "ok", d2_changes=len(diff.d2_artifact))
    results = {**base.results, corrected.candidate_id: after_r}
    return _finalise(base.model_copy(update={"results": results, "usage": usage, "candidates": base.candidates + (corrected,)}),
                     chosen.candidate_id, rec, correction={**info, "applied": True}, diff=diff, final=corrected)


def _variation(run: CreativeRun, action: HumanAction, rec: FlightRecorder, applied: tuple[str, ...]) -> CreativeRun:
    mission, plan = run.mission, run.plan
    if mission.artifact_type not in LANDING_TYPES:
        raise ActionNotAllowed("variations need a concept-bearing artifact type")
    if run.usage.generations_used >= mission.resource_budget.max_generations:
        rec.record("BUDGET_EXHAUSTED", "human_select", "generations")
        return run.model_copy(update={"applied_actions": applied, "events": rec.events,
                                      "reasons": run.reasons + ("BUDGET_EXHAUSTED: generation cap reached; select from the current front",)})
    parent_id = action.candidate_id or run.front[0]
    if parent_id not in run.front:
        raise ActionNotAllowed("variations start from a candidate on the current front")
    parent = run.candidate(parent_id)
    avoid = [c.concept for c in run.candidates if c.concept is not None]
    n = min(plan.search_policy.population_size if plan.search_policy.enabled else 1, mission.resource_budget.max_candidates)
    new: list[Candidate] = []
    for i in range(n):
        child, spec = mutate(parent_id, parent.concept, reason="REQUEST_VARIATION", avoid=avoid + [c.concept for c in new],
                             axis=action.axis)
        if child in avoid or any(c.concept == child for c in new):
            break
        cand = _generate(mission, f"{run.run_id}-g2-c{i}", generation=2, concept=child, requirements=run.requirements,
                         parent_id=parent_id, mutation=spec)
        new.append(cand)
        rec.record("CANDIDATE_GENERATED", "generate", "ok", candidate_id=cand.candidate_id, artifact_hash=cand.artifact.hash,
                   parent_candidate_id=parent_id, mutation_id=spec.mutation_id)
    candidates = list(run.candidates) + new
    results = dict(run.results)
    for cand in new:
        results[cand.candidate_id] = _evaluate(mission, plan, cand)
        rec.record("FEASIBILITY_CHECKED", "feasibility", results[cand.candidate_id].feasibility.verdict, candidate_id=cand.candidate_id)
    results = _with_novelty(results, candidates)
    front, dominated = _front(results)
    rec.record("PARETO_COMPUTED", "pareto", "ok", front=list(front))
    usage = run.usage.model_copy(update={"generations_used": 2, "candidates_generated": run.usage.candidates_generated + len(new)})
    return run.model_copy(update={"candidates": tuple(candidates), "results": results, "front": front, "dominated_by": dominated,
                                  "usage": usage, "applied_actions": applied, "events": rec.events})


# --------------------------------------------------------------------------- approval + delivery gate


def validate_evidence(data: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    errors = [f"VALIDATION_FAILED: missing {k}" for k in MANDATORY_PROVENANCE if not data.get(k)]
    if not errors:
        try:
            EvidenceEnvelope.model_validate(dict(data))
        except ValidationError as exc:
            errors.append(f"VALIDATION_FAILED: {exc.error_count()} schema error(s)")
    return not errors, tuple(errors)


def submit_for_approval(run: CreativeRun, *, tenant_id: str, project_id: str, initiated_by: str) -> CreativeRun:
    """Request a human approval through the existing approvals table, bound to the artifact hash."""
    from services.langgraph.persistence.approvals import create_approval_request, get_approvals_for_run, mark_approval_stale
    from services.langgraph.persistence.runs import create_run_record, get_run_record

    if run.state != "AWAITING_APPROVAL" or run.final is None:
        raise ActionNotAllowed(f"approval cannot be requested in state {run.state}")
    subject = run.final.artifact.hash
    rec = FlightRecorder(run.events)
    if get_run_record(run.run_id) is None:
        create_run_record(run.run_id, tenant_id, project_id, PIPELINE, "awaiting_approval",
                          {"initiated_by": initiated_by, "mission_hash": run.mission.mission_hash, "plan_hash": run.plan.plan_hash,
                           "artifact_hash": subject, "runtime_version": RUNTIME_VERSION})
    approval = None
    for existing in get_approvals_for_run(run.run_id):
        if existing.get("status") != "pending":
            continue
        if existing.get("subject_hash") == subject and approval is None:
            approval = existing  # idempotent re-submit
        else:
            mark_approval_stale(existing["approval_id"], "superseded: creative artifact hash changed")
            rec.record("APPROVAL_SUPERSEDED", "approval", "stale", approval_id=existing["approval_id"])
    if approval is None:
        approval = create_approval_request(
            run.run_id, tenant_id, project_id, "Creative artifact requires human approval before delivery", None,
            subject_type="CREATIVE_ARTIFACT", subject_ref=run.final.artifact.artifact_id,
            subject_version_ref=str(run.final.artifact.version), subject_hash=subject,
            authority_ref=run.mission.approval_policy.authority_ref, policy_version=APPROVAL_POLICY_VERSION)
        rec.record("APPROVAL_REQUESTED", "approval", "pending", approval_id=approval["approval_id"], subject_hash=subject)
    evidence = run.evidence.model_copy(update={"approval_state": "pending"})
    return run.model_copy(update={"approval": {"approval_id": approval["approval_id"], "subject_hash": subject},
                                  "evidence": evidence, "events": rec.events})


class DeliveryVerdict(_Strict):
    allowed: bool
    reasons: tuple[str, ...]
    artifact_hash: Optional[str]
    approval_id: Optional[str]
    external_effects: Literal["none"] = "none"


def delivery_gate(run: CreativeRun, approval: Optional[Mapping[str, Any]] = None) -> tuple[CreativeRun, DeliveryVerdict]:
    """Fail-closed: allowed only for an approved, non-stale approval whose subject hash
    equals the current, self-consistent artifact hash. Never performs delivery."""
    reasons: list[str] = []
    final = run.final
    if run.state not in {"AWAITING_APPROVAL", "APPROVED_FOR_DELIVERY"} or final is None:
        reasons.append(f"NOT_READY: state {run.state}")
    else:
        if _h(final.rendering) != final.rendering_hash:
            reasons.append("ARTIFACT_HASH_INVALID: rendering changed after sealing")
        ok, errs = validate_evidence(run.evidence.model_dump() if run.evidence else {})
        reasons += list(errs)
        if run.evidence and run.evidence.artifact_hash != final.artifact.hash:
            reasons.append("EVIDENCE_MISMATCH: evidence does not bind the final artifact")
    if approval is None and run.approval:
        from services.langgraph.persistence.approvals import get_approval

        approval = get_approval(run.approval["approval_id"])
    if approval is None:
        reasons.append("NO_APPROVAL")
    else:
        status, decision = approval.get("status"), approval.get("decision")
        if status == "stale":
            reasons.append("APPROVAL_STALE")
        elif status != "resolved":
            reasons.append("APPROVAL_PENDING")
        elif decision != "approve":
            reasons.append("APPROVAL_REJECTED")
        if final is not None and approval.get("subject_hash") != final.artifact.hash:
            reasons.append("SUBJECT_HASH_MISMATCH")
    verdict = DeliveryVerdict(allowed=not reasons, reasons=tuple(reasons), artifact_hash=final.artifact.hash if final else None,
                              approval_id=(approval or {}).get("approval_id"))
    rec = FlightRecorder(run.events)
    rec.record("DELIVERY_GATE", "approval", "allowed" if verdict.allowed else "blocked",
               reasons=[r.split(":")[0] for r in reasons])
    update: dict[str, Any] = {"events": rec.events}
    if verdict.allowed:
        update["state"] = "APPROVED_FOR_DELIVERY"
        update["evidence"] = run.evidence.model_copy(update={"approval_state": "approved"})
    return run.model_copy(update=update), verdict


# --------------------------------------------------------------------------- receipts


def mission_receipt(run: CreativeRun) -> dict:
    body = {
        "receipt": "MissionReceipt", "runtime_version": RUNTIME_VERSION, "run_id": run.run_id, "state": run.state,
        "terminal_status": run.terminal_status, "brief_hash": run.brief_hash,
        "mission_hash": run.mission.mission_hash if run.mission else None,
        "plan_hash": run.plan.plan_hash if run.plan else None,
        "topology": run.plan.topology_class if run.plan else None,
        "search_policy": run.plan.search_policy.model_dump(mode="json") if run.plan else None,
        "context": run.context.receipt() if run.context else None,
        "requirements": list(run.requirements),
        "candidates": [{"candidate_id": c.candidate_id, "generation": c.generation, "artifact_hash": c.artifact.hash,
                        "rendering_hash": c.rendering_hash, "parent": c.parent_id,
                        "mutation": c.mutation.model_dump() if c.mutation else None,
                        "concept": c.concept.model_dump() if c.concept else None,
                        "feasibility": run.results[c.candidate_id].feasibility.verdict if c.candidate_id in run.results else None}
                       for c in run.candidates],
        "front": list(run.front), "dominated_by": {k: list(v) for k, v in run.dominated_by.items()},
        "selected": run.selected_id, "final_artifact_hash": run.final.artifact.hash if run.final else None,
        "correction": run.correction, "tri_diff_passed": run.tri_diff.passed if run.tri_diff else None,
        "evidence": run.evidence.model_dump(mode="json") if run.evidence else None,
        "approval": run.approval, "immune": [i.model_dump() for i in run.immune], "reasons": list(run.reasons),
        "usage": run.usage.model_dump(exclude={"wall_clock_seconds"}), "evaluator_versions": list(EVALUATOR_VERSIONS),
        "events_head": run.events[-1].event_hash if run.events else None, "event_count": len(run.events),
        "external_effects": "none",
    }
    body["receipt_hash"] = canonical_hash(body)
    # Timing is reported but never hashed: replaying a mission must reproduce the receipt hash.
    body["timing"] = {"wall_clock_seconds": run.usage.wall_clock_seconds}
    return body


__all__ = [
    "ActionNotAllowed", "Candidate", "CandidateResult", "CreativeRun", "DeliveryVerdict", "HumanAction", "ImmuneAction",
    "PIPELINE", "RUNTIME_VERSION", "TERMINAL_STATUS", "Usage", "decide", "delivery_gate", "mission_receipt",
    "run_creative_mission", "submit_for_approval", "validate_evidence",
]
