"""Two-phase release handshake: candidate before approval, receipt after.

1. ``ReleaseCandidateManifest`` is sealed *before* a reviewer decides. It names
   the exact artifact versions, the contract and its result, the policy version
   and a dependency snapshot. It cannot carry an approval decision, a delivery
   time or a receipt: the schema forbids unknown fields, so a manifest with an
   approval embedded in it is rejected rather than hashed.
2. The approval record's ``subject_hash`` is bound to
   ``approval_subject_hash(candidate, contract, policy)``. A method-only change
   (a different plan producing the same candidate) leaves that hash, and so the
   approval, untouched.
3. ``evaluate_release_predicate`` is the release gate. It only reads facts the
   existing authorities produced (N2 guard codes, the critic's verdict, the
   approval record, ProjectOS artifact and dependency state, the compile gate);
   it adds no authority of its own.
4. ``ReleaseReceipt`` is sealed *after* delivery from what was actually
   released. It is evidence and never grants permission. ``ReleaseWitness`` is
   only an alias for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.langgraph.agency.execution.canonical import canonical_hash

CANDIDATE_SCHEMA_VERSION = "amc-release-candidate/v1"
RECEIPT_SCHEMA_VERSION = "amc-release-receipt/v1"
RELEASE_POLICY_VERSION = "amc-release/v1"

FailureClass = Literal["routing", "contract", "tool", "authority", "dependency", "provider", "evaluator", "runtime"]
FAILURE_CLASSES: tuple[str, ...] = ("routing", "contract", "tool", "authority", "dependency", "provider", "evaluator", "runtime")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactRef(_Strict):
    artifact_id: str = Field(min_length=1)
    version_ref: str = Field(min_length=1)
    content_hash: Optional[str] = None


def _sorted_refs(refs: Iterable[ArtifactRef]) -> tuple[ArtifactRef, ...]:
    ordered = tuple(sorted(refs, key=lambda r: r.artifact_id.encode("utf-8")))
    ids = [r.artifact_id for r in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("artifact_refs must not repeat an artifact_id")
    return ordered


class ReleaseCandidateManifest(_Strict):
    schema_version: Literal["amc-release-candidate/v1"] = CANDIDATE_SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    contract_hash: str = Field(min_length=1)
    artifact_refs: tuple[ArtifactRef, ...]
    contract_result_refs: tuple[str, ...]
    policy_version: str = Field(min_length=1)
    dependency_snapshot_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def _canonical_order(self) -> "ReleaseCandidateManifest":
        if self.artifact_refs != _sorted_refs(self.artifact_refs):
            raise ValueError("artifact_refs must be sorted by artifact_id")
        return self


def build_candidate_manifest(
    *,
    run_id: str,
    project_id: str,
    contract_hash: str,
    artifact_refs: Iterable[ArtifactRef],
    contract_result_refs: Sequence[str],
    dependency_snapshot_hash: str,
    policy_version: str = RELEASE_POLICY_VERSION,
) -> ReleaseCandidateManifest:
    return ReleaseCandidateManifest(
        run_id=run_id,
        project_id=project_id,
        contract_hash=contract_hash,
        artifact_refs=_sorted_refs(artifact_refs),
        contract_result_refs=tuple(contract_result_refs),
        policy_version=policy_version,
        dependency_snapshot_hash=dependency_snapshot_hash,
    )


def candidate_manifest_hash(manifest: ReleaseCandidateManifest) -> str:
    return canonical_hash(manifest.model_dump(mode="json"))


def approval_subject_hash(*, candidate_manifest_hash: str, contract_hash: str, policy_version: str) -> str:
    return canonical_hash(
        {
            "candidate_manifest_hash": candidate_manifest_hash,
            "contract_hash": contract_hash,
            "policy_version": policy_version,
        }
    )


def dependency_snapshot_hash(edges: Iterable[Mapping[str, Any]]) -> str:
    """Hash of the dependency edges touching the candidate's artifacts.

    Each edge is ``{artifact_id, depends_on_artifact_id, relationship,
    depends_on_version_ref}``; order does not matter.
    """

    normalized = sorted(
        (
            {
                "artifact_id": str(edge["artifact_id"]),
                "depends_on_artifact_id": str(edge["depends_on_artifact_id"]),
                "relationship": str(edge.get("relationship") or "hard"),
                "depends_on_version_ref": str(edge.get("depends_on_version_ref") or ""),
            }
            for edge in edges
        ),
        key=lambda e: (e["artifact_id"].encode("utf-8"), e["depends_on_artifact_id"].encode("utf-8")),
    )
    return canonical_hash(normalized)


@dataclass(frozen=True)
class ReleaseBlock:
    code: str
    failure_class: FailureClass
    detail: str


@dataclass(frozen=True)
class ReleaseFacts:
    """Everything the gate reads, each produced by an existing authority."""

    n2_failure_codes: tuple[str, ...]
    contract_dod: Optional[str]
    contract_result_hash: Optional[str]
    approval: Optional[Mapping[str, Any]]
    expected_approval_subject_hash: str
    sealed_candidate: ReleaseCandidateManifest
    current_artifact_refs: tuple[ArtifactRef, ...]
    current_dependency_snapshot_hash: str
    compile_blocked: bool


def evaluate_release_predicate(facts: ReleaseFacts) -> list[ReleaseBlock]:
    """Every reason release is not permitted; empty means permitted.

    N2_PASS ∧ CONTRACT_DOD_PASS ∧ APPROVAL_APPROVED_AND_NON_STALE
    ∧ approval.subject_hash == approval_subject_hash
    ∧ CURRENT_ARTIFACTS_MATCH ∧ CURRENT_DEPENDENCIES_MATCH
    ∧ COMPILE_INVALIDATION_GATE_PASS
    """

    blocks: list[ReleaseBlock] = []
    for code in facts.n2_failure_codes:
        failure_class: FailureClass = "provider" if code == "degraded_release_block" else "authority"
        blocks.append(ReleaseBlock(f"N2:{code}", failure_class, "N2 release guard failed"))

    approval = facts.approval or {}
    approved = approval.get("status") == "resolved" and approval.get("decision") == "approve"
    dod = facts.contract_dod
    if dod is None or facts.contract_result_hash is None:
        blocks.append(ReleaseBlock("CONTRACT_NOT_EVALUATED", "contract", "no contract result for this run"))
    elif dod == "FAIL":
        blocks.append(ReleaseBlock("CONTRACT_FAILED", "contract", "a blocking contract requirement failed"))
    elif dod == "ESCALATE":
        blocks.append(ReleaseBlock("CONTRACT_ESCALATED", "contract", "a blocking requirement could not be measured"))
    elif dod == "NEEDS_HUMAN" and not approved:
        blocks.append(ReleaseBlock("CONTRACT_NEEDS_HUMAN", "contract", "human review requirements await the approval"))
    if facts.contract_result_hash is not None and facts.contract_result_hash not in facts.sealed_candidate.contract_result_refs:
        blocks.append(ReleaseBlock("CONTRACT_RESULT_CHANGED", "contract", "contract result differs from the sealed candidate"))

    if not approval:
        blocks.append(ReleaseBlock("APPROVAL_MISSING", "authority", "no approval for this run"))
    elif approval.get("status") == "stale":
        blocks.append(ReleaseBlock("APPROVAL_STALE", "authority", "approval is stale"))
    elif not approved:
        blocks.append(ReleaseBlock("APPROVAL_NOT_APPROVED", "authority", "approval is not an approve decision"))
    if approval and approval.get("subject_hash") != facts.expected_approval_subject_hash:
        blocks.append(ReleaseBlock("APPROVAL_SUBJECT_MISMATCH", "authority", "approval subject is not this candidate"))

    if _sorted_refs(facts.current_artifact_refs) != facts.sealed_candidate.artifact_refs:
        blocks.append(ReleaseBlock("ARTIFACTS_CHANGED", "dependency", "artifact versions differ from the sealed candidate"))
    if facts.current_dependency_snapshot_hash != facts.sealed_candidate.dependency_snapshot_hash:
        blocks.append(ReleaseBlock("DEPENDENCIES_CHANGED", "dependency", "dependency snapshot differs from the sealed candidate"))
    if facts.compile_blocked:
        blocks.append(ReleaseBlock("COMPILE_BLOCKED", "dependency", "open invalidation obligations or stale approvals"))
    return blocks


class ReleaseReceiptMismatch(ValueError):
    """What was released is not what was approved."""


class ReleaseReceipt(_Strict):
    schema_version: Literal["amc-release-receipt/v1"] = RECEIPT_SCHEMA_VERSION
    candidate_manifest_hash: str
    approval_id: str
    approval_subject_hash: str
    authority_ref: str
    policy_version: str
    delivery_receipt_ref: str
    released_artifact_refs: tuple[ArtifactRef, ...]
    released_at: str
    execution_lineage_hash: str


# A witness is the receipt viewed as proof; there is no separate lifecycle.
ReleaseWitness = ReleaseReceipt


def build_release_receipt(
    *,
    candidate: ReleaseCandidateManifest,
    approval: Mapping[str, Any],
    released_artifact_refs: Iterable[ArtifactRef],
    delivery_receipt_ref: str,
    released_at: str,
    execution_lineage_hash: str,
) -> ReleaseReceipt:
    released = _sorted_refs(released_artifact_refs)
    if released != candidate.artifact_refs:
        raise ReleaseReceiptMismatch("released artifact versions differ from the approved candidate")
    return ReleaseReceipt(
        candidate_manifest_hash=candidate_manifest_hash(candidate),
        approval_id=str(approval["approval_id"]),
        approval_subject_hash=str(approval["subject_hash"]),
        authority_ref=str(approval.get("authority_ref") or "human-review"),
        policy_version=candidate.policy_version,
        delivery_receipt_ref=delivery_receipt_ref,
        released_artifact_refs=released,
        released_at=released_at,
        execution_lineage_hash=execution_lineage_hash,
    )


def release_receipt_hash(receipt: ReleaseReceipt) -> str:
    return canonical_hash(receipt.model_dump(mode="json"))


# Attributes safe to export with a contract.check or release.gate observation:
# identifiers, hashes, verdicts and counts. Never prompts, contract text,
# matched phrases, PII or secrets.
SAFE_TELEMETRY_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "run_id", "project_id", "node_id", "contract_hash", "request_hash", "plan_hash", "method_id",
        "candidate_manifest_hash", "repair_cycle", "critic_verdict", "authority_result",
        "failure_class", "duration", "tokens", "workflow_version", "contract_mode", "block_codes",
    }
)


def safe_attributes(**attributes: Any) -> dict[str, Any]:
    unknown = set(attributes) - SAFE_TELEMETRY_ATTRIBUTES
    if unknown:
        raise ValueError(f"not a safe telemetry attribute: {sorted(unknown)}")
    return {key: value for key, value in attributes.items() if value is not None}
