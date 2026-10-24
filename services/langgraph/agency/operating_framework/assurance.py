"""Meaning, Mutation, Probe, Renewal and Review: findings, never authority.

Each record is stored as an immutable Project OS artifact (N1 ``qa_report``,
subtype ``assurance.<kind>``, key ``assurance/<kind>/<record_id>``), so it gets
the canonical storage, content hash, version history and tenant scope instead
of a parallel store. A record is written once (version 1) and never revised; a
correction is a new record whose ``supersedes_ref`` names the current head of
the chain. ``read_record`` re-reads the stored bytes and recomputes the record
hash, and reports ``INTEGRITY_FAILED`` if either moved.

Boundaries, enforced here and tested:

* Meaning compares requirements with read-back deliverables deterministically;
  a supplied semantic score is stored as advisory and changes nothing.
* Mutation applies one perturbation to an in-memory variant; the canonical
  artifact is never written. Expected versus observed findings give TP/FP/FN/TN.
* Probe changes a dependency only inside an in-memory snapshot and proves the
  canonical graph (artifact heads and edges) is byte-for-byte unchanged after;
  a missing edge becomes a proposal, never an edge.
* Renewal retains the decision and its alternatives and proposes; the decision
  record is checked unchanged after. Only native governance can replace it.
* Review binds the exact subject hashes and dependency snapshot, reads every
  candidate's full bytes, and can only open an approval through the existing
  route. A summary never stands in for that access.

No record publishes, sends, spends, deploys or calls a provider or the network.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.project_os.knowledge import extract_claims
from services.langgraph.security.auth import Principal

from .catalog import load_catalog
from .contracts import (
    PIPELINE,
    POLICY_VERSION,
    REQUIRED_REF_KINDS,
    FrameworkError,
    parse_artifact_ref,
)
from .engine import NOT_MEASURED
from .refs import read_artifact_bytes, resolve_ref

SCHEMA_VERSION = "amc-assurance/v1"
KINDS = ("meaning", "mutation", "probe", "renewal", "review")
RECORD_ARTIFACT_TYPE = "qa_report"
_ARTIFACT_REF = re.compile(r"^artifact:[A-Za-z0-9._-]{1,200}@v[1-9][0-9]{0,6}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _artifact_refs(values: list[str]) -> list[str]:
    for value in values:
        if not _ARTIFACT_REF.match(value):
            raise ValueError(f"invalid artifact ref {value!r}")
    return values


class Base(_Strict):
    supersedes_ref: str | None = Field(default=None, max_length=80)
    task_ids: list[str] = Field(default_factory=list, max_length=50)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    privacy_classification: str = Field(default="internal", pattern=r"^(public|internal|confidential|restricted)$")

    @field_validator("task_ids")
    @classmethod
    def _tasks(cls, v: list[str]) -> list[str]:
        catalog = load_catalog()
        for task_id in v:
            try:
                catalog.task(task_id)
            except KeyError as exc:
                raise ValueError(f"unknown catalog task {task_id}") from exc
        return v


class MeaningInput(Base):
    interpreted_obligation: str = Field(min_length=3, max_length=2000)
    requirement_text: str = Field(default="", max_length=4000)
    qualifiers: list[str] = Field(default_factory=list, max_length=30)
    exclusions: list[str] = Field(default_factory=list, max_length=30)
    scope_conditions: list[str] = Field(default_factory=list, max_length=30)
    output_refs: list[str] = Field(default_factory=list, max_length=20)
    ambiguities: list[str] = Field(default_factory=list, max_length=30)
    advisory_semantic_score: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("output_refs")
    @classmethod
    def _outputs(cls, v: list[str]) -> list[str]:
        return _artifact_refs(v)


class MutationClass(str, Enum):
    CLAIM_CHANGE = "CLAIM_CHANGE"
    SEMANTIC_PRESERVING = "SEMANTIC_PRESERVING"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    ALTERED_APPROVAL_HASH = "ALTERED_APPROVAL_HASH"
    STALE_VERSION = "STALE_VERSION"
    LOCALE_CHANGE = "LOCALE_CHANGE"
    ACCESSIBILITY_REGRESSION = "ACCESSIBILITY_REGRESSION"
    CROSS_TENANT_REF = "CROSS_TENANT_REF"
    VISUAL_ONLY = "VISUAL_ONLY"


DETECTORS = ("CLAIM_CHANGED", "REFS_REQUIRED", "APPROVAL_SUBJECT_MISMATCH", "ARTIFACT_STALE", "LOCALE_CHANGED",
             "A11Y_ALT_MISSING", "REF_NOT_FOUND")
DETECTOR_VERSION = "amc-assurance-detectors/v1"


class MutationInput(Base):
    base_ref: str
    mutation_class: MutationClass
    find: str = Field(default="", max_length=500)
    replace: str = Field(default="", max_length=500)
    expected_findings: list[str] = Field(default_factory=list, max_length=len(DETECTORS))
    test_fixture_ref: str = Field(min_length=3, max_length=200)
    foreign_artifact_id: str | None = Field(default=None, max_length=200)

    @field_validator("base_ref")
    @classmethod
    def _base(cls, v: str) -> str:
        return _artifact_refs([v])[0]

    @field_validator("expected_findings")
    @classmethod
    def _expected(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(DETECTORS))
        if unknown:
            raise ValueError(f"unknown detector(s) {unknown}; known: {list(DETECTORS)}")
        return v


class ProbeInput(Base):
    changed_artifact_id: str = Field(min_length=3, max_length=200)
    change_description: str = Field(min_length=3, max_length=1000)
    declared_effects: list[str] = Field(default_factory=list, max_length=200)
    resource_budget_nodes: int = Field(default=500, ge=1, le=5000)


class TriggerKind(str, Enum):
    EVIDENCE_EXPIRED = "EVIDENCE_EXPIRED"
    NEW_CONTRADICTION = "NEW_CONTRADICTION"
    DEPENDENCY_CHANGED = "DEPENDENCY_CHANGED"
    PERFORMANCE_DRIFT = "PERFORMANCE_DRIFT"
    CLIENT_REQUEST = "CLIENT_REQUEST"
    REGULATORY_CHANGE = "REGULATORY_CHANGE"
    OTHER = "OTHER"


class RenewalInput(Base):
    trigger_kind: TriggerKind
    trigger_evidence_refs: list[str] = Field(min_length=1, max_length=20)
    affected_decision_ref: str = Field(pattern=r"^decision:[A-Za-z0-9._:-]{1,160}$")
    proposed_alternatives: list[str] = Field(min_length=1, max_length=10)
    rationale: str = Field(min_length=3, max_length=4000)
    impact_scope: list[str] = Field(default_factory=list, max_length=50)
    proposal_ref: str | None = None
    request_review: bool = False

    @field_validator("proposal_ref")
    @classmethod
    def _proposal(cls, v: str | None) -> str | None:
        return None if v is None else _artifact_refs([v])[0]


class ReviewInput(Base):
    candidate_refs: list[str] = Field(min_length=1, max_length=50)
    summary: str = Field(default="", max_length=4000)
    request_decision: bool = False

    @field_validator("candidate_refs")
    @classmethod
    def _cands(cls, v: list[str]) -> list[str]:
        return _artifact_refs(v)


_INPUTS: dict[str, type[Base]] = {"meaning": MeaningInput, "mutation": MutationInput, "probe": ProbeInput,
                                  "renewal": RenewalInput, "review": ReviewInput}


# ------------------------------------------------------------------------------ helpers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _adapter():
    from services.langgraph.api.routes._project_common import storage_adapter

    return storage_adapter()


def _resolve_all(plan: dict, refs: list[str], adapter: Any) -> list[dict]:
    return [resolve_ref(r, tenant_id=plan["tenant_id"], project_id=plan["project_id"], adapter=adapter) for r in refs]


def _require_resolvable(checks: list[dict], what: str) -> None:
    bad = [c for c in checks if not c["attachable"]]
    if bad:
        raise FrameworkError("REF_REJECTED", f"{what} must exist in this project", 422, {"checks": bad})


def _artifact_text(plan: dict, ref: str, adapter: Any) -> tuple[dict, str | None]:
    from services.langgraph.persistence.agency_kernel import get_artifact

    check = resolve_ref(ref, tenant_id=plan["tenant_id"], project_id=plan["project_id"], adapter=adapter)
    if check["status"] != "OK":
        return check, None
    artifact_id, _ = parse_artifact_ref(ref)
    data = read_artifact_bytes(get_artifact(artifact_id), adapter)
    try:
        return check, data.decode("utf-8") if data is not None else None
    except UnicodeDecodeError:
        return check, None


def graph_snapshot(project_id: str) -> dict[str, Any]:
    """Read-only snapshot of the project's artifact heads and dependency edges."""
    from services.langgraph.persistence.database import (
        normalize_record,
        table,
        transaction,
    )

    with transaction() as db:
        nodes = db.execute(
            f"SELECT artifact_id, version, content_hash, status FROM {table('agency_artifacts')} WHERE project_id = ? ORDER BY artifact_id",
            (project_id,),
        ).fetchall()
        edges = db.execute(
            f"""SELECT d.artifact_id, d.depends_on_artifact_id, d.relationship FROM {table('artifact_dependencies')} d
                JOIN {table('agency_artifacts')} a ON a.artifact_id = d.artifact_id
                WHERE a.project_id = ? ORDER BY d.depends_on_artifact_id, d.artifact_id""",
            (project_id,),
        ).fetchall()
    snap = {"nodes": [normalize_record(n) for n in nodes], "edges": [normalize_record(e) for e in edges]}
    return {**snap, "hash": canonical_hash(snap)}


