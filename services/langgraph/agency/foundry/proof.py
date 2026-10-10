"""Proof-carrying creative assets: the proof state is computed from evidence, never asserted.

SPECIFIED -> COMPILED -> EXECUTED -> OUTPUT_OBSERVED -> VERIFIED -> APPROVAL_PENDING -> APPROVED -> RELEASE_ELIGIBLE

``proof_state`` walks the chain and stops at the first transition whose proof
is missing; ``blocked_at`` names it. A simulated run never has observed output
bytes, so it can never pass OUTPUT_OBSERVED.
"""

from __future__ import annotations

from typing import Optional

from .contracts import ArtifactProof, ProofState

ORDER = list(ProofState)


def proof_state(*, source_hash: Optional[str], compiled_ir_hash: Optional[str], executed: bool,
                observed_sha256: Optional[str], recorded_sha256: Optional[str], validations: tuple[dict, ...],
                approval: Optional[dict], release_allowed: bool) -> tuple[ProofState, Optional[str]]:
    checks: list[tuple[ProofState, bool, str]] = [
        (ProofState.SPECIFIED, bool(source_hash), "NO_SOURCE_HASH"),
        (ProofState.COMPILED, bool(compiled_ir_hash), "NOT_COMPILED"),
        (ProofState.EXECUTED, executed, "NOT_EXECUTED"),
        (ProofState.OUTPUT_OBSERVED, bool(observed_sha256) and observed_sha256 == recorded_sha256, "OUTPUT_NOT_OBSERVED_OR_HASH_MISMATCH"),
        (ProofState.VERIFIED, bool(validations) and all(v.get("passed") is True for v in validations), "VALIDATION_NOT_PASSED"),
        (ProofState.APPROVAL_PENDING, approval is not None, "NO_APPROVAL_REQUESTED"),
        (ProofState.APPROVED, bool(approval) and approval.get("status") == "resolved" and approval.get("decision") == "approve"
         and approval.get("subject_hash") == observed_sha256, "NOT_APPROVED_FOR_THESE_BYTES"),
        (ProofState.RELEASE_ELIGIBLE, release_allowed, "RELEASE_GATE_REFUSED"),
    ]
    reached: Optional[ProofState] = None
    for state, ok, reason in checks:
        if not ok:
            return (reached or ProofState.SPECIFIED), (reason if reached or state is not ProofState.SPECIFIED else reason)
        reached = state
    return ProofState.RELEASE_ELIGIBLE, None


def build_proof(*, project_ref: str, artifact_ref: Optional[str], version_ref: Optional[int], source_hash: str,
                compiled_ir_hash: Optional[str], renderer_id: Optional[str], renderer_version: Optional[str],
                executed: bool, observed_sha256: Optional[str], recorded_sha256: Optional[str], mime_type: Optional[str],
                observed_dimensions: Optional[str], file_size: Optional[int], dependency_hashes: tuple[str, ...] = (),
                license_refs: tuple[str, ...] = (), validations: tuple[dict, ...] = (), approval: Optional[dict] = None,
                release_allowed: bool = False) -> ArtifactProof:
    state, blocked = proof_state(source_hash=source_hash, compiled_ir_hash=compiled_ir_hash, executed=executed,
                                 observed_sha256=observed_sha256, recorded_sha256=recorded_sha256, validations=validations,
                                 approval=approval, release_allowed=release_allowed)
    return ArtifactProof(project_ref=project_ref, artifact_ref=artifact_ref, version_ref=version_ref, source_hash=source_hash,
                         compiled_ir_hash=compiled_ir_hash, renderer_id=renderer_id, renderer_version=renderer_version,
                         output_sha256=observed_sha256, mime_type=mime_type, observed_dimensions=observed_dimensions,
                         file_size=file_size, dependency_hashes=dependency_hashes, license_refs=license_refs,
                         validation_results=validations, approval_ref=(approval or {}).get("approval_id"), state=state,
                         blocked_at=blocked)


__all__ = ["ORDER", "build_proof", "proof_state"]
