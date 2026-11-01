"""A single fixed local experiment through canonical fabric permits/receipts.

Preserves the original innovation run and its SIMULATED provenance. The local
computation is real, while the inputs and added case/whitespace variants are
disclosed synthetic test cases. Nothing here approves release or calls a model.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.langgraph.agency.compiled.backchain import DeliverableSpec, EvidenceItem
from services.langgraph.agency.compiled.planner import CompiledAgencyRequest, compile_agency_plan
from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.execution_fabric.adapters.innovation import EXECUTOR_VERSION, SKILL_ID, LexicalInput
from services.langgraph.agency.execution_fabric.consumer import execute_mission
from services.langgraph.agency.execution_fabric.contracts import ExecutionContext, ExecutionState, FabricBudget
from services.langgraph.agency.execution_fabric.schedule import from_compiled_agency_plan
from services.langgraph.agency.project_os.storage import StorageIntegrityError
from services.langgraph.agency.role_os import RoleOSRegistry
from services.langgraph.api.routes._project_common import authorize_project_access
from services.langgraph.persistence.agency_kernel import ensure_artifact_dependency, get_artifact
from services.langgraph.persistence.database import atomic_transaction, is_postgres, table, transaction
from services.langgraph.persistence.projects import create_project_artifact, project_artifact_id
from services.langgraph.persistence.proofs import get_run_proof_bundle
from services.langgraph.persistence.runs import get_run_record

from .service import _artifact_id, _check_version, _read

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = "innovation.local-experiment/v1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LocalMeasurements(_Strict):
    case_count: int = Field(ge=1, le=64)
    baseline_retained_items: int = Field(ge=0, le=64)
    candidate_retained_items: int = Field(ge=0, le=64)
    baseline_redundant_items: int = Field(ge=0, le=64)
    candidate_redundant_items: int = Field(ge=0, le=64)
    unit: Literal["items"]


class LocalLearning(_Strict):
    decision: Literal["SUPPORTED", "DISCONFIRMED"]
    rule: str
    interpretation: str
    next_action: str
    limitations: list[str]


class LocalExperimentCompleted(_Strict):
    schema_version: Literal["innovation.local-experiment/v1"]
    status: Literal["COMPLETED"]
    execution_mode: Literal["LOCAL_COMPUTATION"]
    experiment_id: str
    input_provenance: Literal["SIMULATED_OFFLINE_FIXTURE"]
    source_ref: str
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_ref: str
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_ref: str
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    executor_version: Literal["innovation.lexical-normalization/v1"]
    measurements: LocalMeasurements
    fabric_run_id: str
    learning: LocalLearning
    release_authorized: Literal[False]
    # The canonical proof bundle remains a read projection, never new authority.
    proof: dict[str, Any]
    replayed: bool


class LocalExperimentBlocked(_Strict):
    schema_version: Literal["innovation.local-experiment/v1"]
    status: Literal["BLOCKED"]
    report: dict[str, Any]
    limitations: list[str]


LocalExperimentReport = LocalExperimentCompleted | LocalExperimentBlocked


def _inputs(document, head) -> LexicalInput:
    if document.run.status != "COMPLETED" or not document.run.simulation:
        raise HTTPException(409, "Local fixture experiment requires a completed disclosed simulation")
    values = [concept.mechanism for concept in document.run.ideas]
    # Four explicitly synthetic representation variants, not new concepts.
    values += ["  " + text.upper().replace(" ", "   ") + "  " for text in values[:4]]
    return LexicalInput(source_ref=f"{head['artifact_id']}:v{head['version']}", source_hash=head["content_hash"],
                        input_provenance="SIMULATED_OFFLINE_FIXTURE", mechanisms=values)


def _plan(inputs: LexicalInput) -> dict:
    return {"schema_version": SCHEMA, "executor_version": EXECUTOR_VERSION,
            "input": inputs.model_dump(mode="json"), "input_hash": canonical_hash(inputs),
            "hypothesis": "Case/whitespace normalization retains fewer redundant representations than exact-string deduplication.",
            "comparator": "Stable exact-string deduplication", "method": "Count retained normalized equivalence duplicates",
            "metric": "redundant retained items", "unit": "items", "sample_bound": 64,
            "falsification_rule": "Disconfirm if candidate redundancy is not less than baseline redundancy.",
            "decision_rule": "SUPPORTED iff candidate_redundant_items < baseline_redundant_items; otherwise DISCONFIRMED",
            "stop_rule": "At most 64 strings of at most 2000 characters; no external calls or generated code",
            "effect_class": "RETRY_SAFE", "release_authorized": False,
            "limitations": ["Four derived case/whitespace variants added to the simulated input cohort.",
                            "This is an algorithm rehearsal, not a test of concept relevance or market validity."]}


def _artifact_json(principal, project_id, artifact_id, adapter):
    authorize_project_access(principal, project_id)
    head = get_artifact(artifact_id)
    if not head or (head["tenant_id"], head["project_id"]) != (principal.tenant_id, project_id):
        raise HTTPException(404, "Local experiment artifact not found")
    data = adapter.get_bytes(head["content_location"])
    if len(data) > 512_000 or hashlib.sha256(data).hexdigest() != head["content_hash"]:
        raise StorageIntegrityError("Local experiment bytes differ from the recorded artifact")
    return json.loads(data), head


def _store(principal, project_id, key, content, adapter, dependencies):
    artifact_id = project_artifact_id(project_id, key)
    head = get_artifact(artifact_id)
    if head is None:
        create_project_artifact(tenant_id=principal.tenant_id, project_id=project_id, actor=principal.user_id,
                                artifact_key=key, artifact_type="research_brief", subtype="innovation_local_experiment",
                                content_text=json.dumps(content, sort_keys=True, separators=(",", ":")),
                                adapter=adapter, depends_on=dependencies, v2={"mime_type": "application/json", "media_type": "data"})
    actual, head = _artifact_json(principal, project_id, artifact_id, adapter)
    if actual != content:
        raise StorageIntegrityError("A different local experiment already occupies this immutable identity")
    return head


def _schedule(project_id, plan, plan_head, source_head):
    # Facts are checked against actual persisted input, not invented external sources.
    refs = (f"{source_head['artifact_id']}:v{source_head['version']}#/input_hash",
            f"{source_head['artifact_id']}:v{source_head['version']}#/run/ideas",
            f"{plan_head['artifact_id']}:v{plan_head['version']}#/decision_rule")
    spec = DeliverableSpec(id="lexical-" + plan_head["content_hash"][:20],
        requested_outcome="Measure disclosed lexical representations for " + plan_head["content_hash"],
        output_contract="research_brief", acceptance_criteria=("actual bounded counts", "independent storage readback"),
        source_refs=refs, domains=("BRAND",))
    request = CompiledAgencyRequest(project_id=project_id, as_of=plan_head["created_at"], deliverables=(spec,),
        evidence=tuple(EvidenceItem(ref=ref, supports=("research_brief",), verified=True) for ref in refs))
    return from_compiled_agency_plan(compile_agency_plan(request, registry=RoleOSRegistry(ROOT / "runtime" / "role_os")))


def _locked_source(principal, project_id, run_id, expected_version, adapter):
    authorize_project_access(principal, project_id)
    if is_postgres():
        with transaction() as db:
            db.execute(f"SELECT artifact_id FROM {table('agency_artifacts')} WHERE artifact_id = ? FOR UPDATE",
                       (_artifact_id(project_id, run_id),)).fetchone()
    document, head = _read(principal, project_id, run_id, adapter)
    _check_version(head, expected_version)
    return document, head


def run_local_experiment(principal, project_id, run_id, expected_version, adapter) -> dict:
    with atomic_transaction():
        document, source = _locked_source(principal, project_id, run_id, expected_version, adapter)
        inputs = _inputs(document, source)
        plan = _plan(inputs)
        identity = canonical_hash(plan)[:24]
        plan_head = _store(principal, project_id, "innovation-plan-" + identity, plan, adapter, (source["artifact_id"],))
        schedule = _schedule(project_id, plan, plan_head, source)
        context = ExecutionContext.from_server(tenant_id=principal.tenant_id, project_id=project_id,
            actor=principal.user_id, mode="LOCAL", export_root=ROOT,
            budget=FabricBudget(max_invocations=1, max_output_bytes=64_000, max_attempts_per_cell=1, max_tool_calls_per_node=1))
        report = execute_mission(schedule, context, node_inputs={"work:research_brief": inputs.model_dump(mode="json")},
                                 skill_overrides={"work:research_brief": SKILL_ID}, adapter=adapter)
        outcome = report.cells["cell:research_brief"]
        if outcome.state != ExecutionState.SUCCEEDED:
            return {"schema_version": SCHEMA, "status": "BLOCKED", "report": report.model_dump(mode="json"),
                    "limitations": ["No local observation committed; inspect canonical fabric blockers."]}
        return _persist_report(principal, project_id, identity, source, plan_head, report, adapter)


def _persist_report(principal, project_id, identity, source, plan_head, report, adapter):
    outcome = report.cells["cell:research_brief"]
    result_id = outcome.artifact_ref.rsplit(":v", 1)[0]
    measured, result_head = _artifact_json(principal, project_id, result_id, adapter)
    ensure_artifact_dependency(result_id, plan_head["artifact_id"])
    proof = _proof(principal, project_id, report.run_id, outcome.artifact_ref, report.plan_hash)
    measurements = measured["measurements"]
    result = {"schema_version": SCHEMA, "status": "COMPLETED", "execution_mode": "LOCAL_COMPUTATION",
              "experiment_id": "lexical-" + identity, "input_provenance": "SIMULATED_OFFLINE_FIXTURE",
              "source_ref": f"{source['artifact_id']}:v{source['version']}", "source_hash": source["content_hash"],
              "plan_ref": f"{plan_head['artifact_id']}:v{plan_head['version']}", "plan_hash": plan_head["content_hash"],
              "result_ref": outcome.artifact_ref, "result_hash": result_head["content_hash"],
              "input_hash": measured["input_hash"], "executor_version": EXECUTOR_VERSION,
              "measurements": measurements, "fabric_run_id": report.run_id,
              "learning": _learning(measured),
              "release_authorized": False}
    _store(principal, project_id, "innovation-learning-" + identity, result, adapter,
           (source["artifact_id"], plan_head["artifact_id"], result_id))
    return LocalExperimentCompleted.model_validate({**result, "proof": proof, "replayed": bool(outcome.replayed)}).model_dump(mode="json")


def _learning(measured):
    values = measured["measurements"]
    decision = "SUPPORTED" if values["candidate_redundant_items"] < values["baseline_redundant_items"] else "DISCONFIRMED"
    return {"decision": decision, "rule": "candidate_redundant_items < baseline_redundant_items",
            "interpretation": "Only the preregistered lexical fixture comparison was evaluated.",
            "next_action": "Independent semantic relevance review remains required.",
            "limitations": measured["limitations"]}


def _proof(principal, project_id, fabric_run_id, result_ref, plan_hash):
    record = get_run_record(fabric_run_id)
    if not record or (record["tenant_id"], record["project_id"]) != (principal.tenant_id, project_id):
        raise StorageIntegrityError("Experiment proof run is outside the authorized project")
    if (record.get("metadata") or {}).get("plan_hash") != plan_hash:
        raise StorageIntegrityError("Experiment proof does not bind the current plan")
    proof = get_run_proof_bundle(fabric_run_id)
    counts = ("dispatch_count", "execution_count", "observation_count", "matched_observation_count")
    if any(proof["summary"][key] != 1 for key in counts) or len(proof["execution_receipts"]) != 1:
        raise StorageIntegrityError("One matched canonical observation and execution receipt is required")
    execution = proof["execution_receipts"][0]
    observation = proof["observation_receipts"][0]
    permit = proof["dispatch_permits"][0]
    if execution["result_ref"] != result_ref or execution["operation_id"] != observation["operation_id"]:
        raise StorageIntegrityError("Experiment execution receipt refers to different result bytes")
    if permit["work_order_id"] != execution["work_order_id"]:
        raise StorageIntegrityError("Experiment execution receipt does not match its dispatch permit")
    return proof


def read_report(principal, project_id, run_id, expected_version, adapter) -> dict:
    document, source = _read(principal, project_id, run_id, adapter)
    _check_version(source, expected_version)
    inputs = _inputs(document, source)
    plan = _plan(inputs)
    identity = canonical_hash(plan)[:24]
    report, _ = _artifact_json(principal, project_id, project_artifact_id(project_id, "innovation-learning-" + identity), adapter)
    actual_plan, plan_head = _artifact_json(principal, project_id, project_artifact_id(project_id, "innovation-plan-" + identity), adapter)
    if actual_plan != plan or report["plan_hash"] != plan_head["content_hash"] or report["plan_ref"] != f"{plan_head['artifact_id']}:v{plan_head['version']}":
        raise StorageIntegrityError("Preregistered experiment plan changed")
    if report["source_hash"] != source["content_hash"] or report["source_ref"] != inputs.source_ref:
        raise StorageIntegrityError("Experiment report refers to different source input")
    result_id = report["result_ref"].rsplit(":v", 1)[0]
    measured, result_head = _artifact_json(principal, project_id, result_id, adapter)
    if result_head["content_hash"] != report["result_hash"] or report["result_ref"] != f"{result_id}:v{result_head['version']}":
        raise StorageIntegrityError("Local experiment result changed after learning was recorded")
    if measured["input_hash"] != canonical_hash(inputs) or report["input_hash"] != canonical_hash(inputs):
        raise StorageIntegrityError("Experiment measurement refers to different admitted input")
    if report["measurements"] != measured["measurements"] or report["learning"] != _learning(measured):
        raise StorageIntegrityError("Learning differs from actual observations or the preregistered decision rule")
    schedule = _schedule(project_id, plan, plan_head, source)
    proof = _proof(principal, project_id, report["fabric_run_id"], report["result_ref"], schedule.plan_hash)
    return LocalExperimentCompleted.model_validate({**report, "proof": proof, "replayed": True}).model_dump(mode="json")