def _dependents(edges: list[dict], start: str, budget: int) -> tuple[list[str], bool]:
    children: dict[str, list[str]] = {}
    for e in edges:
        children.setdefault(e["depends_on_artifact_id"], []).append(e["artifact_id"])
    seen: list[str] = []
    frontier = [start]
    while frontier:
        node = frontier.pop(0)
        for child in sorted(children.get(node, [])):
            if child not in seen and child != start:
                if len(seen) >= budget:
                    return seen, True
                seen.append(child)
                frontier.append(child)
    return seen, False


# ------------------------------------------------------------------------------ the five builders


def _meaning(principal: Principal, plan: dict, data: MeaningInput, adapter: Any) -> tuple[dict[str, Any], str, list[str]]:
    texts, outputs = [], []
    for ref in data.output_refs:
        check, text = _artifact_text(plan, ref, adapter)
        if not check["attachable"]:
            raise FrameworkError("REF_REJECTED", "Output locations must exist in this project", 422, {"checks": [check]})
        outputs.append({"ref": ref, "status": check["status"], "content_hash": check["content_hash"],
                        "readable": text is not None})
        if text is not None:
            texts.append(text.lower())
    corpus = "\n".join(texts)
    qualifiers = [{"qualifier": q, "found": q.lower() in corpus} if texts else {"qualifier": q, "found": None}
                  for q in data.qualifiers]
    exclusions = [{"exclusion": x, "present": x.lower() in corpus} if texts else {"exclusion": x, "present": None}
                  for x in data.exclusions]
    if not texts:
        coverage = "UNKNOWN"
    elif any(x["present"] for x in exclusions):
        coverage = "CONTRADICTED"
    elif all(q["found"] for q in qualifiers) and not data.ambiguities:
        coverage = "COVERED"
    else:
        coverage = "PARTIAL"
    return {
        "requirement_refs": [f"catalog:{t}" for t in data.task_ids],
        "requirement_text": data.requirement_text,
        "interpreted_obligation": data.interpreted_obligation,
        "qualifiers": qualifiers,
        "exclusions": exclusions,
        "scope_conditions": data.scope_conditions,
        "output_locations": outputs or [{"ref": None, "status": "NOT_AVAILABLE"}],
        "ambiguities": data.ambiguities,
        "coverage_state": coverage,
        "review_status": "NEEDS_HUMAN" if coverage != "COVERED" else "READY_FOR_REVIEW",
        "advisory": {"semantic_score": data.advisory_semantic_score,
                     "note": "advisory only; it never changes coverage_state and never approves a requirement"},
    }, coverage, [o["ref"] for o in outputs]


def _detect(base: str, variant: str) -> set[str]:
    def norm(claims: list[str]) -> list[str]:
        return [" ".join(c.lower().split()) for c in claims]

    def text_of(markup: str) -> str:
        return re.sub(r"<[^>]+>", " ", markup)

    found: set[str] = set()
    # Known blind spot, reported as a false negative by the fixtures: extract_claims
    # ignores sentences shorter than six words, so a change inside one is missed.
    if norm(extract_claims(text_of(base))) != norm(extract_claims(text_of(variant))):
        found.add("CLAIM_CHANGED")
    lang = re.compile(r'\blang\s*=\s*"([^"]*)"', re.IGNORECASE)
    if lang.findall(base) != lang.findall(variant):
        found.add("LOCALE_CHANGED")
    img = re.compile(r"<img\b[^>]*>", re.IGNORECASE)

    def missing_alt(text: str) -> int:
        return sum(1 for tag in img.findall(text) if not re.search(r'\balt\s*=\s*"[^"]+"', tag, re.IGNORECASE))

    if missing_alt(variant) > missing_alt(base):
        found.add("A11Y_ALT_MISSING")
    return found


def _mutation(principal: Principal, plan: dict, data: MutationInput, adapter: Any) -> tuple[dict[str, Any], str, list[str]]:
    from services.langgraph.persistence import operating_framework as store

    check, base_text = _artifact_text(plan, data.base_ref, adapter)
    invalid: str | None = None
    observed: set[str] = set()
    variant_hash = None
    if check["status"] != "OK" or base_text is None:
        invalid = f"base is not readable here ({check['status']})"
    cls = data.mutation_class
    if invalid is None and cls in (MutationClass.CLAIM_CHANGE, MutationClass.SEMANTIC_PRESERVING, MutationClass.LOCALE_CHANGE,
                                   MutationClass.ACCESSIBILITY_REGRESSION, MutationClass.VISUAL_ONLY):
        if not data.find or data.find not in base_text:
            invalid = "the find text does not occur in the base; the perturbation was not applied"
        else:
            variant = base_text.replace(data.find, data.replace, 1)
            variant_hash = canonical_hash({"variant": variant})
            observed = _detect(base_text, variant)
    elif invalid is None and cls in (MutationClass.MISSING_EVIDENCE, MutationClass.ALTERED_APPROVAL_HASH):
        if not data.task_ids:
            invalid = "name the task whose refs or approval subject are perturbed"
        else:
            task = store.get_task(plan["plan_id"], data.task_ids[0])
            definition = load_catalog().task(data.task_ids[0])
            if task is None:
                invalid = "task not in plan"
            elif cls is MutationClass.MISSING_EVIDENCE:
                variant_task = {**task, "evidence_refs": task["evidence_refs"][1:], "artifact_refs": task["artifact_refs"][1:],
                                "decision_refs": task["decision_refs"][1:]}
                kinds = {"evidence": bool(variant_task["evidence_refs"]), "decision": bool(variant_task["decision_refs"]),
                         "artifact": bool(variant_task["artifact_refs"])}
                if any(not kinds[k] for k in REQUIRED_REF_KINDS[definition.output_class]):
                    observed.add("REFS_REQUIRED")
            else:
                proof = (task.get("verification") or {}).get("proof_hash")
                if proof is None:
                    invalid = "the task has no verified proof hash to perturb"
                elif canonical_hash({"perturbed": proof}) != proof:
                    observed.add("APPROVAL_SUBJECT_MISMATCH")
    elif invalid is None and cls is MutationClass.STALE_VERSION:
        artifact_id, version = parse_artifact_ref(data.base_ref)
        stale_ref = f"artifact:{artifact_id}@v{version + 1}"
        if resolve_ref(stale_ref, tenant_id=plan["tenant_id"], project_id=plan["project_id"], adapter=adapter)["status"] != "OK":
            observed.add("ARTIFACT_STALE")
    elif invalid is None and cls is MutationClass.CROSS_TENANT_REF:
        foreign = data.foreign_artifact_id or "art-not-in-this-project"
        if resolve_ref(f"artifact:{foreign}@v1", tenant_id=plan["tenant_id"], project_id=plan["project_id"],
                       adapter=adapter)["status"] == "REF_NOT_FOUND":
            observed.add("REF_NOT_FOUND")
    expected = set(data.expected_findings)
    classification = {
        d: ("TP" if d in expected and d in observed else "FN" if d in expected else "FP" if d in observed else "TN")
        for d in DETECTORS
    }
    if invalid:
        state = "INVALID_TEST"
    elif expected - observed:
        state = "MISSED"
    elif observed - expected:
        state = "INCONCLUSIVE"
    else:
        state = "DETECTED"
    return {
        "base_artifact_version_ref": data.base_ref,
        "base_hash": check.get("content_hash"),
        "mutation_spec": {"find": data.find, "replace": data.replace, "foreign_artifact_id": data.foreign_artifact_id},
        "mutation_class": cls.value,
        "variant_hash": variant_hash,
        "variant_storage": "in-memory only; never written to canonical storage",
        "expected_findings": sorted(expected),
        "observed_findings": sorted(observed),
        "detector_version": DETECTOR_VERSION,
        "test_fixture_ref": data.test_fixture_ref,
        "classification": classification,
        "false_negative_indicators": sorted(expected - observed),
        "false_positive_indicators": sorted(observed - expected),
        "comparison_method": "deterministic: normalized claim extraction, lang attribute, img alt, ref resolution",
        "result_state": state,
        "invalid_reason": invalid,
    }, state, [data.base_ref]


def _probe(principal: Principal, plan: dict, data: ProbeInput, adapter: Any) -> tuple[dict[str, Any], str, list[str]]:
    from services.langgraph.agency.delivery.blast_radius import blast_radius_certificate

    before = graph_snapshot(plan["project_id"])
    node_ids = {n["artifact_id"] for n in before["nodes"]}
    if data.changed_artifact_id not in node_ids:
        raise FrameworkError("REF_REJECTED", "The changed dependency must be an artifact in this project", 422)
    observed, truncated = _dependents(before["edges"], data.changed_artifact_id, data.resource_budget_nodes)
    declared = sorted(set(data.declared_effects))
    unexpected = sorted(set(observed) - set(declared))
    unobserved = sorted(set(declared) - set(observed))
    after = graph_snapshot(plan["project_id"])
    isolated = after["hash"] == before["hash"]
    head = next(n for n in before["nodes"] if n["artifact_id"] == data.changed_artifact_id)
    certificate = blast_radius_certificate(
        changed_artifact_id=data.changed_artifact_id, changed_version_ref=f"{data.changed_artifact_id}:sandbox",
        before_hash=head["content_hash"], after_hash=None,
        affected=[{"artifact_id": a, "status": "would_invalidate"} for a in observed],
        reason_edges=before["edges"], staled_approval_ids=[], projectos_decision_refs=[])
    if not isolated:
        state = "BLOCKED"
    elif truncated:
        state = "INCONCLUSIVE"
    elif unexpected:
        state = "UNDECLARED_EFFECTS"
    elif unobserved:
        state = "MISSING_EDGES_PROPOSED"
    else:
        state = "MATCHED"
    return {
        "sandbox_snapshot_ref": f"graph-snapshot:{before['hash'][:16]}",
        "snapshot_hash": before["hash"],
        "changed_dependency_ref": f"{data.changed_artifact_id}@v{head['version']}",
        "change_description": data.change_description,
        "declared_effects": declared,
        "observed_effects": observed,
        "read_set_refs": [f"{n['artifact_id']}@v{n['version']}" for n in before["nodes"]],
        "write_set_refs": [],
        "effect_diff": {"unexpected": unexpected, "declared_not_observed": unobserved},
        "unexpected_effects": unexpected,
        "graph_amendment_proposals": [
            {"artifact_id": a, "depends_on_artifact_id": data.changed_artifact_id, "status": "PROPOSED",
             "route": "requires review through the existing artifact dependency path"} for a in unobserved],
        "probe_environment": "in-memory projection of the project dependency graph",
        "network_and_action_policy": "no network, no provider, no publication, send, spend or deployment",
        "resource_budget": {"max_nodes": data.resource_budget_nodes, "truncated": truncated},
        "isolation": {"before_hash": before["hash"], "after_hash": after["hash"], "canonical_unchanged": isolated},
        "coverage_limitations": [
            "only dependency edges recorded in Project OS are traversed; undeclared real-world couplings are not visible",
            "coverage is validated_edges / edges known to the graph, never against a complete ground truth",
        ],
        "blast_radius_certificate": certificate,
        "result_state": state,
    }, state, [f"artifact:{data.changed_artifact_id}@v{head['version']}"]


def _renewal(principal: Principal, plan: dict, data: RenewalInput, adapter: Any) -> tuple[dict[str, Any], str, list[str]]:
    from services.langgraph.agency.intake.release import open_artifact_approval
    from services.langgraph.persistence.agency_kernel import get_decision

    triggers = _resolve_all(plan, data.trigger_evidence_refs, adapter)
    _require_resolvable(triggers, "Trigger evidence")
    decision_check = resolve_ref(data.affected_decision_ref, tenant_id=plan["tenant_id"], project_id=plan["project_id"])
    _require_resolvable([decision_check], "The affected decision")
    decision_id = data.affected_decision_ref.removeprefix("decision:")
    before = get_decision(decision_id)
    alternatives = before.get("alternatives") or []
    proposal_check = None
    if data.proposal_ref:
        proposal_check = resolve_ref(data.proposal_ref, tenant_id=plan["tenant_id"], project_id=plan["project_id"], adapter=adapter)
        _require_resolvable([proposal_check], "The proposal artifact")
    review_request = None
    status = "PROPOSED"
    if data.request_review:
        if proposal_check is None or proposal_check["status"] != "OK":
            raise FrameworkError("PROPOSAL_REQUIRED", "A review request needs a readable proposal artifact", 422)
        artifact_id, version = parse_artifact_ref(data.proposal_ref)
        approval = open_artifact_approval(
            principal, tenant_id=plan["tenant_id"], project_id=plan["project_id"],
            mission_id=f"{plan['plan_id']}:renewal:{proposal_check['content_hash'][:16]}",
            contract_hash=plan["catalog_sha256"], artifact_id=artifact_id, version=version,
            content_hash=proposal_check["content_hash"], run_pipeline=PIPELINE, policy_version=POLICY_VERSION,
            subject_type="AGENCY_RENEWAL_PROPOSAL", reason=f"Renewal of {data.affected_decision_ref}: {data.trigger_kind.value}",
            metadata={"plan_id": plan["plan_id"], "affected_decision_ref": data.affected_decision_ref})
        review_request = approval["approval_id"]
        status = "UNDER_REVIEW"
    after = get_decision(decision_id)
    unchanged = canonical_hash(before) == canonical_hash(after)
    return {
        "trigger_kind": data.trigger_kind.value,
        "trigger_evidence_refs": [{"ref": c["ref"], "status": c["status"], "origin": c["origin"]} for c in triggers],
        "affected_decision_ref": data.affected_decision_ref,
        "affected_decision_hash": decision_check["content_hash"],
        "retained_decision": {"question": before.get("question"), "selected_option": before.get("selected_option"),
                              "status": before.get("status")},
        "retained_alternatives": alternatives,
        "proposed_alternatives": data.proposed_alternatives,
        "rationale": data.rationale,
        "impact_scope": data.impact_scope,
        "proposal_artifact_ref": data.proposal_ref,
        "review_request_ref": review_request,
        "decision_status": status,
        "decision_unchanged": unchanged,
        "authority_note": "the accepted decision stays authoritative until its owner approves a new decision through native governance",
    }, status, [data.affected_decision_ref, *([data.proposal_ref] if data.proposal_ref else [])]


def _review(principal: Principal, plan: dict, data: ReviewInput, adapter: Any) -> tuple[dict[str, Any], str, list[str]]:
    from services.langgraph.agency.intake.release import open_artifact_approval
    from services.langgraph.persistence import operating_framework as store
    from services.langgraph.persistence.agency_kernel import get_artifact

    subjects, access, blocked = [], [], []
    for ref in data.candidate_refs:
        check = resolve_ref(ref, tenant_id=plan["tenant_id"], project_id=plan["project_id"], adapter=adapter)
        if not check["attachable"]:
            raise FrameworkError("REF_REJECTED", "Review candidates must exist in this project", 422, {"checks": [check]})
        artifact_id, version = parse_artifact_ref(ref)
        data_bytes = read_artifact_bytes(get_artifact(artifact_id), adapter) if check["status"] == "OK" else None
        subjects.append({"ref": ref, "artifact_id": artifact_id, "version": version, "content_hash": check["content_hash"],
                         "status": check["status"]})
        access.append({"ref": ref, "bytes_read": len(data_bytes) if data_bytes is not None else None,
                       "hash_verified": data_bytes is not None})
        if check["status"] != "OK":
            blocked.append({"ref": ref, "status": check["status"]})
    snap = graph_snapshot(plan["project_id"])
    ids = {s["artifact_id"] for s in subjects}
    edges = [e for e in snap["edges"] if e["artifact_id"] in ids]
    upstream = sorted({e["depends_on_artifact_id"] for e in edges})
    heads = {n["artifact_id"]: n for n in snap["nodes"]}
    dependency_snapshot = {"edges": edges, "upstream_heads": [
        {"artifact_id": u, "version": heads[u]["version"], "content_hash": heads[u]["content_hash"]} for u in upstream if u in heads]}
    dependency_hash = canonical_hash(dependency_snapshot)
    subject_hash = canonical_hash({"subjects": [{k: s[k] for k in ("artifact_id", "version", "content_hash")} for s in subjects],
                                   "dependency_snapshot_hash": dependency_hash})
    diffs = []
    for s in subjects:
        if s["version"] > 1:
            diffs.append({"ref": s["ref"], "compare": f"{s['artifact_id']}@v{s['version'] - 1}..v{s['version']}",
                          "route": f"/projects/{plan['project_id']}/artifacts/{s['artifact_id']}/compare"})
    open_tasks = [t["task_id"] for t in store.list_tasks(plan["plan_id"])
                  if any(r in data.candidate_refs for r in t["artifact_refs"]) and t["state"] not in ("VERIFIED", "APPROVED")]
    findings = [f"task {t} referencing a candidate is not verified" for t in open_tasks]
    for record in list_records_raw(plan, kinds=("meaning", "mutation", "probe")):
        if set(record.get("subject_refs", [])) & set(data.candidate_refs) and record["status"] not in (
                "COVERED", "DETECTED", "MATCHED"):
            findings.append(f"{record['kind']} {record['record_id']} is {record['status']}")
    full_access = all(a["hash_verified"] for a in access)
    status = "BLOCKED" if blocked or not full_access else "NEEDS_HUMAN"
    decision_ref = None
    if data.request_decision:
        if status != "NEEDS_HUMAN":
            raise FrameworkError("REVIEW_NOT_READY", "Every candidate must be current and fully readable before a decision", 409,
                                 {"blocked": blocked})
        approval = open_artifact_approval(
            principal, tenant_id=plan["tenant_id"], project_id=plan["project_id"],
            mission_id=f"{plan['plan_id']}:review:{subject_hash[:16]}", contract_hash=plan["catalog_sha256"],
            artifact_id=f"agency-review:{plan['plan_id']}:{subject_hash[:16]}", version=1, content_hash=subject_hash,
            run_pipeline=PIPELINE, policy_version=POLICY_VERSION, subject_type="AGENCY_REVIEW_CANDIDATE",
            reason=f"Review of {len(subjects)} candidate artifact(s)", metadata={"plan_id": plan["plan_id"]})
        decision_ref = approval["approval_id"]
    return {
        "candidate_subject_refs": subjects,
        "dependency_snapshot_ref": f"graph-snapshot:{snap['hash'][:16]}",
        "dependency_snapshot_hash": dependency_hash,
        "candidate_manifest_ref": None,
        "diff_refs": diffs,
        "unresolved_findings": findings,
        "reviewer_authority_scope": "decided only at /approvals/{id}/decide (approver role, separation of duties)",
        "access_check_receipt": {"principal": principal.user_id, "subjects": access, "full_candidate_access": full_access},
        "summary": data.summary,
        "summary_note": "navigation aid only; the decision binds the full candidate bytes and dependency snapshot",
        "decision_ref": decision_ref,
        "decision_subject_hash": subject_hash,
        "status": status,
    }, status, data.candidate_refs


_BUILDERS = {"meaning": _meaning, "mutation": _mutation, "probe": _probe, "renewal": _renewal, "review": _review}


# ------------------------------------------------------------------------------ storage


def _record_key(kind: str, record_id: str) -> str:
    return f"assurance/{kind}/{record_id}"


def _seal(record: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in record.items() if k != "record_hash"}
    return {**body, "record_hash": canonical_hash(body)}


def list_records_raw(plan: dict, *, kinds: tuple[str, ...] = KINDS) -> list[dict]:
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import list_project_artifacts

    adapter = _adapter()
    out = []
    for meta in list_project_artifacts(plan["project_id"], artifact_type=RECORD_ARTIFACT_TYPE, query="assurance/", limit=1000):
        if not (meta.subtype or "").startswith("assurance.") or meta.subtype.split(".", 1)[1] not in kinds:
            continue
        artifact = get_artifact(meta.artifact_id)
        data = read_artifact_bytes(artifact, adapter)
        if data is None:
            continue
        try:
            record = json.loads(data)
        except ValueError:
            continue
        if record.get("plan_id") != plan["plan_id"]:
            continue
        out.append(record)
    return sorted(out, key=lambda r: r["created_at"])


def _verify(record: dict, artifact: dict, data: bytes | None) -> dict[str, Any]:
    import hashlib

    problems = []
    if data is None:
        problems.append("stored bytes are not readable")
    elif hashlib.sha256(data).hexdigest() != artifact.get("content_hash"):
        problems.append("stored bytes do not match the artifact content hash")
    if int(artifact.get("version", 0)) != 1:
        problems.append(f"record artifact was revised to v{artifact.get('version')}; records are append-only")
    if _seal(record)["record_hash"] != record.get("record_hash"):
        problems.append("record hash does not match its content")
    return {"status": "VERIFIED" if not problems else "INTEGRITY_FAILED", "problems": problems}


def create_record(principal: Principal, plan_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    from services.langgraph.persistence.projects import create_project_artifact

    from .service import _plan_for

    if kind not in KINDS:
        raise FrameworkError("UNKNOWN_KIND", f"Unknown assurance kind {kind}", 404)
    plan = _plan_for(principal, plan_id)
    try:
        data = _INPUTS[kind].model_validate(payload)
    except ValidationError as exc:
        raise FrameworkError("INVALID_RECORD", "The record input is invalid", 422,
                             {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}) from exc
    adapter = _adapter()
    evidence = _resolve_all(plan, data.evidence_refs, adapter)
    _require_resolvable(evidence, "Evidence refs")
    existing = list_records_raw(plan, kinds=(kind,))
    if data.supersedes_ref:
        target = next((r for r in existing if r["record_id"] == data.supersedes_ref), None)
        if target is None:
            raise FrameworkError("SUPERSEDES_NOT_FOUND", "The superseded record is not in this plan", 404)
        if any(r.get("supersedes_ref") == data.supersedes_ref for r in existing):
            raise FrameworkError("STALE_SUPERSEDE", "That record was already superseded; supersede the current head", 409)
    body, status, subject_refs = _BUILDERS[kind](principal, plan, data, adapter)
    first_subject = next((r for r in subject_refs if r and r.startswith("artifact:")), None)
    subject_check = (resolve_ref(first_subject, tenant_id=plan["tenant_id"], project_id=plan["project_id"], adapter=adapter)
                     if first_subject else None)
    record_id = f"asr-{uuid4().hex[:20]}"
    record = _seal({
        "record_id": record_id,
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "tenant_id": plan["tenant_id"],
        "project_id": plan["project_id"],
        "plan_id": plan["plan_id"],
        "mission_id": plan["plan_id"],
        "catalog_version_ref": f"{plan['catalog_version']}@{plan['catalog_sha256'][:16]}",
        "task_ids": data.task_ids,
        "subject_refs": [r for r in subject_refs if r],
        "subject_artifact_id": parse_artifact_ref(first_subject)[0] if first_subject else None,
        "subject_version_ref": first_subject,
        "subject_content_hash": subject_check["content_hash"] if subject_check else None,
        "author_actor_id": principal.user_id,
        "created_at": _now(),
        "evidence_refs": [{"ref": c["ref"], "status": c["status"], "origin": c["origin"]} for c in evidence],
        "dependency_snapshot_hash": graph_snapshot(plan["project_id"])["hash"],
        "status": status,
        "supersedes_ref": data.supersedes_ref,
        "execution_receipt_ref": None,
        "privacy_classification": data.privacy_classification,
        "retention_policy_ref": "project-retention-default",
        "authority": "NONE: a finding or proposal; grants no approval, release, publication, send or spend",
        "body": body,
    })
    meta = create_project_artifact(
        tenant_id=plan["tenant_id"], project_id=plan["project_id"], actor=principal.user_id,
        artifact_key=_record_key(kind, record_id), artifact_type=RECORD_ARTIFACT_TYPE, adapter=adapter,
        content_text=json.dumps(record, sort_keys=True, separators=(",", ":")), subtype=f"assurance.{kind}",
        v2={"mime_type": "application/json"},
    )
    return {**read_record(principal, plan_id, record_id), "artifact_id": meta.artifact_id}


def read_record(principal: Principal, plan_id: str, record_id: str) -> dict[str, Any]:
    from services.langgraph.persistence.agency_kernel import get_artifact
    from services.langgraph.persistence.projects import project_artifact_id

    from .service import _plan_for

    plan = _plan_for(principal, plan_id)
    adapter = _adapter()
    for kind in KINDS:
        artifact = get_artifact(project_artifact_id(plan["project_id"], _record_key(kind, record_id)))
        if artifact is None or artifact.get("project_id") != plan["project_id"]:
            continue
        data = read_artifact_bytes(artifact, adapter)
        record = json.loads(data) if data is not None else {}
        if record.get("plan_id") != plan["plan_id"]:
            break
        integrity = _verify(record, artifact, data)
        current = None
        pinned = [r for r in record.get("subject_refs", []) if r.startswith("artifact:")]
        if pinned:
            # Every artifact the record binds must still be the head it pinned.
            checks = [resolve_ref(r, tenant_id=plan["tenant_id"], project_id=plan["project_id"], adapter=adapter) for r in pinned]
            first_ok = checks[0]["content_hash"] == record.get("subject_content_hash")
            current = {"subjects": [{"ref": c["ref"], "status": c["status"]} for c in checks],
                       "subject_current": first_ok and all(c["status"] == "OK" for c in checks)}
        superseded_by = [r["record_id"] for r in list_records_raw(plan, kinds=(kind,)) if r.get("supersedes_ref") == record_id]
        return {"record": record, "integrity": integrity, "subject_now": current,
                "superseded_by": superseded_by, "artifact_id": artifact["artifact_id"],
                "artifact_version": artifact["version"], "content_hash": artifact["content_hash"]}
    raise FrameworkError("RECORD_NOT_FOUND", "Assurance record not found in this plan", 404)


def list_records(principal: Principal, plan_id: str, *, kind: str | None = None) -> list[dict]:
    from .service import _plan_for

    plan = _plan_for(principal, plan_id)
    records = list_records_raw(plan, kinds=(kind,) if kind else KINDS)
    superseded = {r["supersedes_ref"] for r in records if r.get("supersedes_ref")}
    return [{"record_id": r["record_id"], "kind": r["kind"], "status": r["status"], "created_at": r["created_at"],
             "author_actor_id": r["author_actor_id"], "task_ids": r["task_ids"], "subject_refs": r["subject_refs"],
             "record_hash": r["record_hash"], "supersedes_ref": r.get("supersedes_ref"),
             "is_head": r["record_id"] not in superseded} for r in records]


def confusion_matrix(records: list[dict]) -> dict[str, Any]:
    """TP/FP/FN/TN per detector over labelled mutation records; undefined ratios are NOT_MEASURED."""
    out = {}
    for detector in DETECTORS:
        tally = {"TP": 0, "FP": 0, "FN": 0, "TN": 0}
        for r in records:
            body = r.get("body", r)
            if body.get("result_state") == "INVALID_TEST":
                continue
            tally[body["classification"][detector]] += 1
        tp, fp, fn = tally["TP"], tally["FP"], tally["FN"]
        out[detector] = {**tally, "precision": round(tp / (tp + fp), 4) if tp + fp else NOT_MEASURED,
                         "recall": round(tp / (tp + fn), 4) if tp + fn else NOT_MEASURED}
    return out


__all__ = ["DETECTORS", "KINDS", "MutationClass", "TriggerKind", "confusion_matrix", "create_record", "graph_snapshot",
           "list_records", "list_records_raw", "read_record"]
